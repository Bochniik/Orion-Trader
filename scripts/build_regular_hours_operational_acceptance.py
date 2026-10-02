from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any, Iterable

from audit_regular_hours_collection_health import CollectionHealthError, _validate_projection
from audit_regular_hours_slot_evidence_health import build_slot_evidence_report
from reconcile_regular_hours_schedule_delivery import reconcile_day

CONTRACT = "orion-regular-hours-operational-acceptance-v2"
EXPECTED_ARTIFACT_PREFIX = "regular-hours-v3-1-shadow-"
EXPECTED_PROVENANCE_SCHEMA = "regular-hours-v3-1-acquisition-provenance-v1"


def _validate_acquisition_provenance(payload: dict[str, Any], *, run_id: str, run: dict[str, Any]) -> None:
    provenance = payload.get("acquisition_provenance")
    if not isinstance(provenance, dict):
        raise CollectionHealthError("artifact acquisition_provenance is required")
    if provenance.get("schema") != EXPECTED_PROVENANCE_SCHEMA:
        raise CollectionHealthError("artifact acquisition_provenance schema is invalid")
    if str(provenance.get("workflow_run_id") or "") != run_id:
        raise CollectionHealthError("artifact acquisition_provenance workflow_run_id does not match owning workflow run")
    if provenance.get("event_name") != "schedule":
        raise CollectionHealthError("artifact acquisition_provenance event_name must be schedule")
    if provenance.get("forward_eligible") is not True:
        raise CollectionHealthError("artifact acquisition_provenance must be forward_eligible")

    if run.get("run_attempt") is not None:
        try:
            payload_attempt = int(provenance.get("run_attempt"))
            run_attempt = int(run["run_attempt"])
        except (TypeError, ValueError) as exc:
            raise CollectionHealthError("artifact acquisition_provenance run_attempt is invalid") from exc
        if payload_attempt != run_attempt:
            raise CollectionHealthError("artifact acquisition_provenance run_attempt does not match owning workflow run")

    if run.get("head_sha") is not None:
        if str(provenance.get("github_head_sha") or "").lower() != str(run["head_sha"]).lower():
            raise CollectionHealthError("artifact acquisition_provenance github_head_sha does not match owning workflow run")


def build_evidence_by_run_id(
    *,
    runs: Iterable[dict[str, Any]],
    artifacts: Iterable[dict[str, Any]],
    artifact_payloads: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build per-run evidence records without treating artifact names as validation."""
    run_by_id = {str(run.get("id")): run for run in runs if run.get("id") is not None}
    artifacts_by_run: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        workflow_run = artifact.get("workflow_run") or {}
        run_id = workflow_run.get("id") or artifact.get("workflow_run_id")
        if run_id is None:
            continue
        artifacts_by_run.setdefault(str(run_id), []).append(artifact)

    evidence: dict[str, dict[str, Any]] = {}
    for run_id, run in run_by_id.items():
        expected_name = f"{EXPECTED_ARTIFACT_PREFIX}{run_id}"
        candidates = [item for item in artifacts_by_run.get(run_id, []) if item.get("name") == expected_name and item.get("expired") is not True]
        record: dict[str, Any] = {
            "run_conclusion": run.get("conclusion"),
            "artifact_present": bool(candidates),
            "artifact_valid": False,
        }
        if len(candidates) > 1:
            record["artifact_error"] = "multiple non-expired artifacts have the expected run-specific name"
        elif not candidates:
            record["artifact_error"] = "expected run-specific artifact is missing or expired"
        else:
            artifact = candidates[0]
            artifact_id = str(artifact.get("id"))
            payload = artifact_payloads.get(artifact_id)
            if payload is None:
                record["artifact_error"] = "artifact payload was not supplied for validation"
            else:
                try:
                    projection = _validate_projection(payload)
                    _validate_acquisition_provenance(payload, run_id=run_id, run=run)
                    record["artifact_valid"] = True
                    record["artifact_projection"] = projection
                except (CollectionHealthError, TypeError, ValueError) as exc:
                    record["artifact_error"] = str(exc)
        evidence[run_id] = record
    return evidence


def build_operational_acceptance_report(
    *,
    session_date: date,
    runs: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    artifact_payloads: dict[str, dict[str, Any]],
    match_window_minutes: float = 20.0,
) -> dict[str, Any]:
    reconciliation = reconcile_day(session_date=session_date, runs=runs, match_window_minutes=match_window_minutes)
    evidence = build_evidence_by_run_id(runs=runs, artifacts=artifacts, artifact_payloads=artifact_payloads)
    slot_report = build_slot_evidence_report(reconciliation, evidence)
    expected = int(slot_report["slot_count"])
    healthy = int(slot_report["healthy_slot_count"])
    return {
        "contract": CONTRACT,
        "session_date_et": session_date.isoformat(),
        "expected_slot_count": expected,
        "healthy_slot_count": healthy,
        "acceptance_rate": None if expected == 0 else round(healthy / expected, 6),
        "healthy": bool(slot_report["healthy"]),
        "counts": slot_report["counts"],
        "slots": slot_report["slots"],
        "unmatched_scheduled_runs": reconciliation["unmatched_scheduled_runs"],
        "warning": "A slot is accepted only after unique schedule reconciliation, successful run completion, expected non-expired artifact presence, collection-health validation, and matching acquisition provenance.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an end-to-end Regular-hours operational acceptance report from GitHub run/artifact metadata and extracted prediction payloads.")
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--artifacts-json", type=Path, required=True)
    parser.add_argument("--artifact-payloads-json", type=Path, required=True, help="JSON object keyed by GitHub artifact id containing extracted prediction payloads")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--match-window-minutes", type=float, default=20.0)
    args = parser.parse_args()

    runs_payload = json.loads(args.runs_json.read_text(encoding="utf-8"))
    artifact_payload = json.loads(args.artifacts_json.read_text(encoding="utf-8"))
    runs = runs_payload.get("workflow_runs", []) if isinstance(runs_payload, dict) else runs_payload
    artifacts = artifact_payload.get("artifacts", []) if isinstance(artifact_payload, dict) else artifact_payload
    extracted = json.loads(args.artifact_payloads_json.read_text(encoding="utf-8"))
    report = build_operational_acceptance_report(session_date=date.fromisoformat(args.session_date), runs=runs, artifacts=artifacts, artifact_payloads=extracted, match_window_minutes=args.match_window_minutes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["healthy"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
