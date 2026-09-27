from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo


REVIEW_VERSION = "orion-daily-close-review-v1"
_NEW_YORK = ZoneInfo("America/New_York")
_EPSILON = 1e-15
MIN_SECTOR_CONTEXT_SLICE_SIZE = 30


def read_user_settled_evidence(db: Any, user_id: str) -> List[Dict[str, Any]]:
    """Read settled forecast evidence owned by one user only.

    The ownership predicate is deliberately enforced in SQL so callers cannot
    accidentally score another user's rows and filter them afterwards.
    """
    rows = db.execute(
        """
        SELECT
            f.probability_up,
            f.forecast_horizon,
            o.actual_up,
            o.resolved_at,
            p.snapshot_json
        FROM probability_outcomes o
        JOIN probability_forecasts f
            ON f.id = o.forecast_id
        JOIN opportunity_predictions p
            ON p.id = f.prediction_id
        WHERE p.user_id = ?
        ORDER BY o.resolved_at ASC, o.id ASC
        """,
        (str(user_id),),
    ).fetchall()
    evidence = []
    for row in rows:
        item = dict(row)
        snapshot_json = item.pop("snapshot_json", None)
        try:
            snapshot = json.loads(snapshot_json) if snapshot_json else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            snapshot = {}
        item["sector_context_availability"] = _sector_context_availability(
            snapshot
        )
        evidence.append(item)
    return evidence


def _sector_context_availability(snapshot: Any) -> Optional[str]:
    if not isinstance(snapshot, dict):
        return None

    component = (
        ((snapshot.get("opportunity_score") or {}).get("component_evidence") or {})
        .get("sector_confirmation") or {}
    )
    status = component.get("status")
    if status in {"aligned", "not_aligned"}:
        return "available"
    if status == "unavailable":
        return "unavailable"

    source = (
        (snapshot.get("feature_source_diagnostics") or {})
        .get("sector_benchmark") or {}
    )
    status = source.get("status")
    if status == "fresh":
        return "available"
    if status in {"unavailable", "blocked"}:
        return "unavailable"
    return None


def _finite_probability(value: Any) -> Optional[float]:
    try:
        probability = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(probability) or probability < 0.0 or probability > 1.0:
        return None
    return probability


def _actual_up(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed in (0, 1) else None


def _session_date(value: Any) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_NEW_YORK).date().isoformat()


def _score(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "sample_size": 0,
            "brier_score": None,
            "log_loss": None,
            "directional_accuracy": None,
            "false_positives": 0,
            "false_negatives": 0,
        }

    brier = 0.0
    log_loss = 0.0
    correct = 0
    false_positives = 0
    false_negatives = 0

    for row in rows:
        probability = row["probability_up"]
        actual = row["actual_up"]
        predicted = 1 if probability >= 0.5 else 0
        brier += (probability - actual) ** 2
        clipped = min(max(probability, _EPSILON), 1.0 - _EPSILON)
        log_loss -= actual * math.log(clipped) + (1 - actual) * math.log(1.0 - clipped)
        correct += int(predicted == actual)
        false_positives += int(predicted == 1 and actual == 0)
        false_negatives += int(predicted == 0 and actual == 1)

    size = len(rows)
    return {
        "sample_size": size,
        "brier_score": brier / size,
        "log_loss": log_loss / size,
        "directional_accuracy": correct / size,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def build_daily_close_review(
    evidence: Iterable[Dict[str, Any]],
    *,
    session_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Score settled evidence for one session; default to the latest settled session."""
    normalized: List[Dict[str, Any]] = []
    diagnostics = defaultdict(int)

    for row in evidence:
        probability = _finite_probability(row.get("probability_up"))
        actual = _actual_up(row.get("actual_up"))
        resolved_session = _session_date(row.get("resolved_at"))

        if probability is None:
            diagnostics["invalid_probability"] += 1
            continue
        if actual is None:
            diagnostics["missing_or_invalid_outcome"] += 1
            continue
        if resolved_session is None:
            diagnostics["invalid_resolved_at"] += 1
            continue

        sector_context = row.get("sector_context_availability")
        if sector_context not in {"available", "unavailable"}:
            sector_context = None
            diagnostics["missing_sector_context_status"] += 1

        normalized.append(
            {
                "probability_up": probability,
                "actual_up": actual,
                "horizon": str(row.get("forecast_horizon") or "unknown"),
                "session_date": resolved_session,
                "sector_context_availability": sector_context,
            }
        )

    effective_session = session_date
    if effective_session is None and normalized:
        effective_session = max(row["session_date"] for row in normalized)

    accepted: List[Dict[str, Any]] = []
    for row in normalized:
        if effective_session is not None and row["session_date"] != effective_session:
            diagnostics["outside_session"] += 1
            continue
        accepted.append(row)

    by_horizon: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_sector_context: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in accepted:
        by_horizon[row["horizon"]].append(row)
        sector_context = row["sector_context_availability"]
        if sector_context is not None:
            by_sector_context[sector_context].append(row)

    sector_slices = {
        status: _score(rows)
        for status, rows in sorted(by_sector_context.items())
    }
    sector_sample_sizes = {
        status: sector_slices.get(status, {}).get("sample_size", 0)
        for status in ("available", "unavailable")
    }
    underpowered = [
        status
        for status, size in sector_sample_sizes.items()
        if size < MIN_SECTOR_CONTEXT_SLICE_SIZE
    ]

    return {
        "version": REVIEW_VERSION,
        "session_date": effective_session,
        "metrics": _score(accepted),
        "by_horizon": {
            horizon: _score(rows)
            for horizon, rows in sorted(by_horizon.items())
        },
        "by_sector_context_availability": sector_slices,
        "sector_context_comparison": {
            "status": "insufficient_evidence" if underpowered else "ready",
            "minimum_sample_size_per_group": MIN_SECTOR_CONTEXT_SLICE_SIZE,
            "sample_sizes": sector_sample_sizes,
            "underpowered_groups": underpowered,
            "interpretation": (
                "descriptive_metrics_only"
                if underpowered
                else "eligible_for_descriptive_comparison"
            ),
            "promotion_eligible": False,
        },
        "diagnostics": dict(sorted(diagnostics.items())),
        "scoring_policy": "settled_evidence_only",
        "sector_slice_policy": (
            "explicit_point_in_time_status_only; unknown rows excluded from slices"
        ),
    }
