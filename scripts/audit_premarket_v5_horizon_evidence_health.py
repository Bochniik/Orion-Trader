from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any, Iterable

import scripts.audit_premarket_v5_collection_health as collection_health
import scripts.audit_premarket_v5_evidence_health as base
import scripts.audit_premarket_v5_forward_readiness as readiness
import scripts.audit_premarket_v5_schedule_delivery as delivery


REPORT_CONTRACT = "orion-premarket-v5-evidence-health-v3"
STATUS_ORDER = (
    "missing_delivery",
    "workflow_unsuccessful",
    "artifact_missing_after_success",
    "forecast_incomplete",
    "acquisition_ineligible",
    "horizon_ineligible",
    "horizon_partially_prospective",
    "decision_grade_complete",
)


def _projection_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row["session"]), str(row["snapshot"]), str(row.get("github_run_id") or ""))


def _horizon_maps(projection: dict[str, Any]) -> tuple[dict[str, bool], dict[str, bool]]:
    eligible = {
        horizon: bool(projection.get("horizon_forward_eligible", {}).get(horizon, False))
        for horizon in readiness.HORIZON_MINUTES
    }
    complete = {
        horizon: bool(projection.get("decision_grade_complete_by_horizon", {}).get(horizon, False))
        for horizon in readiness.HORIZON_MINUTES
    }
    return eligible, complete


def _reclassify_matched_row(row: dict[str, Any], projection: dict[str, Any]) -> None:
    eligible, complete = _horizon_maps(projection)
    row["horizon_forward_eligible"] = eligible
    row["decision_grade_complete_by_horizon"] = complete

    # Preserve stronger upstream failure classes. Horizon timing only refines rows
    # that the v2 report would otherwise call globally decision-grade.
    if row.get("status") != "decision_grade_complete":
        return

    complete_values = list(complete.values())
    if complete_values and all(complete_values):
        return
    if any(complete_values):
        row["status"] = "horizon_partially_prospective"
    else:
        row["status"] = "horizon_ineligible"


def _rebuild_summary(report: dict[str, Any]) -> None:
    rows = report["evidence_rows"]
    status_counts = Counter(row["status"] for row in rows)
    schedule_summary = report["schedule_delivery"]["summary"]
    duplicate_count = int(schedule_summary["duplicate_delivery_count"])
    unmatched_count = len(report["unmatched_artifacts"])

    all_mature_slots_decision_grade = bool(rows) and all(row["status"] == "decision_grade_complete" for row in rows)
    all_by_horizon = {
        horizon: bool(rows)
        and all(bool(row.get("decision_grade_complete_by_horizon", {}).get(horizon, False)) for row in rows)
        for horizon in readiness.HORIZON_MINUTES
    }
    counts_by_horizon = {
        horizon: sum(
            1 for row in rows if bool(row.get("decision_grade_complete_by_horizon", {}).get(horizon, False))
        )
        for horizon in readiness.HORIZON_MINUTES
    }

    historically_gap_free = bool(
        all_mature_slots_decision_grade
        and schedule_summary["missing_count"] == 0
        and schedule_summary["unsuccessful_count"] == 0
    )
    structurally_clean = duplicate_count == 0 and unmatched_count == 0
    cohort_mature = bool(report["forward_readiness"]["readiness"]["ready_for_issue_3_score_inspection"])

    historical_incident_layers: list[str] = []
    if schedule_summary["missing_count"]:
        historical_incident_layers.append("delivery")
    if schedule_summary["unsuccessful_count"]:
        historical_incident_layers.append("workflow_execution")
    if status_counts["artifact_missing_after_success"]:
        historical_incident_layers.append("artifact_persistence")
    if status_counts["forecast_incomplete"]:
        historical_incident_layers.append("forecast_completeness")
    if status_counts["acquisition_ineligible"]:
        historical_incident_layers.append("acquisition_eligibility")
    if status_counts["horizon_ineligible"] or status_counts["horizon_partially_prospective"]:
        historical_incident_layers.append("horizon_acquisition_eligibility")

    blocking_layers: list[str] = []
    if duplicate_count:
        blocking_layers.append("duplicate_delivery")
    if unmatched_count:
        blocking_layers.append("unmatched_artifact")
    if not cohort_mature:
        blocking_layers.append("cohort_maturity")

    report["summary"] = {
        "mature_expected_slot_count": len(rows),
        "status_counts": {status: status_counts.get(status, 0) for status in STATUS_ORDER},
        "recovered_transport_count": sum(1 for row in rows if row["recovered_transport"]),
        "duplicate_delivery_count": duplicate_count,
        "unmatched_artifact_count": unmatched_count,
        "decision_grade_complete_by_horizon_counts": counts_by_horizon,
        "all_mature_slots_decision_grade_complete_by_horizon": all_by_horizon,
        "all_mature_slots_decision_grade_complete": all_mature_slots_decision_grade,
        "historically_gap_free": historically_gap_free,
        "operationally_clean": historically_gap_free and structurally_clean,
        "structurally_clean": structurally_clean,
        "ready_for_issue_3_score_inspection": bool(cohort_mature and structurally_clean),
        "historical_incident_layers": historical_incident_layers,
        "blocking_layers": blocking_layers,
    }


def _rebuild_per_snapshot(report: dict[str, Any]) -> None:
    rows = report["evidence_rows"]
    rebuilt: dict[str, dict[str, Any]] = {}
    for snapshot in collection_health.SNAPSHOT_CLOCKS:
        snapshot_rows = [row for row in rows if row["snapshot"] == snapshot]
        counts = Counter(row["status"] for row in snapshot_rows)
        readiness_row = report["forward_readiness"]["readiness"]["per_snapshot"][snapshot]
        per_horizon = {
            horizon: {
                "decision_grade_complete_slot_count": sum(
                    1
                    for row in snapshot_rows
                    if bool(row.get("decision_grade_complete_by_horizon", {}).get(horizon, False))
                ),
                **deepcopy(readiness_row["per_horizon"][horizon]),
            }
            for horizon in readiness.HORIZON_MINUTES
        }
        rebuilt[snapshot] = {
            "mature_expected_slot_count": len(snapshot_rows),
            "status_counts": {status: counts.get(status, 0) for status in STATUS_ORDER},
            "recovered_transport_count": sum(1 for row in snapshot_rows if row["recovered_transport"]),
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
            "per_horizon": per_horizon,
        }
    report["per_snapshot"] = rebuilt


def build_evidence_health_report(
    runs: Iterable[dict[str, Any]],
    payloads: Iterable[dict[str, Any]],
    *,
    start_date: date,
    as_of: datetime,
) -> dict[str, Any]:
    materialized_payloads = list(payloads)
    report = base.build_evidence_health_report(runs, materialized_payloads, start_date=start_date, as_of=as_of)
    report["contract"] = REPORT_CONTRACT

    projections = [readiness.validate_acquisition(payload) for payload in materialized_payloads]
    projection_by_key = {_projection_key(projection): projection for projection in projections}

    for row in report["evidence_rows"]:
        run_id = str(row.get("github_run_id") or "")
        if not run_id:
            continue
        projection = projection_by_key.get((str(row["session"]), str(row["snapshot"]), run_id))
        if projection is not None:
            _reclassify_matched_row(row, projection)

    for row in report["unmatched_artifacts"]:
        projection = projection_by_key.get(_projection_key(row))
        if projection is None:
            continue
        eligible, complete = _horizon_maps(projection)
        row["horizon_forward_eligible"] = eligible
        row["decision_grade_complete_by_horizon"] = complete

    _rebuild_summary(report)
    _rebuild_per_snapshot(report)

    score_blind_material = {
        "contract": REPORT_CONTRACT,
        "schedule_delivery_sha256": report["input_identities"]["schedule_delivery_sha256"],
        "forward_readiness_sha256": report["input_identities"]["forward_readiness_sha256"],
        "evidence_rows": report["evidence_rows"],
        "unmatched_projection_count": len(report["unmatched_artifacts"]),
    }
    report["input_identities"]["evidence_health_identity_sha256"] = base._canonical_sha256(score_blind_material)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a horizon-aware, score-blind Premarket V5 evidence-health report."
    )
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--as-of", required=True, help="Timezone-aware ISO timestamp")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        as_of = base._parse_timestamp(args.as_of, field="as_of")
        report = build_evidence_health_report(
            base._load_runs(args.runs_json),
            (base._load_payload(path) for path in args.input),
            start_date=args.start_date,
            as_of=as_of,
        )
    except (
        OSError,
        json.JSONDecodeError,
        base.EvidenceHealthError,
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
