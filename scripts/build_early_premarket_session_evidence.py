#!/usr/bin/env python3
"""Build provenance-safe per-session early-premarket evidence from GitHub exports.

This utility deliberately does not infer target slots from workflow timestamps. Identity
artifacts produced by the observational workflow are the only accepted slot attribution.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reconcile_early_premarket_run_history import _parse_utc, parse_identity_artifact, reconcile

CONTRACT = "orion-early-premarket-session-evidence-v1"


def build_session_evidence(*, session_date: date, raw_runs: Any, identity_files: list[Path],
                           observed_at_utc: datetime) -> dict[str, Any]:
    runs = raw_runs.get("workflow_runs", []) if isinstance(raw_runs, dict) else raw_runs
    if not isinstance(runs, list):
        raise ValueError("runs export must be a list or contain workflow_runs")

    identities = [parse_identity_artifact(path.read_text(encoding="utf-8")) for path in identity_files]
    report = reconcile(
        session_date=session_date,
        raw_runs=runs,
        raw_identities=identities,
        observed_at_utc=observed_at_utc,
    )
    return {
        "contract": CONTRACT,
        "session_date": session_date.isoformat(),
        "identity_artifact_count": len(identities),
        "reconciliation": report,
        "provenance": {
            "slot_identity_source": "explicit_workflow_identity_artifact_only",
            "timestamp_slot_inference_allowed": False,
            "model_performance_evidence": False,
            "promotion_evidence": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one provenance-safe early-premarket session evidence artifact")
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--identity-file", type=Path, action="append", default=[])
    parser.add_argument("--session-date", type=date.fromisoformat, required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw_runs = json.loads(args.runs_json.read_text(encoding="utf-8"))
    evidence = build_session_evidence(
        session_date=args.session_date,
        raw_runs=raw_runs,
        identity_files=args.identity_file,
        observed_at_utc=_parse_utc(args.observed_at_utc),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "written", "output": str(args.output), "session_date": args.session_date.isoformat()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
