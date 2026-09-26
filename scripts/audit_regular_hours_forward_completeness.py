from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Iterable

try:
    from scripts.audit_regular_hours_collection_health import (
        CollectionHealthError,
        _load_payload,
        build_health_report,
    )
except ModuleNotFoundError as exc:
    if exc.name != "scripts":
        raise
    from audit_regular_hours_collection_health import (
        CollectionHealthError,
        _load_payload,
        build_health_report,
    )

REPORT_CONTRACT = "orion-regular-hours-collection-health-v5"
FORWARD_PROTOCOL_ID = "regular-hours-v3-1-forward-validation-2026-09-12"
MIN_COMPLETE_SESSIONS_FOR_SCORE_INSPECTION = 30
PROVENANCE_SCHEMA = "regular-hours-v3-1-acquisition-provenance-v1"
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _session_is_complete(row: dict[str, Any]) -> bool:
    requested = int(row.get("requested_symbol_count") or 0)
    available = int(row.get("available_symbol_count") or 0)
    provenance_valid = int(row.get("provenance_valid_symbol_count") or 0)
    failures = int(row.get("failure_count") or 0)
    provenance_gaps = int(row.get("provenance_gap_symbol_count") or 0)
    lineages = row.get("predictive_lineages")
    return (
        requested > 0
        and available == requested
        and provenance_valid == requested
        and failures == 0
        and provenance_gaps == 0
        and isinstance(lineages, list)
        and len(lineages) == 1
    )


def _validate_acquisition_provenance(payload: dict[str, Any]) -> bool | None:
    provenance = payload.get("acquisition_provenance")
    if provenance is None:
        return None
    if not isinstance(provenance, dict):
        raise CollectionHealthError("acquisition_provenance must be an object")
    if provenance.get("schema") != PROVENANCE_SCHEMA:
        raise CollectionHealthError("unexpected acquisition_provenance schema")
    event_name = str(provenance.get("event_name") or "")
    if event_name not in {"schedule", "workflow_dispatch"}:
        raise CollectionHealthError("acquisition_provenance.event_name is invalid")
    if int(provenance.get("workflow_run_id") or 0) <= 0:
        raise CollectionHealthError("acquisition_provenance.workflow_run_id must be positive")
    if int(provenance.get("run_attempt") or 0) <= 0:
        raise CollectionHealthError("acquisition_provenance.run_attempt must be positive")
    head_sha = str(provenance.get("github_head_sha") or "").lower()
    if not SHA40_RE.fullmatch(head_sha):
        raise CollectionHealthError("acquisition_provenance.github_head_sha must be a Git SHA")
    source_sha = str(provenance.get("source_payload_sha256") or "").lower()
    if not SHA256_RE.fullmatch(source_sha):
        raise CollectionHealthError("acquisition_provenance.source_payload_sha256 must be SHA-256")
    forward_eligible = provenance.get("forward_eligible")
    if not isinstance(forward_eligible, bool):
        raise CollectionHealthError("acquisition_provenance.forward_eligible must be boolean")
    if forward_eligible and event_name != "schedule":
        raise CollectionHealthError("only scheduled artifacts can be forward_eligible")
    return forward_eligible


def add_session_completeness(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("score_blind") is not True or report.get("metrics_exposed") is not False:
        raise CollectionHealthError("collection-health input must remain score-blind")

    by_session = report.get("by_session")
    if not isinstance(by_session, dict):
        raise CollectionHealthError("collection-health report is missing by_session")

    complete_sessions: list[str] = []
    incomplete_sessions: list[str] = []
    for session, raw_row in sorted(by_session.items()):
        if not isinstance(raw_row, dict):
            raise CollectionHealthError("by_session entries must be objects")
        row = dict(raw_row)
        complete = _session_is_complete(row)
        row["complete_standard_session"] = complete
        by_session[session] = row
        (complete_sessions if complete else incomplete_sessions).append(session)

    active_lineage = report.get("latest_standard_predictive_lineage_sha256")
    cohort_sessions = [
        session
        for session in complete_sessions
        if active_lineage and by_session[session].get("predictive_lineages") == [active_lineage]
    ]
    cohort_count = len(cohort_sessions)
    remaining = max(0, MIN_COMPLETE_SESSIONS_FOR_SCORE_INSPECTION - cohort_count)
    lineage_counts = report.get("predictive_lineage_artifact_counts")
    lineage_change_detected = isinstance(lineage_counts, dict) and len(lineage_counts) > 1

    report["contract"] = REPORT_CONTRACT
    report["forward_validation_protocol"] = FORWARD_PROTOCOL_ID
    report["complete_standard_session_count"] = len(complete_sessions)
    report["incomplete_standard_session_count"] = len(incomplete_sessions)
    report["complete_standard_sessions"] = complete_sessions
    report["incomplete_standard_sessions"] = incomplete_sessions
    report["forward_validation_active_predictive_lineage_sha256"] = active_lineage
    report["forward_validation_predictive_lineage_change_detected"] = lineage_change_detected
    report["forward_validation_complete_session_count"] = cohort_count
    report["forward_validation_complete_sessions"] = cohort_sessions
    report["score_inspection_readiness_threshold_defined"] = True
    report["score_inspection_required_complete_sessions"] = MIN_COMPLETE_SESSIONS_FOR_SCORE_INSPECTION
    report["score_inspection_remaining_complete_sessions"] = remaining
    report["ready_for_score_inspection"] = bool(active_lineage) and cohort_count >= MIN_COMPLETE_SESSIONS_FOR_SCORE_INSPECTION
    report["promotion_authorized"] = False
    return report


def build_completeness_report(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    all_payloads = list(payloads)
    eligible: list[dict[str, Any]] = []
    non_forward = 0
    unattested = 0
    for payload in all_payloads:
        state = _validate_acquisition_provenance(payload)
        if state is True:
            eligible.append(payload)
        elif state is False:
            non_forward += 1
        else:
            unattested += 1

    report = add_session_completeness(build_health_report(eligible))
    report["recovered_artifact_count"] = len(all_payloads)
    report["forward_eligible_artifact_count"] = len(eligible)
    report["non_forward_artifact_count"] = non_forward
    report["unattested_legacy_artifact_count"] = unattested
    report["forward_population_requires_attestation"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit attested regular-hours V3.1 forward sessions and apply the "
            "pre-registered score-inspection gate without reading predictive scores."
        )
    )
    parser.add_argument("predictions", nargs="*", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/cloud_shadow/regular_hours_v3_1/collection-health.json"),
    )
    args = parser.parse_args()

    report = build_completeness_report(_load_payload(path) for path in args.predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
