from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from audit_early_premarket_acquisition_health import RunEvidence, build_health_report

CONTRACT = "orion-early-premarket-run-history-reconciliation-v1"
WORKFLOW_NAME = "Early premarket observational collection"


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("run timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _target_slot(run: dict[str, Any]) -> str | None:
    # Prefer explicit immutable evidence exported by a run-history collector.
    explicit = run.get("target_slot_et")
    if explicit:
        return str(explicit)

    # GitHub scheduled runs expose the cron expression, not the resolved ET slot.
    # Do not infer an ET target from created_at: queue delay would make that
    # provenance claim unsafe. Such runs stay unattributed until explicit slot
    # evidence is available.
    return None


def normalize_runs(raw_runs: Iterable[dict[str, Any]]) -> tuple[list[RunEvidence], list[str]]:
    evidence: list[RunEvidence] = []
    ignored: list[str] = []
    for run in raw_runs:
        run_id = str(run.get("id") or run.get("run_id") or "")
        if not run_id:
            raise ValueError("every run must have an id")
        if run.get("name") != WORKFLOW_NAME:
            ignored.append(run_id)
            continue
        created = run.get("created_at")
        if not created:
            raise ValueError(f"run {run_id} is missing created_at")
        evidence.append(
            RunEvidence(
                run_id=run_id,
                created_at_utc=_parse_utc(str(created)),
                conclusion=run.get("conclusion"),
                target_slot_et=_target_slot(run),
            )
        )
    return evidence, sorted(ignored)


def reconcile(
    *, session_date: date, raw_runs: Iterable[dict[str, Any]], observed_at_utc: datetime
) -> dict[str, Any]:
    evidence, ignored = normalize_runs(raw_runs)
    health = build_health_report(
        session_date=session_date,
        runs=evidence,
        observed_at_utc=observed_at_utc,
    )
    mature = [slot for slot in health["slots"] if slot["status"] != "pending"]
    succeeded = [slot for slot in mature if slot["status"] == "collector_succeeded"]
    attributed = sum(len(slot["run_ids"]) for slot in mature)
    return {
        "contract": CONTRACT,
        "session_date": session_date.isoformat(),
        "health": health,
        "metrics": {
            "mature_slot_count": len(mature),
            "successful_slot_count": len(succeeded),
            "coverage_ratio": (len(succeeded) / len(mature)) if mature else None,
            "normalized_workflow_run_count": len(evidence),
            "attributed_run_count": attributed,
            "unattributed_run_count": len(health["unattributed_run_ids"]),
        },
        "ignored_run_ids": ignored,
        "provenance_warning": (
            "GitHub run created_at is not a target-slot identity. Runs without explicit "
            "target_slot_et remain unattributed and cannot prove point-in-time coverage."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile early-premarket GitHub run history")
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--session-date", type=date.fromisoformat, required=True)
    parser.add_argument("--observed-at-utc", required=True)
    args = parser.parse_args()
    raw = json.loads(args.runs_json.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("workflow_runs", [])
    report = reconcile(
        session_date=args.session_date,
        raw_runs=raw,
        observed_at_utc=_parse_utc(args.observed_at_utc),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
