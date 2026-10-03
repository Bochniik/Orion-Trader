from app.services.auxiliary_targets import future_realized_volatility, future_relative_volume


def test_future_targets_require_complete_windows():
    assert future_realized_volatility([100, 101, 102], anchor=1, horizon=2) is None
    assert future_relative_volume([10, 10, 20], anchor=1, horizon=2, baseline_window=2) is None


def test_future_relative_volume_uses_only_pre_anchor_baseline():
    value = future_relative_volume([10, 20, 30, 60], anchor=1, horizon=2, baseline_window=2)
    assert value == 3.0


def test_future_targets_fail_closed_on_invalid_data():
    assert future_realized_volatility([100, 0, 101, 102], anchor=1, horizon=2) is None
    assert future_relative_volume([0, 0, 10], anchor=1, horizon=1, baseline_window=2) is None


def test_realized_volatility_is_deterministic_and_non_negative():
    value = future_realized_volatility([100, 101, 99, 102], anchor=0, horizon=3)
    assert value is not None
    assert value >= 0
