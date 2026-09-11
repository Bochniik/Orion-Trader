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


def test_summer_edt_activates_only_matching_utc_slots():
    now = datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)

    early = module.resolve_snapshot(schedule_cron="45 10 * * 1-5", now=now)
    mid = module.resolve_snapshot(schedule_cron="0 12 * * 1-5", now=now)
    late = module.resolve_snapshot(schedule_cron="15 13 * * 1-5", now=now)
    duplicate_early = module.resolve_snapshot(schedule_cron="45 11 * * 1-5", now=now)

    assert early.active is True and early.as_of_et.hour == 6 and early.as_of_et.minute == 45
    assert mid.active is True and mid.as_of_et.hour == 8 and mid.as_of_et.minute == 0
    assert late.active is True and late.as_of_et.hour == 9 and late.as_of_et.minute == 15
    assert duplicate_early.active is False
    assert duplicate_early.reason == "inactive_dst_slot"


def test_winter_est_activates_only_matching_utc_slots():
    now = datetime(2026, 1, 12, 13, 30, tzinfo=timezone.utc)

    early = module.resolve_snapshot(schedule_cron="45 11 * * 1-5", now=now)
    mid = module.resolve_snapshot(schedule_cron="0 13 * * 1-5", now=now)
    late = module.resolve_snapshot(schedule_cron="15 14 * * 1-5", now=now)
    duplicate_mid = module.resolve_snapshot(schedule_cron="0 12 * * 1-5", now=now)

    assert early.active is True and early.as_of_et.hour == 6 and early.as_of_et.minute == 45
    assert mid.active is True and mid.as_of_et.hour == 8 and mid.as_of_et.minute == 0
    assert late.active is True and late.as_of_et.hour == 9 and late.as_of_et.minute == 15
    assert duplicate_mid.active is False
    assert duplicate_mid.reason == "inactive_dst_slot"


def test_manual_dispatch_preserves_late_snapshot_default():
    result = module.resolve_snapshot(
        schedule_cron=None,
        now=datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc),
    )
    assert result.active is True
    assert result.snapshot == "late"
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
