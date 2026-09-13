from __future__ import annotations

import numpy as np
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


def test_ohlcv_integrity_accepts_well_formed_rows_and_zero_volume():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=6, freq="5min")
    frame = _frame(index)
    frame.loc[index[2], "Volume"] = 0

    assert forward._ohlcv_integrity_error(frame, source="stock") is None


def test_ohlcv_integrity_rejects_nonfinite_values():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=6, freq="5min")
    frame = _frame(index)
    frame.loc[index[2], "Close"] = np.inf

    error = forward._ohlcv_integrity_error(frame, source="stock")

    assert error is not None
    assert error.startswith("stock_nonfinite_ohlcv:1:")
    assert "2026-09-11T13:40:00+00:00" in error


def test_ohlcv_integrity_rejects_nonpositive_prices():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=6, freq="5min")
    frame = _frame(index)
    frame.loc[index[1], "Low"] = 0.0

    error = forward._ohlcv_integrity_error(frame, source="stock")

    assert error is not None
    assert error.startswith("stock_nonpositive_price:1:")


def test_ohlcv_integrity_rejects_negative_volume():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=6, freq="5min")
    frame = _frame(index)
    frame.loc[index[3], "Volume"] = -1.0

    error = forward._ohlcv_integrity_error(frame, source="stock")

    assert error is not None
    assert error.startswith("stock_negative_volume:1:")


def test_ohlcv_integrity_rejects_invalid_high_low_envelope():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=6, freq="5min")
    frame = _frame(index)
    frame.loc[index[4], "High"] = frame.loc[index[4], "Close"] - 0.1

    error = forward._ohlcv_integrity_error(frame, source="stock")

    assert error is not None
    assert error.startswith("stock_invalid_ohlc_envelope:1:")


def test_point_in_time_cutoff_ignores_later_malformed_ohlcv():
    index = pd.date_range("2026-09-11T13:30:00Z", periods=8, freq="5min")
    frame = _frame(index)
    frame.loc[index[7], "Volume"] = -1.0

    assert forward._ohlcv_integrity_error(
        frame,
        source="stock",
        as_of=pd.Timestamp("2026-09-11T14:00:00Z"),
    ) is None
    assert forward._ohlcv_integrity_error(frame, source="stock") is not None


def test_forward_adapter_rejects_bad_stock_ohlcv_before_timeline_check(monkeypatch):
    index = pd.date_range("2026-09-11T13:30:00Z", periods=18, freq="5min")
    stock = _frame(index)
    spy = _frame(index)
    stock.loc[index[7], "Close"] = np.inf

    def forbidden_timeline_check(*args, **kwargs):
        raise AssertionError("timeline guard must not run after stock OHLCV failure")

    monkeypatch.setattr(forward, "_stock_timeline_integrity_error", forbidden_timeline_check)

    result = forward.estimate_long_horizon_v5_frame(stock, spy, symbol="AAPL")

    assert result["available"] is False
    assert result["stock_ohlcv_verified"] is False
    assert result["benchmark_ohlcv_verified"] is False
    assert result["stock_timeline_verified"] is False
    assert result["benchmark_alignment_verified"] is False
    assert result["reason"].startswith("stock_nonfinite_ohlcv:1:")


def test_forward_adapter_rejects_bad_benchmark_ohlcv_before_feature_build(monkeypatch):
    index = pd.date_range("2026-09-11T13:30:00Z", periods=18, freq="5min")
    stock = _frame(index)
    spy = _frame(index)
    spy.loc[index[8], "Low"] = -1.0

    def forbidden_feature_build(*args, **kwargs):
        raise AssertionError("feature builder must not run after benchmark OHLCV failure")

    monkeypatch.setattr(forward, "_build_long_horizon_features", forbidden_feature_build)

    result = forward.estimate_long_horizon_v5_frame(stock, spy, symbol="AAPL")

    assert result["available"] is False
    assert result["stock_ohlcv_verified"] is True
    assert result["benchmark_ohlcv_verified"] is False
    assert result["stock_timeline_verified"] is False
    assert result["benchmark_alignment_verified"] is False
    assert result["reason"].startswith("benchmark_nonpositive_price:1:")
