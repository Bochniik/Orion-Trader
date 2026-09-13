from __future__ import annotations

import pandas as pd

from app.services import intraday_probability_long_horizon_v5_forward as forward


def _frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    n = len(index)
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [100.5 + i for i in range(n)],
            "Low": [99.5 + i for i in range(n)],
            "Close": [100.2 + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=index,
    )


def test_benchmark_alignment_accepts_exact_stock_timeline():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=8, freq="5min")
    stock = _frame(index)
    spy = _frame(index)

    assert forward._benchmark_alignment_error(stock, spy) is None


def test_benchmark_alignment_rejects_any_spy_gap_on_stock_timeline():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=8, freq="5min")
    stock = _frame(index)
    spy = _frame(index.delete(3))

    error = forward._benchmark_alignment_error(stock, spy)

    assert error is not None
    assert error.startswith("benchmark_missing_stock_timestamps:1:")
    assert "2026-09-11T13:45:00+00:00" in error


def test_forward_adapter_fails_before_feature_build_when_spy_would_forward_fill(monkeypatch):
    index = pd.date_range("2026-09-11T13:30:00Z", periods=8, freq="5min")
    stock = _frame(index)
    spy = _frame(index.delete(3))

    def forbidden_feature_build(*args, **kwargs):
        raise AssertionError("feature builder must not run with misaligned benchmark data")

    monkeypatch.setattr(forward, "_build_long_horizon_features", forbidden_feature_build)

    result = forward.estimate_long_horizon_v5_frame(stock, spy, symbol="AAPL")

    assert result["available"] is False
    assert result["benchmark_alignment_verified"] is False
    assert result["reason"].startswith("benchmark_missing_stock_timestamps:1:")


def test_extra_spy_timestamps_do_not_block_forward_alignment():
    stock_index = pd.date_range("2026-09-11T13:30:00Z", periods=8, freq="5min")
    spy_index = stock_index.append(pd.DatetimeIndex([pd.Timestamp("2026-09-11T14:10:00Z")]))

    assert forward._benchmark_alignment_error(_frame(stock_index), _frame(spy_index)) is None


def test_point_in_time_cutoff_ignores_unused_future_benchmark_gap():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=8, freq="5min")
    stock = _frame(index)
    spy = _frame(index.delete(-1))

    assert forward._benchmark_alignment_error(
        stock,
        spy,
        as_of=pd.Timestamp("2026-09-11T14:00:00Z"),
    ) is None
    assert forward._benchmark_alignment_error(stock, spy) is not None


def test_alignment_compares_equivalent_instants_across_timezones():
    utc_index = pd.date_range("2026-09-11T13:30:00Z", periods=8, freq="5min")
    ny_index = utc_index.tz_convert("America/New_York")

    assert forward._benchmark_alignment_error(_frame(ny_index), _frame(utc_index)) is None
