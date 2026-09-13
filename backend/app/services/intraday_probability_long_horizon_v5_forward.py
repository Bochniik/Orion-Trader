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
EXPECTED_BAR_INTERVAL = pd.Timedelta(minutes=5)
FORWARD_ADAPTER_ID = "long-horizon-v5-forward-adapter-v3"


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


def _point_in_time_index(frame: pd.DataFrame, as_of: pd.Timestamp | None = None) -> pd.DatetimeIndex:
    index = _utc_index(frame)
    if as_of is None:
        return index
    cutoff = pd.Timestamp(as_of)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    return index[index <= cutoff]


def _stock_timeline_integrity_error(
    stock: pd.DataFrame,
    *,
    as_of: pd.Timestamp | None = None,
) -> str | None:
    """Reject stock histories whose row cadence cannot safely represent elapsed time.

    Long-horizon V5 features and targets use fixed bar counts (for example 36 rows for
    3h and 60 rows for 5h). A missing or duplicate stock bar would therefore change the
    elapsed-time meaning of both rolling features and resolved labels. Genuine forward
    evidence must only use a clean five-minute regular-session timeline.
    """
    if stock.empty:
        return "empty_market_data"

    index = _point_in_time_index(stock, as_of=as_of)
    if len(index) == 0:
        return None

    duplicated = index[index.duplicated(keep=False)]
    if len(duplicated) > 0:
        first = pd.Timestamp(duplicated.min()).isoformat()
        last = pd.Timestamp(duplicated.max()).isoformat()
        return f"stock_duplicate_timestamps:{len(duplicated)}:{first}:{last}"

    local = index.tz_convert(NEW_YORK)
    misaligned = [
        ts
        for ts in local
        if ts.minute % 5 != 0 or ts.second != 0 or ts.microsecond != 0 or ts.nanosecond != 0
    ]
    if misaligned:
        first = pd.Timestamp(misaligned[0]).tz_convert("UTC").isoformat()
        last = pd.Timestamp(misaligned[-1]).tz_convert("UTC").isoformat()
        return f"stock_off_grid_timestamps:{len(misaligned)}:{first}:{last}"

    sessions = pd.Series(local.date, index=index)
    gaps: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timedelta]] = []
    for session_day in dict.fromkeys(sessions.tolist()):
        session_index = index[sessions.to_numpy() == session_day]
        if len(session_index) < 2:
            continue
        deltas = session_index[1:] - session_index[:-1]
        for pos, delta in enumerate(deltas):
            if delta != EXPECTED_BAR_INTERVAL:
                gaps.append((pd.Timestamp(session_index[pos]), pd.Timestamp(session_index[pos + 1]), delta))

    if gaps:
        before, after, delta = gaps[0]
        return (
            f"stock_noncontiguous_5m_timeline:{len(gaps)}:"
            f"{before.isoformat()}:{after.isoformat()}:{int(delta.total_seconds())}s"
        )
    return None


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

    stock_index = _point_in_time_index(stock, as_of=as_of)
    spy_index = _point_in_time_index(spy, as_of=as_of)

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
    regular-hours evidence feed. Forward evidence additionally fails closed when the
    stock timeline is not a contiguous five-minute regular-session sequence or SPY
    does not contain every normalized stock timestamp used at or before the requested
    cutoff.
    """
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        raise ValueError("symbol is required")

    stock = _normalize_ohlcv(stock)
    spy = _normalize_ohlcv(spy)
    if stock.empty or spy.empty:
        return {"symbol": ticker, "available": False, "reason": "empty_market_data"}

    stock_timeline_error = _stock_timeline_integrity_error(stock, as_of=as_of)
    if stock_timeline_error is not None:
        return {
            "symbol": ticker,
            "available": False,
            "reason": stock_timeline_error,
            "stock_timeline_verified": False,
            "benchmark_alignment_verified": False,
        }

    benchmark_error = _benchmark_alignment_error(stock, spy, as_of=as_of)
    if benchmark_error is not None:
        return {
            "symbol": ticker,
            "available": False,
            "reason": benchmark_error,
            "stock_timeline_verified": True,
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
        "stock_timeline_verified": True,
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
