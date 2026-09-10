from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.intraday_probability_engine import HORIZONS, HORIZON_MINUTES, NEW_YORK, _normalize_ohlcv
from app.services.intraday_probability_statistical_engine import (
    FEATURES,
    MIN_TRAIN,
    L2,
    attach_targets,
    build_statistical_features,
    _fit_logistic,
    _predict,
)

SEMANTICS = (
    "Offline regime-aware regular-hours challenger. Regime thresholds and all model parameters "
    "are fit only from observations whose outcomes were fully resolved before each test day."
)

REGIME_FEATURES = (
    "regime_high_vol",
    "regime_trending",
    "regime_high_vol_x_ret_5m",
    "regime_high_vol_x_volume_z",
    "regime_trending_x_relative_strength_30m",
    "regime_trending_x_vwap_distance",
)

SHRINK = {"30m": 0.55, "1h": 0.52, "3h": 0.48, "5h": 0.44}


def _finite_array(values: np.ndarray, fallback: float = 0.0) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return np.where(np.isfinite(values), values, fallback)


def _fit_regime_thresholds(train: pd.DataFrame) -> dict[str, float]:
    vol = pd.to_numeric(train["volatility_30m"], errors="coerce")
    trend = pd.to_numeric(train["trend_slope"], errors="coerce").abs()
    return {
        "high_vol": float(vol.quantile(0.70)),
        "trending": float(trend.quantile(0.65)),
    }


def _augment(frame: pd.DataFrame, thresholds: dict[str, float]) -> np.ndarray:
    base = frame[list(FEATURES)].astype(float).to_numpy()
    high_vol = (pd.to_numeric(frame["volatility_30m"], errors="coerce").to_numpy(float) >= thresholds["high_vol"]).astype(float)
    trending = (pd.to_numeric(frame["trend_slope"], errors="coerce").abs().to_numpy(float) >= thresholds["trending"]).astype(float)
    ret_5m = pd.to_numeric(frame["ret_5m"], errors="coerce").to_numpy(float)
    volume_z = pd.to_numeric(frame["volume_z"], errors="coerce").to_numpy(float)
    rs30 = pd.to_numeric(frame["relative_strength_30m"], errors="coerce").to_numpy(float)
    vwap = pd.to_numeric(frame["vwap_distance"], errors="coerce").to_numpy(float)
    extra = np.column_stack([
        high_vol,
        trending,
        high_vol * ret_5m,
        high_vol * volume_z,
        trending * rs30,
        trending * vwap,
    ])
    return np.column_stack([base, extra])


def _robust_scale_fit(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = _finite_array(X, np.nan)
    med = np.nanmedian(X, axis=0)
    q1 = np.nanquantile(X, 0.25, axis=0)
    q3 = np.nanquantile(X, 0.75, axis=0)
    scale = q3 - q1
    std = np.nanstd(X, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-10), scale, np.where(np.isfinite(std) & (std > 1e-10), std, 1.0))
    X = np.where(np.isfinite(X), X, med)
    return np.clip((X - med) / scale, -8.0, 8.0), med, scale


def _robust_scale_apply(X: np.ndarray, med: np.ndarray, scale: np.ndarray) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    X = np.where(np.isfinite(X), X, med)
    return np.clip((X - med) / scale, -8.0, 8.0)


def _train_daily_model(dataset: pd.DataFrame, first_ts: pd.Timestamp, horizon: str):
    target = f"target_up_{horizon}"
    cutoff = first_ts - pd.Timedelta(minutes=HORIZON_MINUTES[horizon])
    train = dataset.loc[dataset.index <= cutoff].dropna(subset=list(FEATURES) + [target]).copy()
    if len(train) < MIN_TRAIN[horizon]:
        return None

    thresholds = _fit_regime_thresholds(train)
    Xraw = _augment(train, thresholds)
    X, med, scale = _robust_scale_fit(Xraw)
    y = train[target].to_numpy(float)
    weights = _fit_logistic(X, y, l2=float(L2[horizon]) * 1.25)
    reliability = min(1.0, len(train) / 1200.0)
    return {
        "weights": weights,
        "med": med,
        "scale": scale,
        "thresholds": thresholds,
        "reliability": reliability,
        "training_samples": len(train),
    }


def _predict_with_model(model, row: pd.Series, horizon: str) -> float:
    frame = row.to_frame().T
    Xraw = _augment(frame, model["thresholds"])
    X = _robust_scale_apply(Xraw, model["med"], model["scale"])
    raw = float(_predict(model["weights"], X)[0])
    shrink = float(SHRINK[horizon]) * float(model["reliability"])
    p = 0.5 + (raw - 0.5) * shrink
    return round(float(np.clip(p, 0.03, 0.97)) * 100.0, 1)


def _summary(records):
    if not records:
        return {"available": False, "prediction_count": 0}
    y = np.asarray([r["actual_up"] for r in records], dtype=float)
    p = np.asarray([r["p_up"] / 100.0 for r in records], dtype=float)
    clipped = np.clip(p, 1e-9, 1.0 - 1e-9)
    return {
        "available": True,
        "prediction_count": len(records),
        "brier_score": round(float(np.mean((p - y) ** 2)), 6),
        "log_loss": round(float(-np.mean(y * np.log(clipped) + (1.0 - y) * np.log(1.0 - clipped))), 6),
        "accuracy_at_50_pct": round(float(np.mean((p >= 0.5).astype(float) == y)) * 100.0, 2),
    }


def walk_forward_challenger_v4_frame(
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
    dataset = attach_targets(build_statistical_features(stock, spy))
    local = dataset.index.tz_convert(NEW_YORK)
    dates = pd.Series(local.date, index=dataset.index)
    unique = list(dict.fromkeys(dates.tolist()))
    if len(unique) <= initial_training_days:
        return {"symbol": symbol, "available": False, "warnings": ["Insufficient history."]}

    records = {h: [] for h in HORIZONS}
    refits = {h: 0 for h in HORIZONS}
    skipped = {h: 0 for h in HORIZONS}

    for day in unique[initial_training_days:]:
        day_rows = dataset.loc[dates == day].dropna(subset=list(FEATURES))
        if day_rows.empty:
            continue
        test_rows = day_rows.iloc[::max(1, int(stride_bars))]
        if test_rows.empty:
            continue
        first_ts = test_rows.index[0]
        daily_models = {}
        for horizon in HORIZONS:
            daily_models[horizon] = _train_daily_model(dataset, first_ts, horizon)
            if daily_models[horizon] is not None:
                refits[horizon] += 1

        for ts, row in test_rows.iterrows():
            for horizon in HORIZONS:
                actual = row.get(f"target_up_{horizon}")
                model = daily_models[horizon]
                if pd.isna(actual) or model is None:
                    skipped[horizon] += 1
                    continue
                records[horizon].append({
                    "timestamp": pd.Timestamp(ts).isoformat(),
                    "p_up": _predict_with_model(model, row, horizon),
                    "actual_up": int(actual),
                })

    result = {
        "symbol": str(symbol).upper(),
        "available": any(records[h] for h in HORIZONS),
        "method": "daily_refit_regime_interaction_logistic_challenger_v4",
        "bar_count": len(stock),
        "initial_training_days": initial_training_days,
        "stride_bars": stride_bars,
        "daily_model_refits": refits,
        "skipped_predictions": skipped,
        "horizons": {h: _summary(records[h]) for h in HORIZONS},
        "feature_count": len(FEATURES) + len(REGIME_FEATURES),
        "regime_features": list(REGIME_FEATURES),
        "runtime_modified": False,
        "semantics": SEMANTICS,
    }
    if include_records:
        result["prediction_records"] = records
        result["prediction_records_semantics"] = "Chronological OOS records for offline paired tournament use only."
    return result


def walk_forward_challenger_v4(symbol, period="60d", interval="5m", *, include_records=False):
    import yfinance as yf
    ticker = str(symbol or "").strip().upper()
    stock = yf.download(ticker, period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    spy = yf.download("SPY", period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    result = walk_forward_challenger_v4_frame(stock, spy, symbol=ticker, include_records=include_records)
    result["period"] = period
    result["interval"] = interval
    return result
