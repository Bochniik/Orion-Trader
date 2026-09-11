import numpy as np
import pandas as pd

from app.services.intraday_probability_engine import NEW_YORK
from app.services.intraday_probability_long_horizon_challenger_v5 import (
    DESIGN_ID,
    HORIZON_EXTRA_FEATURES,
    LONG_HORIZONS,
    LONG_MEMORY_FEATURES,
    _build_long_horizon_features,
    walk_forward_long_horizon_challenger_v5_frame,
)


def _synthetic_market(days=26, seed=73):
    rng = np.random.default_rng(seed)
    stock_parts = []
    spy_parts = []
    stock_price = 100.0
    spy_price = 500.0
    for day_idx, day in enumerate(pd.bdate_range("2026-06-01", periods=days)):
        idx = pd.date_range(
            pd.Timestamp(day.date(), tz=NEW_YORK) + pd.Timedelta(hours=9, minutes=30),
            periods=78,
            freq="5min",
        )
        drift = 0.00008 if day_idx % 5 < 3 else -0.00006
        market_noise = rng.normal(0.0, 0.00055, len(idx))
        spy_ret = 0.00002 + market_noise
        spy_close = spy_price * np.cumprod(1.0 + spy_ret)
        spy_open = np.r_[spy_price, spy_close[:-1]]
        spy_parts.append(pd.DataFrame({
            "Open": spy_open,
            "High": np.maximum(spy_open, spy_close) * 1.0004,
            "Low": np.minimum(spy_open, spy_close) * 0.9996,
            "Close": spy_close,
            "Volume": rng.integers(2_000_000, 8_000_000, len(idx)),
        }, index=idx))
        spy_price = float(spy_close[-1])

        idio = rng.normal(0.0, 0.0010, len(idx))
        lagged_market = np.r_[0.0, spy_ret[:-1]]
        stock_ret = drift + 0.35 * lagged_market + 0.18 * np.r_[0.0, idio[:-1]] + idio
        close = stock_price * np.cumprod(1.0 + stock_ret)
        open_ = np.r_[stock_price, close[:-1]]
        wick = np.abs(rng.normal(0.0007, 0.0002, len(idx)))
        stock_parts.append(pd.DataFrame({
            "Open": open_,
            "High": np.maximum(open_, close) * (1.0 + wick),
            "Low": np.minimum(open_, close) * (1.0 - wick),
            "Close": close,
            "Volume": rng.integers(250_000, 1_800_000, len(idx)),
        }, index=idx))
        stock_price = float(close[-1])
    return pd.concat(stock_parts), pd.concat(spy_parts)


def test_long_memory_features_are_prefix_invariant():
    stock, spy = _synthetic_market(days=3)
    cutoff = stock.index[150]
    prefix = _build_long_horizon_features(stock.loc[:cutoff], spy.loc[:cutoff])
    full = _build_long_horizon_features(stock, spy).loc[:cutoff]
    for feature in LONG_MEMORY_FEATURES:
        pd.testing.assert_series_equal(prefix[feature], full[feature], check_names=True)


def test_five_hour_design_does_not_require_ninety_minute_features():
    assert "ret_90m" not in HORIZON_EXTRA_FEATURES["5h"]
    assert "volatility_90m" not in HORIZON_EXTRA_FEATURES["5h"]
    assert "relative_strength_90m" not in HORIZON_EXTRA_FEATURES["5h"]


def test_v5_emits_only_preregistered_long_horizons_and_is_research_only():
    stock, spy = _synthetic_market()
    report = walk_forward_long_horizon_challenger_v5_frame(
        stock,
        spy,
        symbol="TST",
        initial_training_days=15,
        stride_bars=13,
        include_records=True,
    )
    assert report["available"] is True
    assert report["design_id"] == DESIGN_ID
    assert report["runtime_modified"] is False
    assert report["promotion_allowed"] is False
    assert report["historical_results_screening_only"] is True
    assert tuple(report["prediction_records"]) == LONG_HORIZONS
    for horizon, rows in report["prediction_records"].items():
        assert rows, horizon
        assert all(set(row) == {"timestamp", "p_up", "actual_up"} for row in rows)
        assert all(5.0 <= row["p_up"] <= 95.0 for row in rows)
        assert all(row["actual_up"] in (0, 1) for row in rows)


def test_future_session_mutation_cannot_change_first_test_session_predictions():
    stock, spy = _synthetic_market(days=26)
    kwargs = dict(symbol="TST", initial_training_days=15, stride_bars=13, include_records=True)
    baseline = walk_forward_long_horizon_challenger_v5_frame(stock, spy, **kwargs)

    local_dates = stock.index.tz_convert(NEW_YORK).date
    changed_stock = stock.copy()
    mask = local_dates == local_dates[-1]
    changed_stock.loc[mask, "Close"] *= np.linspace(1.0, 1.30, int(mask.sum()))
    changed_stock.loc[mask, "High"] = np.maximum(changed_stock.loc[mask, "High"], changed_stock.loc[mask, "Close"])
    changed_stock.loc[mask, "Low"] = np.minimum(changed_stock.loc[mask, "Low"], changed_stock.loc[mask, "Close"])
    changed = walk_forward_long_horizon_challenger_v5_frame(changed_stock, spy, **kwargs)

    for horizon in LONG_HORIZONS:
        before = baseline["prediction_records"][horizon]
        after = changed["prediction_records"][horizon]
        assert before and after
        first_session = pd.Timestamp(before[0]["timestamp"]).tz_convert(NEW_YORK).date()
        before_first = [r for r in before if pd.Timestamp(r["timestamp"]).tz_convert(NEW_YORK).date() == first_session]
        after_first = [r for r in after if pd.Timestamp(r["timestamp"]).tz_convert(NEW_YORK).date() == first_session]
        assert before_first == after_first


def test_v5_is_deterministic_for_identical_inputs():
    stock, spy = _synthetic_market(days=24)
    kwargs = dict(symbol="TST", initial_training_days=15, stride_bars=17, include_records=True)
    first = walk_forward_long_horizon_challenger_v5_frame(stock, spy, **kwargs)
    second = walk_forward_long_horizon_challenger_v5_frame(stock, spy, **kwargs)
    assert first["prediction_records"] == second["prediction_records"]
