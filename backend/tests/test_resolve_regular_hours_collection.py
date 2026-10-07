from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "resolve_regular_hours_collection.py"
spec = importlib.util.spec_from_file_location("resolve_regular_hours_collection", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_primary_and_retry_attempts_map_to_same_slot_during_edt():
    primary = module.resolve_regular_collection_target(_utc("2026-09-21T13:35:00Z"))
    retry_1 = module.resolve_regular_collection_target(_utc("2026-09-21T13:45:00Z"))
    retry_2 = module.resolve_regular_collection_target(_utc("2026-09-21T13:55:00Z"))
    assert primary.active and retry_1.active and retry_2.active
    assert primary.slot == retry_1.slot == retry_2.slot == "0935"
    assert retry_2.lag_minutes == 20.0


def test_scheduler_transport_grace_accepts_recent_observed_delay():
    # Mirrors the 2026-10-06 production failure where GitHub delivered the
    # 14:35 ET acquisition opportunity about 24.9 minutes late. Evidence is
    # still timestamped at the actual collection time, never backdated.
    target = module.resolve_regular_collection_target(_utc("2026-10-06T18:59:54Z"))
    assert target.active is True
    assert target.reason == "scheduled_regular_collection_window"
    assert target.slot == "1435"
    assert target.lag_minutes == 24.9


def test_attempt_after_bounded_transport_grace_is_inactive():
    target = module.resolve_regular_collection_target(_utc("2026-09-21T14:05:01Z"))
    assert target.active is False
    assert target.reason == "outside_schedule_lag_window"
    assert target.slot == "0935"


def test_est_slot_resolves_with_new_york_timezone():
    target = module.resolve_regular_collection_target(_utc("2026-12-07T14:45:00Z"))
    assert target.active is True
    assert target.slot == "0935"
    assert target.lag_minutes == 10.0


def test_weekend_is_inactive():
    target = module.resolve_regular_collection_target(_utc("2026-09-19T13:35:00Z"))
    assert target.active is False
    assert target.reason == "weekend"
