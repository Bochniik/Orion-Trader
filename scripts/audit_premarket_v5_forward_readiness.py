from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_premarket_v5_collection_health as health
import scripts.finalize_premarket_v5_forward_artifact as attestation


REPORT_CONTRACT = "orion-premarket-v5-forward-readiness-v2"
HORIZON_MINUTES = {
    "premarket_5m": 5,
    "premarket_15m": 15,
    "premarket_30m": 30,
}


class ForwardReadinessError(ValueError):
    pass


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ForwardReadinessError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ForwardReadinessError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_payload_sha256(payload: dict[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "acquisition_provenance"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _horizon_forward_eligibility(
    *,
    as_of: datetime,
    completed: datetime,
    globally_forward_eligible: bool,
) -> dict[str, bool]:
    missing = set(health.SUPPORTED_HORIZONS) - set(HORIZON_MINUTES)
    if missing:
        raise ForwardReadinessError(
            f"missing horizon timing policy for: {','.join(sorted(missing))}"
        )
    return {
        horizon: bool(
            globally_forward_eligible
            and completed < as_of + timedelta(minutes=HORIZON_MINUTES[horizon])
        )
        for horizon in health.SUPPORTED_HORIZONS
    }


def validate_acquisition(payload: dict[str, Any]) -> dict[str, Any]:
    provenance = payload.get("acquisition_provenance")
    if not isinstance(provenance, dict):
        raise ForwardReadinessError("prediction artifact is missing acquisition_provenance")
    if provenance.get("contract") != attestation.ATTESTATION_CONTRACT:
        raise ForwardReadinessError("unexpected acquisition provenance contract")

    expected_hash = _canonical_payload_sha256(payload)
    if provenance.get("prediction_payload_sha256_before_attestation") != expected_hash:
        raise ForwardReadinessError("prediction payload changed after acquisition attestation")

    started = _parse_timestamp(provenance.get("collection_started_at_utc"), field="collection_started_at_utc")
    completed = _parse_timestamp(provenance.get("collection_completed_at_utc"), field="collection_completed_at_utc")
    as_of = _parse_timestamp(payload.get("as_of_utc"), field="as_of_utc")
    if completed < started:
        raise ForwardReadinessError("collection completion precedes collection start")

    lag = (started - as_of).total_seconds() / 60.0
    stored_lag = provenance.get("collection_start_lag_minutes")
    if not isinstance(stored_lag, (int, float)) or abs(float(stored_lag) - lag) > 1e-5:
        raise ForwardReadinessError("collection_start_lag_minutes does not match timestamps")
    if provenance.get("max_early_skew_minutes") != attestation.MAX_EARLY_SKEW_MINUTES:
        raise ForwardReadinessError("acquisition early-skew policy drift")
    if provenance.get("max_start_lag_minutes") != attestation.MAX_START_LAG_MINUTES:
        raise ForwardReadinessError("acquisition start-lag policy drift")

    event_name = str(provenance.get("event_name") or "")
    run_id = provenance.get("github_run_id")
    run_attempt = provenance.get("github_run_attempt")
    if event_name == "schedule" and (not run_id or not isinstance(run_attempt, int) or run_attempt < 1):
        raise ForwardReadinessError("scheduled acquisition is missing GitHub run provenance")

    expected_eligible, expected_reason, _ = attestation.classify_forward_acquisition(
        payload=payload,
        collection_started_at=started,
        collection_completed_at=completed,
        event_name=event_name,
    )
    if provenance.get("forward_eligible") is not expected_eligible:
        raise ForwardReadinessError("forward_eligible does not match acquisition policy")
    if provenance.get("eligibility_reason") != expected_reason:
        raise ForwardReadinessError("eligibility_reason does not match acquisition policy")

    projection = health._validate_projection(payload)
    horizon_forward_eligible = _horizon_forward_eligibility(
        as_of=as_of,
        completed=completed,
        globally_forward_eligible=expected_eligible,
    )
    decision_grade_complete_by_horizon = {
        horizon: bool(projection["complete"] and eligible)
        for horizon, eligible in horizon_forward_eligible.items()
    }
    return {
        "session": projection["session"],
        "snapshot": projection["snapshot"],
        "forecast_complete": bool(projection["complete"]),
        "forward_eligible": expected_eligible,
        "horizon_forward_eligible": horizon_forward_eligible,
        "decision_grade_complete_by_horizon": decision_grade_complete_by_horizon,
        "decision_grade_complete": bool(
            projection["complete"] and all(horizon_forward_eligible.values())
        ),
        "eligibility_reason": expected_reason,
        "collection_start_lag_minutes": round(lag, 6),
        "collection_completed_at_utc": completed.isoformat(),
        "github_run_id": None if run_id is None else str(run_id),
        "github_run_attempt": run_attempt,
    }


def _projection_sha256(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_forward_readiness_report(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(payloads)
    operational = health.build_health_report(materialized)
    projections = [validate_acquisition(payload) for payload in materialized]
    projections.sort(key=lambda row: (row["session"], row["snapshot"], str(row.get("github_run_id"))))

    duplicates = Counter((row["session"], row["snapshot"]) for row in projections)
    duplicate_keys = [f"{session}:{snapshot}" for (session, snapshot), count in duplicates.items() if count > 1]
    if duplicate_keys:
        raise ForwardReadinessError(f"duplicate session/snapshot acquisition evidence: {','.join(sorted(duplicate_keys))}")

    reason_counts = Counter(row["eligibility_reason"] for row in projections if not row["forward_eligible"])
    horizon_eligible_counts = {
        horizon: sum(1 for row in projections if row["horizon_forward_eligible"][horizon])
        for horizon in health.SUPPORTED_HORIZONS
    }
    per_snapshot: dict[str, dict[str, Any]] = {}
    for snapshot in health.SNAPSHOT_CLOCKS:
        rows = [row for row in projections if row["snapshot"] == snapshot]
        distinct = len({row["session"] for row in rows})
        operational_complete = len({row["session"] for row in rows if row["forecast_complete"]})
        decision_complete = len({row["session"] for row in rows if row["decision_grade_complete"]})
        remaining = max(0, health.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT - decision_complete)
        per_horizon: dict[str, dict[str, Any]] = {}
        for horizon in health.SUPPORTED_HORIZONS:
            horizon_complete = len({
                row["session"]
                for row in rows
                if row["decision_grade_complete_by_horizon"][horizon]
            })
            horizon_remaining = max(
                0,
                health.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT - horizon_complete,
            )
            per_horizon[horizon] = {
                "prospective_decision_grade_complete_distinct_session_count": horizon_complete,
                "required_prospective_decision_grade_complete_distinct_session_count": health.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT,
                "remaining_prospective_decision_grade_complete_distinct_session_count": horizon_remaining,
                "ready": horizon_remaining == 0,
            }
        per_snapshot[snapshot] = {
            "distinct_session_count": distinct,
            "operational_complete_distinct_session_count": operational_complete,
            "decision_grade_complete_distinct_session_count": decision_complete,
            "required_decision_grade_complete_distinct_session_count": health.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT,
            "remaining_decision_grade_complete_distinct_session_count": remaining,
            "per_horizon": per_horizon,
            "ready": all(row["ready"] for row in per_horizon.values()),
        }

    ready = all(row["ready"] for row in per_snapshot.values())
    return {
        "contract": REPORT_CONTRACT,
        "score_blind": True,
        "metrics_exposed": False,
        "policy": {
            "required_complete_sessions_per_snapshot": health.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT,
            "required_event_name": "schedule",
            "max_early_skew_minutes": attestation.MAX_EARLY_SKEW_MINUTES,
            "max_start_lag_minutes": attestation.MAX_START_LAG_MINUTES,
            "horizon_prospective_rule": "collection_completed_at_utc < as_of_utc + horizon",
            "horizon_minutes": dict(HORIZON_MINUTES),
        },
        "operational_collection_health": operational,
        "forward_acquisition": {
            "artifact_count": len(projections),
            "forward_eligible_artifact_count": sum(1 for row in projections if row["forward_eligible"]),
            "forward_ineligible_artifact_count": sum(1 for row in projections if not row["forward_eligible"]),
            "horizon_forward_eligible_artifact_counts": horizon_eligible_counts,
            "ineligible_reason_counts": dict(sorted(reason_counts.items())),
            "projection_sha256": _projection_sha256(projections),
        },
        "readiness": {
            "ready_for_issue_3_score_inspection": ready,
            "per_snapshot": per_snapshot,
        },
    }


def _load_payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ForwardReadinessError(f"{path}: prediction artifact must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build score-blind Premarket V5 readiness that requires genuine scheduled forward acquisition provenance."
    )
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        report = build_forward_readiness_report(_load_payload(path) for path in args.input)
    except (OSError, json.JSONDecodeError, ForwardReadinessError, health.CollectionHealthError, ValueError) as exc:
        print(json.dumps({"status": "invalid_forward_readiness_input", "error": str(exc)}, sort_keys=True))
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "score_blind": True,
        "metrics_exposed": False,
        "ready_for_issue_3_score_inspection": report["readiness"]["ready_for_issue_3_score_inspection"],
        "per_snapshot": report["readiness"]["per_snapshot"],
        "forward_acquisition": report["forward_acquisition"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
