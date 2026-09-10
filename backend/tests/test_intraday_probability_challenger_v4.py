import numpy as np
import pandas as pd

from app.services.intraday_probability_backtest_v3 import walk_forward_v3_frame
from app.services.intraday_probability_challenger_v4 import (
    FEATURES,
    REGIME_FEATURES,
    _fit_regime_thresholds,
    walk_forward_challenger_v4_frame,
)
from app.services.intraday_probability_engine import NEW_YORK


def _synthetic_market(days=17, seed=41):
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
        regime = 1.0 if day_idx % 4 in (0, 1) else -1.0
        noise = rng.normal(0.0, 0.0012 if day_idx % 3 else 0.0020, len(idx))
        stock_ret = regime * 0.00012 + 0.22 * np.r_[0.0, noise[:-1]] + noise
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

        spy_noise = rng.normal(0.0, 0.00055, len(idx))
        spy_close = spy_price * np.cumprod(1.0 + 0.00003 + spy_noise)
        spy_open = np.r_[spy_price, spy_close[:-1]]
        spy_parts.append(pd.DataFrame({
            "Open": spy_open,
            "High": np.maximum(spy_open, spy_close) * 1.0004,
            "Low": np.minimum(spy_open, spy_close) * 0.9996,
            "Close": spy_close,
            "Volume": rng.integers(2_000_000, 8_000_000, len(idx)),
        }, index=idx))
        spy_price = float(spy_close[-1])
    return pd.concat(stock_parts), pd.concat(spy_parts)


def test_regime_thresholds_are_fit_from_supplied_training_rows_only():
    frame = pd.DataFrame({
        "volatility_30m": [0.01, 0.02, 0.03, 0.04],
        "trend_slope": [-0.01, 0.02, -0.03, 0.04],
    })
    baseline = _fit_regime_thresholds(frame)
    future = pd.DataFrame({"volatility_30m": [10.0], "trend_slope": [10.0]})
    assert _fit_regime_thresholds(frame).copy() == baseline
    assert _fit_regime_thresholds(pd.concat([frame, future], ignore_index=True)) != baseline


def test_challenger_emits_tournament_compatible_oos_records():
    stock, spy = _synthetic_market()
    report = walk_forward_challenger_v4_frame(
        stock,
        spy,
        symbol="TST",
        initial_training_days=15,
        stride_bars=13,
        include_records=True,
    )
    assert report["available"] is True
    assert report["runtime_modified"] is False
    assert report["feature_count"] == len(FEATURES) + len(REGIME_FEATURES)
    assert report["method"] == "daily_refit_regime_interaction_logistic_challenger_v4"
    for horizon, rows in report["prediction_records"].items():
        assert rows, horizon
        assert all(set(row) == {"timestamp", "p_up", "actual_up"} for row in rows)
        assert all(3.0 <= row["p_up"] <= 97.0 for row in rows)
        assert all(row["actual_up"] in (0, 1) for row in rows)


def test_challenger_pairs_exactly_with_v3_walk_forward_timestamps_and_outcomes():
    stock, spy = _synthetic_market()
    kwargs = dict(symbol="TST", initial_training_days=15, stride_bars=13, include_records=True)
    incumbent = walk_forward_v3_frame(stock, spy, **kwargs)
    challenger = walk_forward_challenger_v4_frame(stock, spy, **kwargs)
    for horizon in incumbent["prediction_records"]:
        left = incumbent["prediction_records"][horizon]
        right = challenger["prediction_records"][horizon]
        assert [(r["timestamp"], r["actual_up"]) for r in left] == [
            (r["timestamp"], r["actual_up"]) for r in right
        ]


def test_future_session_mutation_cannot_change_first_test_session_predictions():
    stock, spy = _synthetic_market(days=18)
    kwargs = dict(symbol="TST", initial_training_days=15, stride_bars=13, include_records=True)
    baseline = walk_forward_challenger_v4_frame(stock, spy, **kwargs)

    local_dates = stock.index.tz_convert(NEW_YORK).date
    final_date = local_dates[-1]
    changed_stock = stock.copy()
    mask = local_dates == final_date
    changed_stock.loc[mask, "Close"] *= np.linspace(1.0, 1.25, int(mask.sum()))
    changed_stock.loc[mask, "High"] = np.maximum(changed_stock.loc[mask, "High"], changed_stock.loc[mask, "Close"])
    changed_stock.loc[mask, "Low"] = np.minimum(changed_stock.loc[mask, "Low"], changed_stock.loc[mask, "Close"])
    changed = walk_forward_challenger_v4_frame(changed_stock, spy, **kwargs)

    for horizon in baseline["prediction_records"]:
        before = baseline["prediction_records"][horizon]
        after = changed["prediction_records"][horizon]
        first_session = pd.Timestamp(before[0]["timestamp"]).tz_convert(NEW_YORK).date()
        before_first = [r for r in before if pd.Timestamp(r["timestamp"]).tz_convert(NEW_YORK).date() == first_session]
        after_first = [r for r in after if pd.Timestamp(r["timestamp"]).tz_convert(NEW_YORK).date() == first_session]
        assert before_first == after_first
