from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.intraday_probability_engine import HORIZON_MINUTES, NEW_YORK, _normalize_ohlcv, _session_key
from app.services.intraday_probability_statistical_engine import (
    FEATURES,
    MIN_TRAIN,
    attach_targets,
    build_statistical_features,
    _fit_logistic,
    _predict,
)

DESIGN_ID = "long-horizon-v5-20260911-a"
LONG_HORIZONS = ("3h", "5h")
LONG_MEMORY_FEATURES = (
    "ret_90m",
    "volatility_90m",
    "relative_strength_90m",
    "directional_persistence_60m",
    "range_expansion_60m",
    "volatility_60m",
    "directional_persistence_30m",
    "range_expansion_30m",
    "session_progress_x_relative_strength_90m",
    "session_progress_x_relative_strength_60m",
)
HORIZON_EXTRA_FEATURES = {
    "3h": (
        "ret_90m",
        "volatility_90m",
        "relative_strength_90m",
        "directional_persistence_60m",
        "range_expansion_60m",
        "session_progress_x_relative_strength_90m",
    ),
    "5h": (
        "volatility_60m",
        "directional_persistence_30m",
        "range_expansion_30m",
        "session_progress_x_relative_strength_60m",
    ),
}

# Fixed before forward evaluation. These are candidate-design constants, not runtime settings.
L2_LONG = {"3h": 6.0, "5h": 8.0}
SHRINK_LONG = {"3h": 0.40, "5h": 0.36}

SEMANTICS = (
    "Research-only regular-hours long-horizon challenger fixed after the 2026-09-11 "
    "pre-registration. It targets only 3h/5h and uses horizon-aware causal memory windows so "
    "feature history cannot consume the future outcome window. Every daily model is fit only on "
    "rows whose horizon outcomes were fully resolved before that test day. Historical results are screening-only."
)


def _build_long_horizon_features(stock: pd.DataFrame, spy: pd.DataFrame) -> pd.DataFrame:
    frame = build_statistical_features(stock, spy).copy()
    session = _session_key(frame.index)

    close = frame["Close"].astype(float)
    high = frame["High"].astype(float)
    low = frame["Low"].astype(float)
    stock_ret = close.groupby(session.values).pct_change()
    signed = np.sign(stock_ret)

    frame["ret_90m"] = close.groupby(session.values).pct_change(18)
    frame["volatility_90m"] = stock_ret.groupby(session.values).transform(
        lambda s: s.rolling(18, min_periods=10).std()
    )
    frame["volatility_60m"] = stock_ret.groupby(session.values).transform(
        lambda s: s.rolling(12, min_periods=6).std()
    )
    frame["directional_persistence_60m"] = signed.groupby(session.values).transform(
        lambda s: s.rolling(12, min_periods=6).mean()
    )
    frame["directional_persistence_30m"] = signed.groupby(session.values).transform(
        lambda s: s.rolling(6, min_periods=4).mean()
    )

    rolling_high_60 = high.groupby(session.values).transform(lambda s: s.rolling(12, min_periods=6).max())
    rolling_low_60 = low.groupby(session.values).transform(lambda s: s.rolling(12, min_periods=6).min())
    frame["range_expansion_60m"] = (rolling_high_60 - rolling_low_60) / close.replace(0, np.nan)
    rolling_high_30 = high.groupby(session.values).transform(lambda s: s.rolling(6, min_periods=4).max())
    rolling_low_30 = low.groupby(session.values).transform(lambda s: s.rolling(6, min_periods=4).min())
    frame["range_expansion_30m"] = (rolling_high_30 - rolling_low_30) / close.replace(0, np.nan)

    spy_aligned = spy.reindex(frame.index).ffill()
    spy_close = spy_aligned["Close"].astype(float)
    spy_ret_90m = spy_close.groupby(session.values).pct_change(18)
    frame["relative_strength_90m"] = frame["ret_90m"] - spy_ret_90m
    frame["session_progress_x_relative_strength_90m"] = frame["time_fraction"] * frame["relative_strength_90m"]
    frame["session_progress_x_relative_strength_60m"] = frame["time_fraction"] * frame["relative_strength_60m"]
    return frame


def _features_for_horizon(horizon: str) -> list[str]:
    if horizon not in LONG_HORIZONS:
        raise ValueError(f"Unsupported long-horizon target: {horizon}")
    return list(FEATURES) + list(HORIZON_EXTRA_FEATURES[horizon])


def _robust_scale_fit(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = np.asarray(X, dtype=float)
    X = np.where(np.isfinite(X), X, np.nan)
    med = np.nanmedian(X, axis=0)
    q1 = np.nanquantile(X, 0.25, axis=0)
    q3 = np.nanquantile(X, 0.75, axis=0)
    scale = q3 - q1
    std = np.nanstd(X, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-10), scale, np.where(np.isfinite(std) & (std > 1e-10), std, 1.0))
    med = np.where(np.isfinite(med), med, 0.0)
    X = np.where(np.isfinite(X), X, med)
    return np.clip((X - med) / scale, -8.0, 8.0), med, scale


def _robust_scale_apply(X: np.ndarray, med: np.ndarray, scale: np.ndarray) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    X = np.where(np.isfinite(X), X, med)
    return np.clip((X - med) / scale, -8.0, 8.0)


def _train_daily_model(dataset: pd.DataFrame, first_ts: pd.Timestamp, horizon: str):
    target = f"target_up_{horizon}"
    cutoff = first_ts - pd.Timedelta(minutes=HORIZON_MINUTES[horizon])
    features = _features_for_horizon(horizon)
    train = dataset.loc[dataset.index <= cutoff].dropna(subset=features + [target]).copy()
    if len(train) < MIN_TRAIN[horizon]:
        return None

    X, med, scale = _robust_scale_fit(train[features].to_numpy(float))
    y = train[target].to_numpy(float)
    weights = _fit_logistic(X, y, l2=L2_LONG[horizon])
    reliability = min(1.0, len(train) / 1400.0)
    return {
        "weights": weights,
        "med": med,
        "scale": scale,
        "reliability": reliability,
        "training_samples": len(train),
        "training_cutoff": pd.Timestamp(cutoff).isoformat(),
        "max_training_timestamp": pd.Timestamp(train.index.max()).isoformat(),
    }


def _predict_with_model(model, row: pd.Series, horizon: str) -> float:
    features = _features_for_horizon(horizon)
    Xraw = row[features].astype(float).to_numpy().reshape(1, -1)
    X = _robust_scale_apply(Xraw, model["med"], model["scale"])
    raw = float(_predict(model["weights"], X)[0])
    shrink = SHRINK_LONG[horizon] * float(model["reliability"])
    p = 0.5 + (raw - 0.5) * shrink
    return round(float(np.clip(p, 0.05, 0.95)) * 100.0, 1)


def _summary(records):
    if not records:
        return {"available": False, "prediction_count": 0}
    y = np.asarray([row["actual_up"] for row in records], dtype=float)
    p = np.asarray([row["p_up"] / 100.0 for row in records], dtype=float)
    clipped = np.clip(p, 1e-9, 1.0 - 1e-9)
    return {
        "available": True,
        "prediction_count": len(records),
        "brier_score": round(float(np.mean((p - y) ** 2)), 6),
        "log_loss": round(float(-np.mean(y * np.log(clipped) + (1.0 - y) * np.log(1.0 - clipped))), 6),
        "accuracy_at_50_pct": round(float(np.mean((p >= 0.5).astype(float) == y)) * 100.0, 2),
    }


def walk_forward_long_horizon_challenger_v5_frame(
    stock,
    spy,
    *,
    symbol="TEST",
    initial_training_days=15,
    stride_bars=6,
    include_records=False,
):
    stock = _normalize_ohlcv(stock)
    spy = _normalize_ohlcv(spy)
    dataset = attach_targets(_build_long_horizon_features(stock, spy))
    local = dataset.index.tz_convert(NEW_YORK)
    dates = pd.Series(local.date, index=dataset.index)
    unique = list(dict.fromkeys(dates.tolist()))
    if len(unique) <= initial_training_days:
        return {"symbol": symbol, "available": False, "warnings": ["Insufficient history."]}

    records = {h: [] for h in LONG_HORIZONS}
    refits = {h: 0 for h in LONG_HORIZONS}
    skipped = {h: 0 for h in LONG_HORIZONS}

    for day in unique[initial_training_days:]:
        day_rows = dataset.loc[dates == day]
        if day_rows.empty:
            continue
        first_ts_by_horizon = {}
        test_rows_by_horizon = {}
        for horizon in LONG_HORIZONS:
            features = _features_for_horizon(horizon)
            valid = day_rows.dropna(subset=features)
            valid = valid.loc[valid[f"target_up_{horizon}"].notna()]
            test_rows = valid.iloc[::max(1, int(stride_bars))]
            test_rows_by_horizon[horizon] = test_rows
            if not test_rows.empty:
                first_ts_by_horizon[horizon] = test_rows.index[0]

        daily_models = {
            horizon: _train_daily_model(dataset, first_ts_by_horizon[horizon], horizon)
            if horizon in first_ts_by_horizon else None
            for horizon in LONG_HORIZONS
        }
        for horizon, model in daily_models.items():
            if model is not None:
                refits[horizon] += 1

        for horizon in LONG_HORIZONS:
            model = daily_models[horizon]
            for ts, row in test_rows_by_horizon[horizon].iterrows():
                actual = row.get(f"target_up_{horizon}")
                if pd.isna(actual) or model is None:
                    skipped[horizon] += 1
                    continue
                records[horizon].append({
                    "timestamp": pd.Timestamp(ts).isoformat(),
                    "p_up": _predict_with_model(model, row, horizon),
                    "actual_up": int(actual),
                })

    feature_count = {h: len(_features_for_horizon(h)) for h in LONG_HORIZONS}
    result = {
        "symbol": str(symbol).upper(),
        "available": any(records[h] for h in LONG_HORIZONS),
        "design_id": DESIGN_ID,
        "method": "daily_refit_horizon_aware_causal_long_memory_logistic_challenger_v5",
        "bar_count": len(stock),
        "initial_training_days": initial_training_days,
        "stride_bars": stride_bars,
        "daily_model_refits": refits,
        "skipped_predictions": skipped,
        "horizons": {h: _summary(records[h]) for h in LONG_HORIZONS},
        "feature_count_by_horizon": feature_count,
        "horizon_extra_features": {h: list(HORIZON_EXTRA_FEATURES[h]) for h in LONG_HORIZONS},
        "historical_results_screening_only": True,
        "runtime_modified": False,
        "promotion_allowed": False,
        "semantics": SEMANTICS,
    }
    if include_records:
        result["prediction_records"] = records
        result["prediction_records_semantics"] = "Chronological OOS records for historical screening and later paired forward evaluation only."
    return result


def walk_forward_long_horizon_challenger_v5(symbol, period="60d", interval="5m", *, include_records=False):
    import yfinance as yf

    ticker = str(symbol or "").strip().upper()
    if not ticker:
        raise ValueError("symbol is required")
    stock = yf.download(ticker, period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    spy = yf.download("SPY", period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    result = walk_forward_long_horizon_challenger_v5_frame(stock, spy, symbol=ticker, include_records=include_records)
    result["period"] = period
    result["interval"] = interval
    return result
