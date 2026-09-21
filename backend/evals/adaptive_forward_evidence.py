from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.evals.adaptive_challenger_registry import assert_forward_evidence_eligible, validate_registration

CONTRACT = "orion-adaptive-forward-evidence-v1"


def _parse_utc(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _preregistered_minimums(validated: Mapping[str, Any]) -> tuple[int, int]:
    protocol = validated["candidate"].get("evaluation_protocol") or {}
    try:
        min_observations = int(protocol["min_forward_observations"])
        min_distinct_sessions = int(protocol["min_forward_distinct_sessions"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "evaluation_protocol must preregister positive min_forward_observations "
            "and min_forward_distinct_sessions before forward evidence is inspected"
        ) from exc
    if min_observations < 1 or min_distinct_sessions < 1:
        raise ValueError("preregistered forward evidence minimums must both be positive")
    return min_observations, min_distinct_sessions


def assess_forward_evidence_readiness(
    registration: Mapping[str, Any],
    records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    validated = validate_registration(registration)
    min_observations, min_distinct_sessions = _preregistered_minimums(validated)
    eligibility = assert_forward_evidence_eligible(validated, records)
    allowed_horizons = set(validated["candidate"]["horizons"])

    sessions: set[str] = set()
    malformed_session_count = 0
    duplicate_keys: set[tuple[str, str, str]] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    horizon_counts = {horizon: 0 for horizon in sorted(allowed_horizons)}

    for row in records:
        timestamp = row.get("timestamp") or row.get("prediction_time_utc")
        horizon = str(row.get("horizon") or "")
        symbol = str(row.get("symbol") or "").upper()
        try:
            parsed = _parse_utc(timestamp, field="evidence timestamp")
        except ValueError:
            continue
        session = str(row.get("session_date") or row.get("trading_session") or "").strip()
        if not session:
            malformed_session_count += 1
        else:
            sessions.add(session)
        if horizon in horizon_counts:
            horizon_counts[horizon] += 1
        key = (parsed.isoformat(), symbol, horizon)
        if key in seen_keys:
            duplicate_keys.add(key)
        seen_keys.add(key)

    enough_observations = len(records) >= min_observations
    enough_sessions = len(sessions) >= min_distinct_sessions
    all_horizons_observed = all(count > 0 for count in horizon_counts.values())
    ready = (
        eligibility["forward_evidence_eligible"]
        and malformed_session_count == 0
        and not duplicate_keys
        and enough_observations
        and enough_sessions
        and all_horizons_observed
    )

    return {
        "contract": CONTRACT,
        "candidate_id": validated["candidate_id"],
        "forward_cutoff_utc": eligibility["forward_cutoff_utc"],
        "observations": len(records),
        "distinct_sessions": len(sessions),
        "min_observations": min_observations,
        "min_distinct_sessions": min_distinct_sessions,
        "horizon_observations": horizon_counts,
        "invalid_timestamp_count": eligibility["invalid_timestamp_count"],
        "at_or_before_cutoff_count": eligibility["at_or_before_cutoff_count"],
        "wrong_horizon_count": eligibility["wrong_horizon_count"],
        "missing_session_count": malformed_session_count,
        "duplicate_observation_count": len(duplicate_keys),
        "tournament_ready": ready,
        "safety": {
            "research_only": True,
            "runtime_modified": False,
            "automatic_promotion_allowed": False,
            "pre_cutoff_evidence_forbidden": True,
            "same_evidence_approval_forbidden": True,
            "readiness_thresholds_preregistered": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess untouched Orion challenger evidence before tournament scoring.")
    parser.add_argument("registration", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registration = json.loads(args.registration.read_text(encoding="utf-8"))
    records = json.loads(args.evidence.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("evidence must be a JSON list")
    result = assess_forward_evidence_readiness(registration, records)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
