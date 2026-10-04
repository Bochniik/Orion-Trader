from datetime import datetime, timezone

import pytest

from app.services.execution_realism import ExecutionPolicy, simulate_bar_execution


def ts(hour, minute=0, second=0):
    return datetime(2026, 10, 2, hour, minute, second, tzinfo=timezone.utc)


def test_latency_fails_closed_before_order_is_eligible():
    out = simulate_bar_execution(
        signal_at=ts(14), bar_at=ts(14), requested_quantity=10,
        bar_volume=1000, reference_price=100, side="BUY",
        policy=ExecutionPolicy(latency_ms=250),
    )
    assert out.status == "NO_TRADE"
    assert out.reason == "latency_not_elapsed"


def test_volume_participation_causes_partial_fill_and_dynamic_slippage():
    out = simulate_bar_execution(
        signal_at=ts(14), bar_at=ts(14, 0, 1), requested_quantity=50,
        bar_volume=100, reference_price=100, side="BUY",
        policy=ExecutionPolicy(latency_ms=0, max_volume_participation=0.10,
                               base_slippage_bps=1, impact_bps_at_full_participation=9),
    )
    assert out.status == "PARTIAL_FILL"
    assert out.filled_quantity == 10
    assert out.unfilled_quantity == 40
    assert out.slippage_bps == pytest.approx(10)
    assert out.fill_price == pytest.approx(100.1)


def test_regular_session_constraint_is_fail_closed():
    out = simulate_bar_execution(
        signal_at=ts(11), bar_at=ts(11, 0, 1), requested_quantity=10,
        bar_volume=1000, reference_price=100, side="SELL",
        policy=ExecutionPolicy(latency_ms=0),
    )
    assert out.status == "NO_TRADE"
    assert out.reason == "outside_regular_session"


def test_missing_timezone_is_fail_closed():
    out = simulate_bar_execution(
        signal_at=datetime(2026, 10, 2, 14), bar_at=ts(14, 0, 1),
        requested_quantity=10, bar_volume=1000, reference_price=100, side="BUY",
    )
    assert out.status == "NO_TRADE"
    assert out.reason == "timezone_required"
