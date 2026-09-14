from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Iterable


REPORT_CONTRACT = "orion-long-horizon-v5-schedule-delivery-v1"
SCHEDULE_CRON = "5 14-19 * * 1-5"
SCHEDULE_MINUTE = 5
SCHEDULE_HOURS_UTC = tuple(range(14, 20))
# The scheduled paired-shadow producer first landed in #32. Do not fabricate
# missing slots before the frozen forward collection workflow existed.
PROTOCOL_NOT_BEFORE_UTC = datetime(2026, 9, 11, 5, 10, tzinfo=timezone.utc)
MATURE_AFTER_MINUTES = 20
MAX_DELIVERY_DELAY_MINUTES = 55


class ScheduleDeliveryError(ValueError):
    pass


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ScheduleDeliveryError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ScheduleDeliveryError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def expected_slots(*, start: datetime, as_of: datetime) -> list[datetime]:
    if start.tzinfo is None or as_of.tzinfo is None:
        raise ScheduleDeliveryError("start and as_of must be timezone-aware")
    start_utc = max(start.astimezone(timezone.utc), PROTOCOL_NOT_BEFORE_UTC)
    mature_cutoff = as_of.astimezone(timezone.utc) - timedelta(minutes=MATURE_AFTER_MINUTES)
    if mature_cutoff < start_utc:
        return []

    day = start_utc.date()
    end_day = mature_cutoff.date()
    slots: list[datetime] = []
    while day <= end_day:
        if day.weekday() < 5:
            for hour in SCHEDULE_HOURS_UTC:
                slot = datetime(day.year, day.month, day.day, hour, SCHEDULE_MINUTE, tzinfo=timezone.utc)
                if start_utc <= slot <= mature_cutoff:
                    slots.append(slot)
        day += timedelta(days=1)
    return slots


def _project_runs(runs: Iterable[dict[str, Any]], *, start: datetime, as_of: datetime) -> list[dict[str, Any]]:
    start_utc = max(start.astimezone(timezone.utc), PROTOCOL_NOT_BEFORE_UTC)
    cutoff = as_of.astimezone(timezone.utc)
    projected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for run in runs:
        if str(run.get("event") or "") != "schedule":
            raise ScheduleDeliveryError("workflow-run input must contain scheduled runs only")
        run_id = str(run.get("id") or "").strip()
        if not run_id.isdigit():
            raise ScheduleDeliveryError("scheduled workflow run id must be numeric")
        if run_id in seen_ids:
            raise ScheduleDeliveryError(f"duplicate scheduled workflow run id: {run_id}")
        seen_ids.add(run_id)
        created = _parse_timestamp(run.get("created_at"), field="workflow run created_at")
        if created < start_utc or created > cutoff:
            continue
        projected.append(
            {
                "run_id": run_id,
                "created_at": created,
                "status": str(run.get("status") or "unknown"),
                "conclusion": None if run.get("conclusion") is None else str(run.get("conclusion")),
            }
        )
    projected.sort(key=lambda row: (row["created_at"], int(row["run_id"])))
    return projected


def build_schedule_delivery_report(
    runs: Iterable[dict[str, Any]], *, start: datetime, as_of: datetime
) -> dict[str, Any]:
    if start.tzinfo is None or as_of.tzinfo is None:
        raise ScheduleDeliveryError("start and as_of must be timezone-aware")
    start_utc = max(start.astimezone(timezone.utc), PROTOCOL_NOT_BEFORE_UTC)
    as_of_utc = as_of.astimezone(timezone.utc)
    if as_of_utc < start_utc:
        slots: list[datetime] = []
    else:
        slots = expected_slots(start=start_utc, as_of=as_of_utc)
    observed = _project_runs(runs, start=start_utc, as_of=as_of_utc)

    unmatched = set(range(len(observed)))
    deliveries: list[dict[str, Any]] = []
    max_delay = timedelta(minutes=MAX_DELIVERY_DELAY_MINUTES)
    for slot in slots:
        candidates = [
            index
            for index in unmatched
            if slot <= observed[index]["created_at"] <= slot + max_delay
        ]
        matched_index = min(candidates, key=lambda index: observed[index]["created_at"]) if candidates else None
        if matched_index is None:
            deliveries.append(
                {
                    "expected_slot_utc": slot.isoformat(),
                    "utc_hour": slot.hour,
                    "delivered": False,
                    "run_id": None,
                    "created_at_utc": None,
                    "delivery_delay_minutes": None,
                    "status": None,
                    "conclusion": None,
                }
            )
            continue
        unmatched.remove(matched_index)
        row = observed[matched_index]
        delay = (row["created_at"] - slot).total_seconds() / 60.0
        deliveries.append(
            {
                "expected_slot_utc": slot.isoformat(),
                "utc_hour": slot.hour,
                "delivered": True,
                "run_id": row["run_id"],
                "created_at_utc": row["created_at"].isoformat(),
                "delivery_delay_minutes": round(delay, 3),
                "status": row["status"],
                "conclusion": row["conclusion"],
            }
        )

    unexpected = [
        {
            "run_id": observed[index]["run_id"],
            "created_at_utc": observed[index]["created_at"].isoformat(),
            "status": observed[index]["status"],
            "conclusion": observed[index]["conclusion"],
        }
        for index in sorted(unmatched)
    ]
    missing = [row for row in deliveries if not row["delivered"]]
    delivered = [row for row in deliveries if row["delivered"]]
    per_hour: dict[str, dict[str, Any]] = {}
    for hour in SCHEDULE_HOURS_UTC:
        rows = [row for row in deliveries if row["utc_hour"] == hour]
        delivered_count = sum(1 for row in rows if row["delivered"])
        per_hour[f"{hour:02d}:05Z"] = {
            "expected": len(rows),
            "delivered": delivered_count,
            "missing": len(rows) - delivered_count,
            "delivery_rate": None if not rows else round(delivered_count / len(rows), 6),
        }
    conclusion_counts = Counter(str(row["conclusion"] or "pending") for row in delivered)
    delivered_count = len(delivered)
    expected_count = len(deliveries)
    return {
        "contract": REPORT_CONTRACT,
        "score_blind": True,
        "metrics_exposed": False,
        "population": "mature_expected_github_schedule_slots",
        "schedule": {
            "cron": SCHEDULE_CRON,
            "protocol_not_before_utc": PROTOCOL_NOT_BEFORE_UTC.isoformat(),
            "mature_after_minutes": MATURE_AFTER_MINUTES,
            "max_delivery_delay_minutes": MAX_DELIVERY_DELAY_MINUTES,
        },
        "audit_window": {
            "start_utc": start_utc.isoformat(),
            "as_of_utc": as_of_utc.isoformat(),
        },
        "summary": {
            "expected_slot_count": expected_count,
            "delivered_slot_count": delivered_count,
            "missing_slot_count": len(missing),
            "unexpected_run_count": len(unexpected),
            "schedule_delivery_rate": None if expected_count == 0 else round(delivered_count / expected_count, 6),
            "all_mature_slots_delivered": not missing,
            "delivered_run_conclusion_counts": dict(sorted(conclusion_counts.items())),
        },
        "per_utc_slot": per_hour,
        "deliveries": deliveries,
        "missing_slots": missing,
        "unexpected_runs": unexpected,
    }


def _load_runs(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("workflow_runs")
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ScheduleDeliveryError("runs JSON must be an array or an object containing workflow_runs[]")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit score-blind delivery of frozen long-horizon V5 GitHub schedule slots."
    )
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--start", required=True, help="Timezone-aware ISO timestamp")
    parser.add_argument("--as-of", required=True, help="Timezone-aware ISO timestamp")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        start = _parse_timestamp(args.start, field="start")
        as_of = _parse_timestamp(args.as_of, field="as_of")
        report = build_schedule_delivery_report(_load_runs(args.runs), start=start, as_of=as_of)
    except (OSError, json.JSONDecodeError, ScheduleDeliveryError, ValueError) as exc:
        print(json.dumps({"status": "invalid_schedule_delivery_input", "error": str(exc)}, sort_keys=True))
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
