from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from scripts.audit_regular_hours_collection_health import (
    CollectionHealthError,
    _load_payload,
    build_health_report,
)

REPORT_CONTRACT = "orion-regular-hours-collection-health-v2"


def _session_is_complete(row: dict[str, Any]) -> bool:
    requested = int(row.get("requested_symbol_count") or 0)
    available = int(row.get("available_symbol_count") or 0)
    provenance_valid = int(row.get("provenance_valid_symbol_count") or 0)
    failures = int(row.get("failure_count") or 0)
    provenance_gaps = int(row.get("provenance_gap_symbol_count") or 0)
    return (
        requested > 0
        and available == requested
        and provenance_valid == requested
        and failures == 0
        and provenance_gaps == 0
    )


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

    report["contract"] = REPORT_CONTRACT
    report["complete_standard_session_count"] = len(complete_sessions)
    report["incomplete_standard_session_count"] = len(incomplete_sessions)
    report["complete_standard_sessions"] = complete_sessions
    report["incomplete_standard_sessions"] = incomplete_sessions
    report["score_inspection_readiness_threshold_defined"] = False
    return report


def build_completeness_report(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return add_session_completeness(build_health_report(payloads))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit complete regular-hours V3.1 standard sessions without inspecting "
            "predictive scores or inventing a score-inspection threshold."
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
