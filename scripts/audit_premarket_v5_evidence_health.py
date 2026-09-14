from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_premarket_v5_forward_readiness as readiness
import scripts.audit_premarket_v5_schedule_delivery as delivery
import scripts.audit_premarket_v5_collection_health as collection_health


REPORT_CONTRACT = "orion-premarket-v5-evidence-health-v2"
STATUS_ORDER = (
    "missing_delivery",
    "workflow_unsuccessful",
    "artifact_missing_after_success",
    "forecast_incomplete",
    "acquisition_ineligible",
    "decision_grade_complete",
)


class EvidenceHealthError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EvidenceHealthError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise EvidenceHealthError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _projection_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row["session"]), str(row["snapshot"]), str(row.get("github_run_id") or ""))


def build_evidence_health_report(
    runs: Iterable[dict[str, Any]],
    payloads: Iterable[dict[str, Any]],
    *,
    start_date: date,
    as_of: datetime,
) -> dict[str, Any]:
    materialized_payloads = list(payloads)
    schedule_report = delivery.build_schedule_delivery_report(runs, start_date=start_date, as_of=as_of)
    forward_report = readiness.build_forward_readiness_report(materialized_payloads)
    projections = [readiness.validate_acquisition(payload) for payload in materialized_payloads]
    projections.sort(key=_projection_key)

    projection_by_key = {_projection_key(row): row for row in projections}
    consumed_projection_keys: set[tuple[str, str, str]] = set()
    evidence_rows: list[dict[str, Any]] = []

    for delivered in schedule_report.get("deliveries", []):
        status: str
        matched_projection: dict[str, Any] | None = None

        if not delivered["delivered"]:
            status = "missing_delivery"
        elif not delivered["successful"]:
            status = "workflow_unsuccessful"
        else:
            matching = [
                projection_by_key[(delivered["session"], delivered["snapshot"], str(run_id))]
                for run_id in delivered["run_ids"]
                if (delivered["session"], delivered["snapshot"], str(run_id)) in projection_by_key
            ]
            if not matching:
                status = "artifact_missing_after_success"
            else:
                if len(matching) > 1:
                    raise EvidenceHealthError(
                        f"multiple prediction artifacts match successful delivery {delivered['session']}:{delivered['snapshot']}"
                    )
                matched_projection = matching[0]
                consumed_projection_keys.add(_projection_key(matched_projection))
                if not matched_projection["forecast_complete"]:
                    status = "forecast_incomplete"
                elif not matched_projection["forward_eligible"]:
                    status = "acquisition_ineligible"
                else:
                    status = "decision_grade_complete"

        row = {
            "session": delivered["session"],
            "snapshot": delivered["snapshot"],
            "target_utc": delivered["target_utc"],
            "schedule_cron": delivered["schedule_cron"],
            "status": status,
            "run_count": delivered["run_count"],
            "run_ids": list(delivered["run_ids"]),
        }
        if matched_projection is not None:
            row.update(
                {
                    "forecast_complete": matched_projection["forecast_complete"],
                    "forward_eligible": matched_projection["forward_eligible"],
                    "eligibility_reason": matched_projection["eligibility_reason"],
                    "github_run_id": matched_projection["github_run_id"],
                }
            )
        evidence_rows.append(row)

    unmatched = [row for row in projections if _projection_key(row) not in consumed_projection_keys]
    status_counts = Counter(row["status"] for row in evidence_rows)
    per_snapshot: dict[str, dict[str, Any]] = {}
    for snapshot in collection_health.SNAPSHOT_CLOCKS:
        rows = [row for row in evidence_rows if row["snapshot"] == snapshot]
        counts = Counter(row["status"] for row in rows)
        readiness_row = forward_report["readiness"]["per_snapshot"][snapshot]
        per_snapshot[snapshot] = {
            "mature_expected_slot_count": len(rows),
            "status_counts": {status: counts.get(status, 0) for status in STATUS_ORDER},
            "decision_grade_complete_distinct_session_count": readiness_row[
                "decision_grade_complete_distinct_session_count"
            ],
            "required_decision_grade_complete_distinct_session_count": readiness_row[
                "required_decision_grade_complete_distinct_session_count"
            ],
            "remaining_decision_grade_complete_distinct_session_count": readiness_row[
                "remaining_decision_grade_complete_distinct_session_count"
            ],
            "ready": readiness_row["ready"],
        }

    duplicate_count = schedule_report["summary"]["duplicate_delivery_count"]
    all_mature_slots_decision_grade = bool(evidence_rows) and all(
        row["status"] == "decision_grade_complete" for row in evidence_rows
    )
    # Historical transport/acquisition incidents are measured, but they do not
    # permanently poison a cohort that later reaches the preregistered count of
    # complete, forward-eligible sessions. Structural provenance ambiguity still
    # fails closed because it can make the accepted evidence population unclear.
    historically_gap_free = all_mature_slots_decision_grade
    structurally_clean = duplicate_count == 0 and not unmatched
    # Preserve the v1 field's composite meaning for compatibility. In v2 it is
    # diagnostic only; score-inspection readiness is cohort maturity plus the
    # explicit structural-integrity gate below.
    operationally_clean = historically_gap_free and structurally_clean
    cohort_mature = forward_report["readiness"]["ready_for_issue_3_score_inspection"]
    ready_for_score_inspection = bool(cohort_mature and structurally_clean)

    historical_incident_layers: list[str] = []
    if status_counts["missing_delivery"]:
        historical_incident_layers.append("delivery")
    if status_counts["workflow_unsuccessful"]:
        historical_incident_layers.append("workflow_execution")
    if status_counts["artifact_missing_after_success"]:
        historical_incident_layers.append("artifact_persistence")
    if status_counts["forecast_incomplete"]:
        historical_incident_layers.append("forecast_completeness")
    if status_counts["acquisition_ineligible"]:
        historical_incident_layers.append("acquisition_eligibility")

    blocking_layers: list[str] = []
    if duplicate_count:
        blocking_layers.append("duplicate_delivery")
    if unmatched:
        blocking_layers.append("unmatched_artifact")
    if not cohort_mature:
        blocking_layers.append("cohort_maturity")

    score_blind_material = {
        "schedule_delivery_sha256": _canonical_sha256(schedule_report),
        "forward_readiness_sha256": _canonical_sha256(forward_report),
        "evidence_rows": evidence_rows,
        "unmatched_projection_count": len(unmatched),
    }

    return {
        "contract": REPORT_CONTRACT,
        "score_blind": True,
        "metrics_exposed": False,
        "audit_window": {
            "start_date": start_date.isoformat(),
            "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        },
        "input_identities": {
            "schedule_delivery_sha256": score_blind_material["schedule_delivery_sha256"],
            "forward_readiness_sha256": score_blind_material["forward_readiness_sha256"],
            "evidence_health_identity_sha256": _canonical_sha256(score_blind_material),
        },
        "summary": {
            "mature_expected_slot_count": len(evidence_rows),
            "status_counts": {status: status_counts.get(status, 0) for status in STATUS_ORDER},
            "duplicate_delivery_count": duplicate_count,
            "unmatched_artifact_count": len(unmatched),
            "all_mature_slots_decision_grade_complete": all_mature_slots_decision_grade,
            "historically_gap_free": historically_gap_free,
            "operationally_clean": operationally_clean,
            "structurally_clean": structurally_clean,
            "ready_for_issue_3_score_inspection": ready_for_score_inspection,
            "historical_incident_layers": historical_incident_layers,
            "blocking_layers": blocking_layers,
        },
        "per_snapshot": per_snapshot,
        "evidence_rows": evidence_rows,
        "unmatched_artifacts": [
            {
                "session": row["session"],
                "snapshot": row["snapshot"],
                "github_run_id": row["github_run_id"],
                "forecast_complete": row["forecast_complete"],
                "forward_eligible": row["forward_eligible"],
                "eligibility_reason": row["eligibility_reason"],
            }
            for row in unmatched
        ],
        "schedule_delivery": schedule_report,
        "forward_readiness": forward_report,
    }


def _load_runs(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("workflow_runs")
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise EvidenceHealthError("runs JSON must be an array or an object containing workflow_runs[]")
    return data


def _load_payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise EvidenceHealthError(f"{path}: prediction artifact must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build one score-blind Premarket V5 evidence-health report from schedule delivery and forward artifacts."
    )
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--as-of", required=True, help="Timezone-aware ISO timestamp")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        as_of = _parse_timestamp(args.as_of, field="as_of")
        report = build_evidence_health_report(
            _load_runs(args.runs_json),
            (_load_payload(path) for path in args.input),
            start_date=args.start_date,
            as_of=as_of,
        )
    except (
        OSError,
        json.JSONDecodeError,
        EvidenceHealthError,
        delivery.ScheduleDeliveryError,
        readiness.ForwardReadinessError,
        collection_health.CollectionHealthError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "invalid_evidence_health_input", "error": str(exc)}, sort_keys=True))
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
