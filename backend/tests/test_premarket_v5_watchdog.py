from datetime import datetime, timezone
from pathlib import Path

from scripts.resolve_premarket_v5_watchdog import resolve_watchdog_snapshot


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[2]


def test_watchdog_activates_early_snapshot_on_ed_timing():
    resolution = resolve_watchdog_snapshot(now=datetime(2026, 10, 8, 10, 45, tzinfo=UTC))

    assert resolution.active is True
    assert resolution.snapshot == "early"
    assert resolution.as_of_et.hour == 6
    assert resolution.as_of_et.minute == 45
    assert resolution.lag_minutes == 0.0


def test_watchdog_keeps_short_recovery_window_but_fails_closed_after_it():
    inside = resolve_watchdog_snapshot(now=datetime(2026, 10, 8, 10, 56, tzinfo=UTC))
    outside = resolve_watchdog_snapshot(now=datetime(2026, 10, 8, 10, 58, tzinfo=UTC))

    assert inside.active is True
    assert inside.snapshot == "early"
    assert inside.lag_minutes == 11.0
    assert outside.active is False
    assert outside.reason == "outside_snapshot_window"


def test_watchdog_resolves_mid_and_late_without_changing_frozen_targets():
    mid = resolve_watchdog_snapshot(now=datetime(2026, 10, 8, 12, 5, tzinfo=UTC))
    late = resolve_watchdog_snapshot(now=datetime(2026, 10, 8, 13, 20, tzinfo=UTC))

    assert mid.active is True
    assert mid.snapshot == "mid"
    assert mid.as_of_et.hour == 8
    assert mid.as_of_et.minute == 0
    assert mid.lag_minutes == 5.0

    assert late.active is True
    assert late.snapshot == "late"
    assert late.as_of_et.hour == 9
    assert late.as_of_et.minute == 15
    assert late.lag_minutes == 5.0


def test_watchdog_is_dst_safe_for_est_session():
    resolution = resolve_watchdog_snapshot(now=datetime(2026, 11, 5, 11, 45, tzinfo=UTC))

    assert resolution.active is True
    assert resolution.snapshot == "early"
    assert resolution.as_of_et.utcoffset().total_seconds() == -5 * 3600
    assert resolution.lag_minutes == 0.0


def test_watchdog_fails_closed_on_weekend():
    resolution = resolve_watchdog_snapshot(now=datetime(2026, 10, 10, 10, 45, tzinfo=UTC))

    assert resolution.active is False
    assert resolution.reason == "weekend"


def test_watchdog_workflow_uses_reusable_premarket_worker_and_snapshot_override():
    watchdog = (ROOT / ".github/workflows/premarket-v5-delivery-watchdog.yml").read_text(encoding="utf-8")
    worker = (ROOT / ".github/workflows/premarket-v5-cloud-shadow.yml").read_text(encoding="utf-8")

    assert 'cron: "*/5 10-14 * * 1-5"' in watchdog
    assert "uses: ./.github/workflows/premarket-v5-cloud-shadow.yml" in watchdog
    assert "external_snapshot: ${{ needs.resolve.outputs.snapshot }}" in watchdog
    assert 'SCHEDULE_ARG=""' in worker
