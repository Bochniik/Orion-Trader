from __future__ import annotations

import argparse
from datetime import datetime, timedelta, time, timezone
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
LAST_PREDICTION_CUTOFF = time(15, 30)
DEFAULT_CRON = "35 13-21 * * 1-5"
CONTRACT = "orion-regular-hours-schedule-delivery-v1"
ON_TIME_MINUTES = 20.0
SEVERE_DELAY_MINUTES = 60.0


def _parse_int_set(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            start, end = int(start_raw), int(end_raw)
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    if not values or min(values) < minimum or max(values) > maximum:
        raise ValueError(f"Unsupported cron field: {field}")
    return values


def _cron_fields(cron: str) -> tuple[set[int], set[int], set[int]]:
    parts = cron.split()
    if len(parts) != 5:
        raise ValueError(f"Expected five-field cron expression, got: {cron}")
    minute_field, hour_field, day_month, month, weekday_field = parts
    if day_month != "*" or month != "*":
        raise ValueError("Only daily month/day wildcards are supported")
    minutes = _parse_int_set(minute_field, 0, 59)
    hours = _parse_int_set(hour_field, 0, 23)
    weekdays = _parse_int_set(weekday_field, 0, 7)
    return minutes, hours, weekdays


def _github_weekday(moment: datetime) -> int:
    # Python Monday=0..Sunday=6; cron Sunday=0/7, Monday=1.
    return (moment.weekday() + 1) % 7


def expected_slot_utc(observed_at: datetime, cron: str = DEFAULT_CRON) -> datetime:
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    current = observed_at.astimezone(timezone.utc).replace(second=0, microsecond=0)
    minutes, hours, weekdays = _cron_fields(cron)
    for offset in range(0, 24 * 60 + 1):
        candidate = current - timedelta(minutes=offset)
        weekday = _github_weekday(candidate)
        weekday_allowed = weekday in weekdays or (weekday == 0 and 7 in weekdays)
        if candidate.minute in minutes and candidate.hour in hours and weekday_allowed:
            return candidate
    raise ValueError("No matching cron slot found within the previous 24 hours")


def _in_regular_window(moment: datetime) -> bool:
    local = moment.astimezone(NY)
    clock = local.time().replace(tzinfo=None)
    return local.weekday() < 5 and REGULAR_OPEN <= clock <= LAST_PREDICTION_CUTOFF


def build_audit(
    *,
    observed_at: datetime | None = None,
    event_name: str = "schedule",
    scheduled_cron: str | None = DEFAULT_CRON,
) -> dict[str, Any]:
    observed = observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    observed = observed.astimezone(timezone.utc)

    base: dict[str, Any] = {
        "contract": CONTRACT,
        "event_name": event_name,
        "observed_at_utc": observed.isoformat(),
        "observed_at_et": observed.astimezone(NY).isoformat(),
        "observed_in_regular_window": _in_regular_window(observed),
    }

    if event_name != "schedule" or not scheduled_cron:
        base.update(
            {
                "mode": "manual_dispatch",
                "scheduled_cron": scheduled_cron,
                "expected_slot_utc": None,
                "delivery_delay_minutes": None,
                "delivery_class": "not_applicable",
                "expected_slot_in_regular_window": None,
                "missed_regular_window": False,
            }
        )
        return base

    slot = expected_slot_utc(observed, scheduled_cron)
    delay_minutes = max(0.0, (observed - slot).total_seconds() / 60.0)
    if delay_minutes <= ON_TIME_MINUTES:
        delivery_class = "on_time"
    elif delay_minutes <= SEVERE_DELAY_MINUTES:
        delivery_class = "delayed"
    else:
        delivery_class = "severely_delayed"

    expected_in_window = _in_regular_window(slot)
    observed_in_window = _in_regular_window(observed)
    base.update(
        {
            "mode": "scheduled",
            "scheduled_cron": scheduled_cron,
            "expected_slot_utc": slot.isoformat(),
            "expected_slot_et": slot.astimezone(NY).isoformat(),
            "delivery_delay_minutes": round(delay_minutes, 3),
            "delivery_class": delivery_class,
            "on_time_threshold_minutes": ON_TIME_MINUTES,
            "severe_delay_threshold_minutes": SEVERE_DELAY_MINUTES,
            "expected_slot_in_regular_window": expected_in_window,
            "missed_regular_window": bool(expected_in_window and not observed_in_window),
        }
    )
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit GitHub schedule delivery for Orion regular-hours shadow runs.")
    parser.add_argument("--event-name", default="schedule")
    parser.add_argument("--scheduled-cron", default=DEFAULT_CRON)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cron = args.scheduled_cron.strip() or None
    report = build_audit(event_name=args.event_name, scheduled_cron=cron)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
