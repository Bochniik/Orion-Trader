from __future__ import annotations

from datetime import datetime, timezone

from scripts.resolve_early_premarket_observation import resolve_observation_target


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_resolves_edT_slots_without_dst_duplication():
    target = resolve_observation_target(_utc("2026-09-14T08:05:00Z"))
    assert target.active is True
    assert target.slot == "0405"
    assert target.target_et.startswith("2026-09-14T04:05:00-04:00")
    assert target.lag_minutes == 0.0

    target = resolve_observation_target(_utc("2026-09-14T10:35:00Z"))
    assert target.active is True
    assert target.slot == "0635"
    assert target.target_et.startswith("2026-09-14T06:35:00-04:00")


def test_resolves_est_slots():
    target = resolve_observation_target(_utc("2026-12-14T09:05:00Z"))
    assert target.active is True
    assert target.slot == "0405"
    assert target.target_et.startswith("2026-12-14T04:05:00-05:00")

    target = resolve_observation_target(_utc("2026-12-14T11:35:00Z"))
    assert target.active is True
    assert target.slot == "0635"


def test_inactive_duplicate_dst_slots_fail_closed():
    early_est_duplicate = resolve_observation_target(_utc("2026-12-14T08:05:00Z"))
    assert early_est_duplicate.active is False
    assert early_est_duplicate.reason == "before_observation_window"

    late_edt_duplicate = resolve_observation_target(_utc("2026-09-14T11:05:00Z"))
    assert late_edt_duplicate.active is False
    assert late_edt_duplicate.reason == "outside_schedule_lag_window"


def test_schedule_delay_within_twenty_minutes_is_preserved():
    target = resolve_observation_target(_utc("2026-09-14T08:19:30Z"))
    assert target.active is True
    assert target.slot == "0405"
    assert target.lag_minutes == 14.5


def test_stale_delivery_is_rejected():
    target = resolve_observation_target(_utc("2026-09-14T08:26:00Z"))
    assert target.active is False
    assert target.reason == "outside_schedule_lag_window"
    assert target.slot == "0405"


def test_weekend_is_rejected():
    target = resolve_observation_target(_utc("2026-09-13T08:05:00Z"))
    assert target.active is False
    assert target.reason == "weekend"
