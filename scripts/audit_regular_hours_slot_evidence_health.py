from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CONTRACT = "orion-regular-hours-slot-evidence-health-v1"


def build_slot_evidence_report(
    reconciliation: dict[str, Any],
    evidence_by_run_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Join schedule reconciliation to artifact evidence without guessing mappings."""
    if reconciliation.get("contract") != "orion-regular-hours-daily-schedule-reconciliation-v1":
        raise ValueError("unexpected reconciliation contract")

    slots: list[dict[str, Any]] = []
    for slot in reconciliation.get("slots", []):
        schedule_status = slot.get("status")
        run_id = slot.get("matched_run_id")
        evidence = evidence_by_run_id.get(str(run_id)) if run_id is not None else None

        if schedule_status != "matched":
            status = schedule_status
            reason = "schedule mapping is not uniquely matched; evidence must not be attributed"
        elif evidence is None:
            status = "evidence_missing"
            reason = "matched scheduled run has no evidence record"
        elif evidence.get("run_conclusion") != "success":
            status = "run_failed"
            reason = f"matched run conclusion is {evidence.get('run_conclusion') or 'unknown'}"
        elif evidence.get("artifact_present") is not True:
            status = "artifact_missing"
            reason = "matched successful run has no expected evidence artifact"
        elif evidence.get("artifact_valid") is not True:
            status = "artifact_invalid"
            reason = str(evidence.get("artifact_error") or "evidence artifact failed validation")
        else:
            status = "healthy"
            reason = "matched run succeeded and expected evidence artifact passed validation"

        slots.append(
            {
                "slot_utc": slot.get("slot_utc"),
                "slot_et": slot.get("slot_et"),
                "matched_run_id": run_id,
                "schedule_status": schedule_status,
                "evidence_status": status,
                "healthy": status == "healthy",
                "reason": reason,
            }
        )

    counts: dict[str, int] = {}
    for row in slots:
        key = row["evidence_status"]
        counts[key] = counts.get(key, 0) + 1

    return {
        "contract": CONTRACT,
        "session_date_et": reconciliation.get("session_date_et"),
        "slot_count": len(slots),
        "healthy_slot_count": sum(row["healthy"] for row in slots),
        "counts": dict(sorted(counts.items())),
        "healthy": all(row["healthy"] for row in slots),
        "slots": slots,
        "warning": "Evidence is attributed only to uniquely matched scheduled runs; ambiguous schedule mappings remain unresolved.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Join regular-hours schedule reconciliation with per-run evidence health.")
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True, help="JSON object keyed by GitHub run id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    reconciliation = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    report = build_slot_evidence_report(reconciliation, evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["healthy"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
