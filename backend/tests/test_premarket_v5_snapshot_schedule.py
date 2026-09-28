from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "resolve_premarket_v5_snapshot.py"
spec = importlib.util.spec_from_file_location("premarket_v5_snapshot_schedule", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_registered_cadence_is_fixed_to_three_regimes():
    assert module.SNAPSHOT_CLOCKS == {
        "early": module.time(6, 45),
        "mid": module.time(8, 0),
        "late": module.time(9, 15),
    }
    assert module.RECOVERY_DELAY.total_seconds() == 600


def test_summer_edt_activates_primary_and_matching_recovery_slots():
    now = datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)

    early = module.resolve_snapshot(schedule_cron="45 10 * * 1-5", now=now)
    early_recovery = module.resolve_snapshot(schedule_cron="55 10 * * 1-5", now=now)
    mid = module.resolve_snapshot(schedule_cron="0 12 * * 1-5", now=now)
    mid_recovery = module.resolve_snapshot(schedule_cron="10 12 * * 1-5", now=now)
    late = module.resolve_snapshot(schedule_cron="15 13 * * 1-5", now=now)
    late_recovery = module.resolve_snapshot(schedule_cron="25 13 * * 1-5", now=now)
    inactive_early = module.resolve_snapshot(schedule_cron="45 11 * * 1-5", now=now)
    inactive_early_recovery = module.resolve_snapshot(schedule_cron="55 11 * * 1-5", now=now)

    assert early.active is True and early.mode == "primary"
    assert early_recovery.active is True and early_recovery.mode == "recovery"
    assert early_recovery.as_of_utc == early.as_of_utc
    assert mid.active is True and mid_recovery.active is True
    assert mid_recovery.as_of_utc == mid.as_of_utc
    assert late.active is True and late_recovery.active is True
    assert late_recovery.as_of_utc == late.as_of_utc
    assert inactive_early.active is False
    assert inactive_early.reason == "inactive_dst_slot"
    assert inactive_early_recovery.active is False
    assert inactive_early_recovery.reason == "inactive_dst_slot"


def test_winter_est_activates_primary_and_matching_recovery_slots():
    now = datetime(2026, 1, 12, 13, 30, tzinfo=timezone.utc)

    early = module.resolve_snapshot(schedule_cron="45 11 * * 1-5", now=now)
    early_recovery = module.resolve_snapshot(schedule_cron="55 11 * * 1-5", now=now)
    mid = module.resolve_snapshot(schedule_cron="0 13 * * 1-5", now=now)
    mid_recovery = module.resolve_snapshot(schedule_cron="10 13 * * 1-5", now=now)
    late = module.resolve_snapshot(schedule_cron="15 14 * * 1-5", now=now)
    late_recovery = module.resolve_snapshot(schedule_cron="25 14 * * 1-5", now=now)
    inactive_mid = module.resolve_snapshot(schedule_cron="0 12 * * 1-5", now=now)
    inactive_mid_recovery = module.resolve_snapshot(schedule_cron="10 12 * * 1-5", now=now)

    assert early.active is True and early_recovery.active is True
    assert early_recovery.as_of_utc == early.as_of_utc
    assert mid.active is True and mid_recovery.active is True
    assert mid_recovery.as_of_utc == mid.as_of_utc
    assert late.active is True and late_recovery.active is True
    assert late_recovery.as_of_utc == late.as_of_utc
    assert inactive_mid.active is False
    assert inactive_mid_recovery.active is False


def test_market_holiday_is_not_counted_as_registered_forward_session():
    now = datetime(2026, 9, 7, 12, 30, tzinfo=timezone.utc)
    result = module.resolve_snapshot(schedule_cron="10 12 * * 1-5", now=now)

    assert result.active is False
    assert result.reason == "market_holiday"
    assert result.snapshot == "mid"
    assert result.mode == "recovery"


def test_good_friday_is_rejected_even_though_it_is_a_weekday():
    now = datetime(2026, 4, 3, 12, 30, tzinfo=timezone.utc)
    result = module.resolve_snapshot(schedule_cron="0 12 * * 1-5", now=now)

    assert result.active is False
    assert result.reason == "market_holiday"


def test_manual_dispatch_preserves_late_snapshot_default():
    result = module.resolve_snapshot(
        schedule_cron=None,
        now=datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc),
    )
    assert result.active is True
    assert result.snapshot == "late"
    assert result.mode == "manual"
    assert result.as_of_et.hour == 9 and result.as_of_et.minute == 15


def test_unknown_schedule_fails_closed():
    try:
        module.resolve_snapshot(
            schedule_cron="30 12 * * 1-5",
            now=datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc),
        )
    except ValueError as exc:
        assert "unregistered" in str(exc).lower()
    else:
        raise AssertionError("unknown schedules must fail closed")


def test_manual_current_captures_actual_minute_without_future_snapshot():
    now = datetime(2026, 9, 28, 11, 12, 35, tzinfo=timezone.utc)
    result = module.resolve_snapshot(schedule_cron=None, now=now, manual_current=True)
    assert result.active is True
    assert result.snapshot == "current"
    assert result.mode == "manual_current"
    assert result.reason == "manual_current_research_only"
    assert result.as_of_utc == datetime(2026, 9, 28, 11, 12, tzinfo=timezone.utc)
    assert (result.as_of_et.hour, result.as_of_et.minute) == (7, 12)


def test_manual_current_rejects_scheduled_provenance():
    try:
        module.resolve_snapshot(
            schedule_cron="45 10 * * 1-5",
            now=datetime(2026, 9, 28, 11, 12, tzinfo=timezone.utc),
            manual_current=True,
        )
    except ValueError as exc:
        assert "incompatible" in str(exc)
    else:
        raise AssertionError("manual current must not impersonate scheduled evidence")
