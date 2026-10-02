from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")
SLOT_TIMES_ET = tuple(time(hour, 35) for hour in range(9, 16))
DEFAULT_MATCH_WINDOW_MINUTES = 20.0
CONTRACT = "orion-regular-hours-daily-schedule-reconciliation-v1"


def expected_slots_utc(session_date: date) -> list[datetime]:
    if session_date.weekday() >= 5:
        return []
    return [datetime.combine(session_date, clock, tzinfo=NY).astimezone(timezone.utc) for clock in SLOT_TIMES_ET]


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _scheduled_runs(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for run in runs:
        if run.get("event") != "schedule":
            continue
        created_raw = run.get("created_at") or run.get("run_started_at")
        if not created_raw:
            continue
        normalized.append({**run, "_observed_at": _parse_timestamp(str(created_raw))})
    return sorted(normalized, key=lambda item: item["_observed_at"])


def reconcile_day(
    *,
    session_date: date,
    runs: Iterable[dict[str, Any]],
    match_window_minutes: float = DEFAULT_MATCH_WINDOW_MINUTES,
) -> dict[str, Any]:
    slots = expected_slots_utc(session_date)
    scheduled = _scheduled_runs(runs)
    effective_match_window_minutes = min(float(match_window_minutes), DEFAULT_MATCH_WINDOW_MINUTES)
    window = timedelta(minutes=effective_match_window_minutes)

    candidates: dict[int, list[int]] = {}
    for slot_index, slot in enumerate(slots):
        candidates[slot_index] = [
            run_index
            for run_index, run in enumerate(scheduled)
            if slot <= run["_observed_at"] <= slot + window
        ]

    matched_run_indexes: set[int] = set()
    slot_reports: list[dict[str, Any]] = []
    for slot_index, slot in enumerate(slots):
        run_indexes = candidates[slot_index]
        ordered = sorted(run_indexes, key=lambda index: scheduled[index]["_observed_at"])
        successful = [index for index in ordered if str(scheduled[index].get("conclusion") or "") == "success"]

        if successful:
            run_index = successful[0]
            run = scheduled[run_index]
            matched_run_indexes.update(ordered)
            status = "matched"
            run_id = run.get("id")
            delay = (run["_observed_at"] - slot).total_seconds() / 60.0
            reason = "at least one scheduled delivery in the retry window completed successfully"
        elif ordered:
            matched_run_indexes.update(ordered)
            status = "failed"
            run_id = None
            delay = None
            reason = "scheduled delivery attempts existed in the retry window but none completed successfully"
        else:
            status = "missing"
            run_id = None
            delay = None
            reason = "no scheduled run falls within this slot's retry window"

        slot_reports.append(
            {
                "slot_utc": slot.isoformat(),
                "slot_et": slot.astimezone(NY).isoformat(),
                "status": status,
                "matched_run_id": run_id,
                "delivery_delay_minutes": None if delay is None else round(delay, 3),
                "candidate_run_ids": [scheduled[index].get("id") for index in ordered],
                "successful_candidate_run_ids": [scheduled[index].get("id") for index in successful],
                "reason": reason,
            }
        )

    unmatched_runs = [
        {
            "run_id": run.get("id"),
            "observed_at_utc": run["_observed_at"].isoformat(),
            "conclusion": run.get("conclusion"),
        }
        for index, run in enumerate(scheduled)
        if index not in matched_run_indexes
    ]
    counts = {status: sum(item["status"] == status for item in slot_reports) for status in ("matched", "missing", "failed")}
    return {
        "contract": CONTRACT,
        "session_date_et": session_date.isoformat(),
        "match_window_minutes": effective_match_window_minutes,
        "requested_match_window_minutes": match_window_minutes,
        "slot_count": len(slots),
        "counts": counts,
        "slots": slot_reports,
        "unmatched_scheduled_runs": unmatched_runs,
        "healthy": counts["missing"] == 0 and counts["failed"] == 0,
        "warning": "Matching uses run creation time as delivery evidence. Retry windows are intentionally capped below the one-hour slot spacing, and a slot is healthy when any attempt in its window succeeds.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile one ET trading day's expected regular-hours slots against GitHub scheduled runs.")
    parser.add_argument("--session-date", required=True, help="ET session date, YYYY-MM-DD")
    parser.add_argument("--runs-json", type=Path, required=True, help="GitHub Actions workflow-runs JSON (object with workflow_runs or a list)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--match-window-minutes", type=float, default=DEFAULT_MATCH_WINDOW_MINUTES)
    args = parser.parse_args()

    payload = json.loads(args.runs_json.read_text(encoding="utf-8"))
    runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else payload
    report = reconcile_day(session_date=date.fromisoformat(args.session_date), runs=runs, match_window_minutes=args.match_window_minutes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["healthy"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
