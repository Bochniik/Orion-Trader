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


def test_stock_timeline_accepts_contiguous_partial_regular_session():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=18, freq="5min")

    assert forward._stock_timeline_integrity_error(_frame(index)) is None


def test_stock_timeline_allows_overnight_session_boundary():
    first = pd.date_range("2026-09-10T19:30:00Z", periods=6, freq="5min")
    second = pd.date_range("2026-09-11T13:30:00Z", periods=6, freq="5min")
    index = first.append(second)

    assert forward._stock_timeline_integrity_error(_frame(index)) is None


def test_stock_timeline_rejects_missing_five_minute_bar():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=18, freq="5min")
    stock = _frame(index.delete(7))

    error = forward._stock_timeline_integrity_error(stock)

    assert error is not None
    assert error.startswith("stock_noncontiguous_5m_timeline:1:")
    assert "2026-09-11T14:00:00+00:00" in error
    assert "2026-09-11T14:10:00+00:00" in error
    assert error.endswith(":600s")


def test_stock_timeline_rejects_duplicate_timestamp():
    base = pd.date_range("2026-09-11T13:30:00Z", periods=8, freq="5min")
    index = base.insert(4, base[3])

    error = forward._stock_timeline_integrity_error(_frame(index))

    assert error is not None
    assert error.startswith("stock_duplicate_timestamps:2:")


def test_stock_timeline_rejects_off_grid_timestamp():
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-09-11T13:30:00Z"),
            pd.Timestamp("2026-09-11T13:35:00Z"),
            pd.Timestamp("2026-09-11T13:40:30Z"),
        ]
    )

    error = forward._stock_timeline_integrity_error(_frame(index))

    assert error is not None
    assert error.startswith("stock_off_grid_timestamps:1:")
    assert "2026-09-11T13:40:30+00:00" in error


def test_point_in_time_cutoff_ignores_later_stock_gap():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=12, freq="5min")
    stock = _frame(index.delete(9))

    assert forward._stock_timeline_integrity_error(
        stock,
        as_of=pd.Timestamp("2026-09-11T14:05:00Z"),
    ) is None
    assert forward._stock_timeline_integrity_error(stock) is not None


def test_forward_adapter_fails_before_feature_build_on_stock_gap(monkeypatch):
    index = pd.date_range("2026-09-11T13:30:00Z", periods=18, freq="5min")
    stock = _frame(index.delete(7))
    spy = _frame(index)

    def forbidden_feature_build(*args, **kwargs):
        raise AssertionError("feature builder must not run with a noncontiguous stock timeline")

    monkeypatch.setattr(forward, "_build_long_horizon_features", forbidden_feature_build)

    result = forward.estimate_long_horizon_v5_frame(stock, spy, symbol="AAPL")

    assert result["available"] is False
    assert result["stock_timeline_verified"] is False
    assert result["benchmark_alignment_verified"] is False
    assert result["reason"].startswith("stock_noncontiguous_5m_timeline:1:")


def test_stock_timeline_guard_precedes_benchmark_alignment_guard(monkeypatch):
    index = pd.date_range("2026-09-11T13:30:00Z", periods=18, freq="5min")
    stock = _frame(index.delete(7))
    spy = _frame(index.delete(6))

    def forbidden_benchmark_check(*args, **kwargs):
        raise AssertionError("benchmark check must not run after stock timeline failure")

    monkeypatch.setattr(forward, "_benchmark_alignment_error", forbidden_benchmark_check)

    result = forward.estimate_long_horizon_v5_frame(stock, spy, symbol="AAPL")

    assert result["available"] is False
    assert result["reason"].startswith("stock_noncontiguous_5m_timeline:1:")
