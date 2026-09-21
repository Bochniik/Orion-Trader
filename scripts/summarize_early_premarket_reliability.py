#!/usr/bin/env python3
"""Aggregate reconciled early-premarket reports without weakening provenance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

CONTRACT = "orion-early-premarket-acquisition-reliability-v1"
RECONCILIATION_CONTRACTS = {
    "orion-early-premarket-run-history-reconciliation-v1",
    "orion-early-premarket-run-history-reconciliation-v2",
}


def summarize(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(reports)
    if not rows:
        raise ValueError("at least one reconciled report is required")

    totals = {
        "mature_slot_count": 0,
        "successful_slot_count": 0,
        "missing_workflow_slot_count": 0,
        "failed_collector_slot_count": 0,
        "duplicate_slot_count": 0,
        "attributed_run_count": 0,
        "unattributed_run_count": 0,
    }
    sessions: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    for report in rows:
        contract = report.get("contract")
        if contract not in RECONCILIATION_CONTRACTS:
            raise ValueError(f"unsupported reconciliation contract: {contract!r}")
        health = report.get("health") or {}
        session_date = str(health.get("session_date") or "")
        if not session_date:
            raise ValueError("reconciled report is missing health.session_date")
        if session_date in seen_dates:
            raise ValueError(f"duplicate session report: {session_date}")
        seen_dates.add(session_date)

        metrics = report.get("metrics") or {}
        mature = int(metrics.get("mature_slot_count", 0))
        successful = int(metrics.get("successful_slot_count", 0))
        slots = [s for s in health.get("slots", []) if s.get("status") != "pending"]
        missing = sum(s.get("status") == "workflow_never_created" for s in slots)
        failed = sum(s.get("status") == "workflow_created_collector_failed" for s in slots)
        duplicate = sum(int(s.get("duplicate_run_count", 0)) > 0 for s in slots)
        attributed = int(metrics.get("attributed_run_count", 0))
        unattributed = int(metrics.get("unattributed_run_count", 0))

        if successful + missing + failed != mature:
            raise ValueError(f"slot accounting mismatch for {session_date}")

        values = (mature, successful, missing, failed, duplicate, attributed, unattributed)
        for key, value in zip(totals, values):
            totals[key] += value
        sessions.append({
            "session_date": session_date,
            "mature_slot_count": mature,
            "successful_slot_count": successful,
            "coverage_ratio": (successful / mature) if mature else None,
            "missing_workflow_slot_count": missing,
            "failed_collector_slot_count": failed,
            "duplicate_slot_count": duplicate,
            "unattributed_run_count": unattributed,
        })

    mature = totals["mature_slot_count"]
    run_total = totals["attributed_run_count"] + totals["unattributed_run_count"]
    aggregate = dict(totals)
    aggregate.update({
        "coverage_ratio": totals["successful_slot_count"] / mature if mature else None,
        "missing_workflow_rate": totals["missing_workflow_slot_count"] / mature if mature else None,
        "collector_failure_rate": totals["failed_collector_slot_count"] / mature if mature else None,
        "duplicate_slot_rate": totals["duplicate_slot_count"] / mature if mature else None,
        "unattributed_evidence_rate": totals["unattributed_run_count"] / run_total if run_total else None,
    })
    return {
        "contract": CONTRACT,
        "session_count": len(sessions),
        "sessions": sorted(sessions, key=lambda row: row["session_date"]),
        "aggregate": aggregate,
        "interpretation": "Acquisition reliability only; this report is not model performance or promotion evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize reconciled early-premarket acquisition reliability")
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    print(json.dumps(summarize(reports), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
