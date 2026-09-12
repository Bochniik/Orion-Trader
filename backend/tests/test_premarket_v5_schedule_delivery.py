from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_premarket_v5_schedule_delivery as delivery
import scripts.resolve_premarket_v5_snapshot as resolver


def _active_target(day: date, snapshot: str) -> tuple[datetime, str]:
    reference = datetime.combine(day, datetime.min.time(), tzinfo=resolver.NY).astimezone(timezone.utc)
    target_utc, _ = resolver._target_for_local_day(snapshot, reference=reference)
    cron = f"{target_utc.minute} {target_utc.hour} * * 1-5"
    assert resolver.REGISTERED_CRON_SLOTS[cron] == snapshot
    return target_utc, cron


def _run(day: date, snapshot: str, *, conclusion: str = "success", active: bool = True, run_id: int = 1) -> dict:
    target, cron = _active_target(day, snapshot)
    if not active:
        alternatives = [slot for slot, name in resolver.REGISTERED_CRON_SLOTS.items() if name == snapshot and slot != cron]
        assert len(alternatives) == 1
        cron = alternatives[0]
        minute, hour = [int(value) for value in cron.split()[:2]]
        target = target.replace(hour=hour, minute=minute)
    return {
        "id": run_id,
        "event": "schedule",
        "display_title": f"{delivery.RUN_NAME_PREFIX}{cron}",
        "created_at": target.isoformat(),
        "status": "completed",
        "conclusion": conclusion,
        "run_attempt": 1,
    }


def test_complete_trading_day_is_fully_delivered():
    day = date(2026, 9, 11)
    late_target, _ = _active_target(day, "late")
    as_of = late_target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)
    runs = [_run(day, snapshot, run_id=index) for index, snapshot in enumerate(resolver.SNAPSHOT_CLOCKS, start=1)]

    report = delivery.build_schedule_delivery_report(runs, start_date=day, as_of=as_of)

    assert report["score_blind"] is True
    assert report["metrics_exposed"] is False
    assert report["summary"]["expected_delivery_count"] == 3
    assert report["summary"]["missing_count"] == 0
    assert report["summary"]["unsuccessful_count"] == 0
    assert report["summary"]["all_mature_slots_delivered"] is True
    assert report["summary"]["all_mature_slots_successful"] is True


def test_missing_run_is_distinguished_from_young_not_yet_mature_slot():
    day = date(2026, 9, 11)
    mid_target, _ = _active_target(day, "mid")
    as_of = mid_target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)
    runs = [_run(day, "early")]

    report = delivery.build_schedule_delivery_report(runs, start_date=day, as_of=as_of)

    assert report["summary"]["expected_delivery_count"] == 2
    assert report["summary"]["missing_count"] == 1
    assert report["missing_deliveries"][0]["snapshot"] == "mid"
    assert report["per_snapshot"]["late"]["expected"] == 0


def test_inactive_dst_duplicate_does_not_satisfy_active_delivery():
    day = date(2026, 9, 11)
    early_target, _ = _active_target(day, "early")
    as_of = early_target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)

    report = delivery.build_schedule_delivery_report(
        [_run(day, "early", active=False)], start_date=day, as_of=as_of
    )

    assert report["summary"]["expected_delivery_count"] == 1
    assert report["summary"]["missing_count"] == 1
    assert report["summary"]["delivered_count"] == 0


def test_failed_run_counts_as_delivered_but_unsuccessful():
    day = date(2026, 9, 11)
    early_target, _ = _active_target(day, "early")
    as_of = early_target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)

    report = delivery.build_schedule_delivery_report(
        [_run(day, "early", conclusion="failure")], start_date=day, as_of=as_of
    )

    assert report["summary"]["delivered_count"] == 1
    assert report["summary"]["successful_count"] == 0
    assert report["summary"]["missing_count"] == 0
    assert report["summary"]["unsuccessful_count"] == 1
    assert report["unsuccessful_deliveries"][0]["conclusions"] == ["failure"]


def test_manual_run_is_ignored_for_schedule_delivery():
    day = date(2026, 9, 11)
    early_target, cron = _active_target(day, "early")
    as_of = early_target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)
    manual = _run(day, "early")
    manual.update({"event": "workflow_dispatch", "display_title": f"{delivery.RUN_NAME_PREFIX}{cron}"})

    report = delivery.build_schedule_delivery_report([manual], start_date=day, as_of=as_of)

    assert report["summary"]["missing_count"] == 1
    assert report["summary"]["delivered_count"] == 0


def test_duplicate_active_runs_are_reported_without_hiding_success():
    day = date(2026, 9, 11)
    early_target, _ = _active_target(day, "early")
    as_of = early_target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)

    report = delivery.build_schedule_delivery_report(
        [_run(day, "early", conclusion="failure", run_id=10), _run(day, "early", conclusion="success", run_id=11)],
        start_date=day,
        as_of=as_of,
    )

    assert report["summary"]["duplicate_delivery_count"] == 1
    assert report["summary"]["delivered_count"] == 1
    assert report["summary"]["successful_count"] == 1
    assert report["duplicate_deliveries"][0]["run_count"] == 2
