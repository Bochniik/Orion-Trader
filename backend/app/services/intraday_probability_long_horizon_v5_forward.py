from __future__ import annotations

from datetime import time
from typing import Any

import pandas as pd

from app.services.intraday_probability_engine import HORIZON_MINUTES, NEW_YORK, _normalize_ohlcv
from app.services.intraday_probability_statistical_engine import attach_targets
from app.services.intraday_probability_long_horizon_challenger_v5 import (
    DESIGN_ID,
    LONG_HORIZONS,
    _build_long_horizon_features,
    _features_for_horizon,
    _predict_with_model,
    _train_daily_model,
)

REGULAR_CLOSE = time(16, 0)
FORWARD_ADAPTER_ID = "long-horizon-v5-forward-adapter-v2"


def _direction(probability_up: float) -> str:
    if probability_up >= 55.0:
        return "bullish"
    if probability_up <= 45.0:
        return "bearish"
    return "neutral"


def _utc_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    index = frame.index
    if index.tz is None:
        return index.tz_localize("UTC")
    return index.tz_convert("UTC")


def _benchmark_alignment_error(
    stock: pd.DataFrame,
    spy: pd.DataFrame,
    *,
    as_of: pd.Timestamp | None = None,
) -> str | None:
    """Reject source frames that would make SPY forward-fill onto used stock timestamps.

    V5's frozen feature builder intentionally remains unchanged. It reindexes SPY to
    the stock timeline and forward-fills gaps. For genuine forward evidence we must
    not silently exercise that fallback because a stale benchmark value can distort
    relative-strength inputs while the stock prediction timestamp still looks fresh.
    """
    if stock.empty or spy.empty:
        return "empty_market_data"

    stock_index = _utc_index(stock)
    spy_index = _utc_index(spy)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        else:
            cutoff = cutoff.tz_convert("UTC")
        stock_index = stock_index[stock_index <= cutoff]
        spy_index = spy_index[spy_index <= cutoff]

    if len(stock_index) == 0:
        return None

    missing = stock_index.difference(spy_index)
    if len(missing) > 0:
        first = pd.Timestamp(missing[0]).isoformat()
        last = pd.Timestamp(missing[-1]).isoformat()
        return f"benchmark_missing_stock_timestamps:{len(missing)}:{first}:{last}"
    return None


def estimate_long_horizon_v5_frame(
    stock: pd.DataFrame,
    spy: pd.DataFrame,
    *,
    symbol: str,
    as_of: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Produce one causal point-in-time V5 shadow forecast from already observed bars.

    The frozen V5 model itself is not modified. Training rows are still restricted by
    the model's horizon-resolution cutoff. Horizons whose target would extend beyond
    the regular-hours close are suppressed because they cannot be settled on the
    regular-hours evidence feed. Forward evidence additionally fails closed when SPY
    does not contain every normalized stock timestamp used at or before the requested
    cutoff, preventing benchmark forward fill from masquerading as current data.
    """
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        raise ValueError("symbol is required")

    stock = _normalize_ohlcv(stock)
    spy = _normalize_ohlcv(spy)
    if stock.empty or spy.empty:
        return {"symbol": ticker, "available": False, "reason": "empty_market_data"}

    benchmark_error = _benchmark_alignment_error(stock, spy, as_of=as_of)
    if benchmark_error is not None:
        return {
            "symbol": ticker,
            "available": False,
            "reason": benchmark_error,
            "benchmark_alignment_verified": False,
        }

    dataset = attach_targets(_build_long_horizon_features(stock, spy))
    if dataset.empty:
        return {"symbol": ticker, "available": False, "reason": "empty_feature_frame"}

    cutoff = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(dataset.index.max())
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    eligible = dataset.loc[dataset.index <= cutoff]
    if eligible.empty:
        return {"symbol": ticker, "available": False, "reason": "no_bar_at_or_before_as_of"}

    prediction_ts = pd.Timestamp(eligible.index.max())
    local_prediction = prediction_ts.tz_convert(NEW_YORK)
    horizons: dict[str, Any] = {}

    for horizon in LONG_HORIZONS:
        target_ts = prediction_ts + pd.Timedelta(minutes=HORIZON_MINUTES[horizon])
        local_target = target_ts.tz_convert(NEW_YORK)
        if local_target.date() != local_prediction.date() or local_target.time() > REGULAR_CLOSE:
            horizons[horizon] = {
                "available": False,
                "reason": "target_outside_regular_session",
                "target_time_utc": target_ts.isoformat(),
            }
            continue

        features = _features_for_horizon(horizon)
        row = eligible.iloc[-1]
        if row[features].isna().any():
            horizons[horizon] = {"available": False, "reason": "insufficient_causal_feature_history"}
            continue

        model = _train_daily_model(dataset, prediction_ts, horizon)
        if model is None:
            horizons[horizon] = {"available": False, "reason": "insufficient_resolved_training_rows"}
            continue

        p_up_pct = _predict_with_model(model, row, horizon)
        horizons[horizon] = {
            "available": True,
            "probability_up": round(p_up_pct / 100.0, 6),
            "probability_down": round(1.0 - p_up_pct / 100.0, 6),
            "direction": _direction(p_up_pct),
            "target_time_utc": target_ts.isoformat(),
            "training_samples": int(model["training_samples"]),
            "training_cutoff": model["training_cutoff"],
            "max_training_timestamp": model["max_training_timestamp"],
        }

    return {
        "symbol": ticker,
        "available": any(row.get("available") for row in horizons.values()),
        "design_id": DESIGN_ID,
        "forward_adapter_id": FORWARD_ADAPTER_ID,
        "as_of": prediction_ts.isoformat(),
        "horizons": horizons,
        "benchmark_alignment_verified": True,
        "research_only": True,
        "runtime_modified": False,
        "promotion_allowed": False,
    }


def estimate_long_horizon_v5(symbol: str, *, period: str = "60d", interval: str = "5m") -> dict[str, Any]:
    import yfinance as yf

    ticker = str(symbol or "").strip().upper()
    stock = yf.download(ticker, period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    spy = yf.download("SPY", period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    result = estimate_long_horizon_v5_frame(stock, spy, symbol=ticker)
    result["period"] = period
    result["interval"] = interval
    return result
