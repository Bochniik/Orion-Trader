from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_premarket_v5_schedule_delivery as delivery
import scripts.collect_premarket_v5_actions_evidence as actions
import scripts.resolve_premarket_v5_snapshot as resolver


def _target(day: date, snapshot: str) -> tuple[datetime, str]:
    reference = datetime.combine(day, datetime.min.time(), tzinfo=resolver.NY).astimezone(timezone.utc)
    target_utc, _ = resolver._target_for_local_day(snapshot, reference=reference)
    cron = f"{target_utc.minute} {target_utc.hour} * * 1-5"
    return target_utc, cron


def _recovery_cron(primary_cron: str, snapshot: str) -> str:
    minute, hour = [int(value) for value in primary_cron.split()[:2]]
    dt = datetime(2026, 1, 1, hour, minute, tzinfo=timezone.utc) + timedelta(minutes=10)
    candidate = f"{dt.minute} {dt.hour} * * 1-5"
    assert resolver.RECOVERY_CRON_SLOTS[candidate] == snapshot
    return candidate


def test_collector_accepts_central_scheduler_primary_and_recovery_only():
    primary = {
        "event": "schedule",
        "display_title": "Market acquisition schedule 45 10 * * 1-5",
    }
    recovery = {
        "event": "schedule",
        "display_title": "Market acquisition schedule 55 10 * * 1-5",
    }
    regular = {
        "event": "schedule",
        "display_title": "Market acquisition schedule 35,45,55 13-20 * * 1-5",
    }
    assert actions._registered_premarket_cron(primary) == "45 10 * * 1-5"
    assert actions._registered_premarket_cron(recovery) == "55 10 * * 1-5"
    assert actions._registered_premarket_cron(regular) is None


def test_central_scheduler_primary_satisfies_logical_snapshot():
    day = date(2026, 10, 6)
    target, cron = _target(day, "early")
    as_of = target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)
    run = {
        "id": 100,
        "event": "schedule",
        "display_title": f"{delivery.SCHEDULER_RUN_NAME_PREFIX}{cron}",
        "created_at": target.isoformat(),
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }

    report = delivery.build_schedule_delivery_report([run], start_date=day, as_of=as_of)
    row = report["deliveries"][0]
    assert report["summary"]["delivered_count"] == 1
    assert report["summary"]["successful_count"] == 1
    assert row["primary_successful"] is True
    assert row["recovered"] is False


def test_successful_recovery_satisfies_missing_primary_without_backdating():
    day = date(2026, 10, 6)
    target, primary_cron = _target(day, "early")
    recovery_cron = _recovery_cron(primary_cron, "early")
    recovery_created = target + resolver.RECOVERY_DELAY
    as_of = target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)
    run = {
        "id": 101,
        "event": "schedule",
        "display_title": f"{delivery.SCHEDULER_RUN_NAME_PREFIX}{recovery_cron}",
        "created_at": recovery_created.isoformat(),
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }

    report = delivery.build_schedule_delivery_report([run], start_date=day, as_of=as_of)
    row = report["deliveries"][0]
    assert row["schedule_cron"] == primary_cron
    assert row["observed_crons"] == [recovery_cron]
    assert row["primary_successful"] is False
    assert row["recovered"] is True
    assert report["summary"]["recovered_delivery_count"] == 1
    assert report["summary"]["missing_count"] == 0


def test_wrong_dst_transport_remains_inactive_and_does_not_fake_delivery():
    day = date(2026, 10, 6)
    target, _ = _target(day, "early")
    inactive_cron = "45 11 * * 1-5"
    run = {
        "id": 102,
        "event": "schedule",
        "display_title": f"{delivery.SCHEDULER_RUN_NAME_PREFIX}{inactive_cron}",
        "created_at": target.replace(hour=11, minute=45).isoformat(),
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }
    as_of = target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)

    report = delivery.build_schedule_delivery_report([run], start_date=day, as_of=as_of)
    assert report["summary"]["delivered_count"] == 0
    assert report["summary"]["missing_count"] == 1
