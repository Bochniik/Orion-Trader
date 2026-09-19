from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

LEDGER_CONTRACT = "orion-cloud-shadow-evidence-ledger-v1"
CONTRACT = "orion-adaptive-research-diagnostics-v1"
DEFAULT_MIN_OBSERVATIONS = 12
DEFAULT_MIN_SESSIONS = 3
DEFAULT_MIN_EXCESS_ERROR = 0.10

SEMANTICS = (
    "Research-only settled-error diagnostics. The report may be used to generate challenger "
    "hypotheses, but any candidate influenced by this evidence must receive a new identity and "
    "a later preregistered forward cutoff. The same observations cannot both design and approve "
    "a challenger."
)


def _session(value: Any) -> str:
    text = str(value or "")
    if len(text) < 10:
        raise ValueError("prediction_time_utc is required")
    return text[:10]


def _probability(value: Any) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid probability_up: {value}") from exc
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise ValueError(f"Invalid probability_up: {value}")
    return p


def _actual(value: Any) -> int:
    try:
        actual = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid actual_up: {value}") from exc
    if actual not in (0, 1):
        raise ValueError(f"Invalid actual_up: {value}")
    return actual


def _confidence_band(probability_up: float) -> str:
    confidence = max(probability_up, 1.0 - probability_up)
    if confidence < 0.60:
        return "50-60"
    if confidence < 0.70:
        return "60-70"
    if confidence < 0.80:
        return "70-80"
    if confidence < 0.90:
        return "80-90"
    return "90-100"


def _direction(probability_up: float) -> str:
    return "UP" if probability_up >= 0.5 else "DOWN"


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 1.0)
    p = successes / total
    denominator = 1.0 + (z * z) / total
    center = (p + (z * z) / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt((p * (1.0 - p) / total) + (z * z) / (4.0 * total * total))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _normalize_records(payload: Mapping[str, Any], *, engine: str | None = None) -> list[dict[str, Any]]:
    if payload.get("contract") != LEDGER_CONTRACT:
        raise ValueError(f"Unsupported evidence ledger contract: {payload.get('contract')}")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("Evidence ledger records must be a list")

    normalized: list[dict[str, Any]] = []
    seen: dict[str, tuple[Any, ...]] = {}
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("Evidence ledger record must be an object")
        row_engine = str(raw.get("engine") or "").strip()
        symbol = str(raw.get("symbol") or "").upper().strip()
        horizon = str(raw.get("horizon") or "").strip()
        prediction_time = str(raw.get("prediction_time_utc") or "").strip()
        if not row_engine or not symbol or not horizon or not prediction_time:
            raise ValueError("Settled record missing engine/symbol/horizon/prediction_time_utc")
        if engine and row_engine != engine:
            continue

        probability_up = _probability(raw.get("probability_up"))
        actual_up = _actual(raw.get("actual_up"))
        predicted_up = probability_up >= 0.5
        error = int(predicted_up != bool(actual_up))
        record_id = str(raw.get("record_id") or "").strip()
        identity = record_id or "|".join(
            [
                row_engine,
                symbol,
                horizon,
                prediction_time,
                str(raw.get("target_time_utc") or ""),
            ]
        )
        fingerprint = (
            probability_up,
            actual_up,
            str(raw.get("target_time_utc") or ""),
            str(raw.get("material_sha256") or ""),
        )
        if identity in seen and seen[identity] != fingerprint:
            raise ValueError(f"Conflicting duplicate settled evidence: {identity}")
        if identity in seen:
            continue
        seen[identity] = fingerprint

        normalized.append(
            {
                "engine": row_engine,
                "symbol": symbol,
                "horizon": horizon,
                "prediction_time_utc": prediction_time,
                "session": _session(prediction_time),
                "probability_up": probability_up,
                "actual_up": actual_up,
                "error": error,
                "direction": _direction(probability_up),
                "confidence_band": _confidence_band(probability_up),
                "reliability_profile_source": str(raw.get("reliability_profile_source") or "unknown"),
                "profile_validated_for_symbol": raw.get("profile_validated_for_symbol"),
            }
        )
    return normalized


def _summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    total = len(values)
    errors = sum(int(row["error"]) for row in values)
    lower, upper = _wilson_interval(errors, total)
    return {
        "observations": total,
        "distinct_sessions": len({str(row["session"]) for row in values}),
        "errors": errors,
        "error_rate": round(errors / total, 6) if total else None,
        "error_rate_ci95": [round(lower, 6), round(upper, 6)] if total else None,
    }


def _group(rows: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(key_fn(row))].append(row)
    return {key: _summary(group_rows) for key, group_rows in sorted(grouped.items())}


def build_diagnostics(
    ledger: Mapping[str, Any],
    *,
    engine: str = "regular_hours_v3_1",
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
    min_sessions: int = DEFAULT_MIN_SESSIONS,
    min_excess_error: float = DEFAULT_MIN_EXCESS_ERROR,
) -> dict[str, Any]:
    if min_observations < 1 or min_sessions < 1:
        raise ValueError("Minimum coverage thresholds must be positive")
    if not 0.0 <= min_excess_error <= 1.0:
        raise ValueError("min_excess_error must be between 0 and 1")

    rows = _normalize_records(ledger, engine=engine)
    by_horizon_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_horizon_rows[row["horizon"]].append(row)

    hypotheses: list[dict[str, Any]] = []
    dimensions = {
        "direction": lambda row: row["direction"],
        "confidence_band": lambda row: row["confidence_band"],
        "symbol": lambda row: row["symbol"],
        "reliability_profile_source": lambda row: row["reliability_profile_source"],
    }

    horizon_reports: dict[str, Any] = {}
    for horizon, horizon_rows in sorted(by_horizon_rows.items()):
        baseline = _summary(horizon_rows)
        baseline_error = float(baseline["error_rate"] or 0.0)
        dimension_reports: dict[str, Any] = {}

        for dimension, key_fn in dimensions.items():
            grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in horizon_rows:
                grouped_rows[str(key_fn(row))].append(row)
            dimension_reports[dimension] = {
                key: _summary(group_rows) for key, group_rows in sorted(grouped_rows.items())
            }
            for key, group_rows in grouped_rows.items():
                summary = _summary(group_rows)
                error_rate = summary["error_rate"]
                ci = summary["error_rate_ci95"]
                excess = None if error_rate is None else round(float(error_rate) - baseline_error, 6)
                coverage_ok = (
                    summary["observations"] >= min_observations
                    and summary["distinct_sessions"] >= min_sessions
                )
                statistically_separated = bool(ci and ci[0] > baseline_error)
                if (
                    coverage_ok
                    and excess is not None
                    and excess >= min_excess_error
                    and statistically_separated
                ):
                    hypotheses.append(
                        {
                            "horizon": horizon,
                            "dimension": dimension,
                            "value": key,
                            "observations": summary["observations"],
                            "distinct_sessions": summary["distinct_sessions"],
                            "error_rate": error_rate,
                            "baseline_error_rate": round(baseline_error, 6),
                            "excess_error_rate": excess,
                            "error_rate_ci95": ci,
                            "status": "candidate_failure_pattern",
                        }
                    )

        horizon_reports[horizon] = {
            "baseline": baseline,
            "by_dimension": dimension_reports,
        }

    hypotheses.sort(
        key=lambda row: (
            -float(row["excess_error_rate"]),
            -int(row["observations"]),
            str(row["horizon"]),
            str(row["dimension"]),
            str(row["value"]),
        )
    )

    return {
        "contract": CONTRACT,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "semantics": SEMANTICS,
        "engine": engine,
        "settled_observations": len(rows),
        "distinct_sessions": len({row["session"] for row in rows}),
        "thresholds": {
            "minimum_observations": min_observations,
            "minimum_sessions": min_sessions,
            "minimum_excess_error_rate": min_excess_error,
            "uncertainty_interval": "wilson_95pct",
        },
        "safety": {
            "research_only": True,
            "runtime_modified": False,
            "automatic_promotion_allowed": False,
            "same_evidence_promotion_forbidden": True,
            "candidate_requires_new_identity": True,
            "candidate_requires_later_preregistered_forward_cutoff": True,
        },
        "horizons": horizon_reports,
        "candidate_failure_patterns": hypotheses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate research-only error diagnostics from Orion settled evidence."
    )
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--engine", default="regular_hours_v3_1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-observations", type=int, default=DEFAULT_MIN_OBSERVATIONS)
    parser.add_argument("--min-sessions", type=int, default=DEFAULT_MIN_SESSIONS)
    parser.add_argument("--min-excess-error", type=float, default=DEFAULT_MIN_EXCESS_ERROR)
    args = parser.parse_args()

    payload = json.loads(args.ledger.read_text(encoding="utf-8"))
    result = build_diagnostics(
        payload,
        engine=args.engine,
        min_observations=args.min_observations,
        min_sessions=args.min_sessions,
        min_excess_error=args.min_excess_error,
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
