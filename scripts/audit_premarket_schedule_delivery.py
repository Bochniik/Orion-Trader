from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from nyse_session_calendar import is_nyse_trading_day

NY = ZoneInfo("America/New_York")
OBSERVATION_SLOTS = ((4, 5), (4, 35), (5, 5), (5, 35), (6, 5), (6, 35))
MAX_DELIVERY_LAG_MINUTES = 20.0


@dataclass(frozen=True)
class SlotDelivery:
    slot: str
    target_utc: str
    status: str
    run_id: int | None
    conclusion: str | None
    delivery_lag_minutes: float | None
    duplicate_run_ids: tuple[int, ...]


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("workflow run timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def expected_targets(session_date: date) -> list[tuple[str, datetime]]:
    if not is_nyse_trading_day(session_date):
        return []
    targets: list[tuple[str, datetime]] = []
    for hour, minute in OBSERVATION_SLOTS:
        local = datetime.combine(session_date, time(hour, minute), tzinfo=NY)
        targets.append((local.strftime("%H%M"), local.astimezone(timezone.utc)))
    return targets


def audit_schedule_delivery(session_date: date, workflow_runs: list[dict[str, Any]]) -> dict[str, Any]:
    slots: list[SlotDelivery] = []
    used_run_ids: set[int] = set()

    parsed_runs: list[tuple[datetime, dict[str, Any]]] = []
    for run in workflow_runs:
        if str(run.get("event") or "") != "schedule":
            continue
        created_at = run.get("created_at")
        run_id = run.get("id")
        if not created_at or run_id is None:
            continue
        parsed_runs.append((_parse_utc(str(created_at)), run))

    for slot, target in expected_targets(session_date):
        window_end = target + timedelta(minutes=MAX_DELIVERY_LAG_MINUTES)
        candidates = [
            (created, run)
            for created, run in parsed_runs
            if target <= created <= window_end and int(run["id"]) not in used_run_ids
        ]
        candidates.sort(key=lambda item: (item[0], int(item[1]["id"])))
        if not candidates:
            slots.append(SlotDelivery(slot, target.isoformat().replace("+00:00", "Z"), "run_missing", None, None, None, ()))
            continue

        created, primary = candidates[0]
        primary_id = int(primary["id"])
        used_run_ids.add(primary_id)
        duplicate_ids = tuple(int(run["id"]) for _, run in candidates[1:])
        used_run_ids.update(duplicate_ids)
        conclusion = str(primary.get("conclusion") or "") or None
        status = "run_created_success" if conclusion == "success" else "run_created_collector_failed"
        lag = round((created - target).total_seconds() / 60.0, 6)
        slots.append(SlotDelivery(slot, target.isoformat().replace("+00:00", "Z"), status, primary_id, conclusion, lag, duplicate_ids))

    counts = {key: sum(item.status == key for item in slots) for key in ("run_created_success", "run_created_collector_failed", "run_missing")}
    healthy = bool(slots) and counts["run_created_success"] == len(slots)
    if not slots:
        healthy = True
    return {
        "contract": "orion-premarket-schedule-delivery-v1",
        "score_blind": True,
        "session_date": session_date.isoformat(),
        "trading_day": bool(slots),
        "expected_slots": len(slots),
        "counts": counts,
        "healthy": healthy,
        "promotion_authorized": False,
        "slots": [asdict(item) for item in slots],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit scheduled early-premarket workflow delivery without reading model scores.")
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--session-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    payload = json.loads(args.runs_json.read_text(encoding="utf-8"))
    runs = payload.get("workflow_runs", payload) if isinstance(payload, dict) else payload
    if not isinstance(runs, list):
        raise SystemExit("runs JSON must be a list or contain workflow_runs")
    report = audit_schedule_delivery(args.session_date, runs)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["healthy"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
