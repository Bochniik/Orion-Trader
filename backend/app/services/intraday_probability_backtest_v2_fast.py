
from __future__ import annotations
from math import isfinite
from typing import Dict, List

import numpy as np
import pandas as pd

from app.services.intraday_probability_engine import (
    HORIZONS,
    HORIZON_MINUTES,
    NEW_YORK,
    _normalize_ohlcv,
)
from app.services.intraday_probability_statistical_engine import (
    FEATURES,
    MIN_TRAIN,
    L2,
    attach_targets,
    build_statistical_features,
    _scale_fit,
    _scale_one,
    _fit_logistic,
    _predict,
    _local_calibrate,
)

SEMANTICS = (
    "Fast chronological walk-forward validation. Models are retrained once per "
    "trading day per horizon using only outcomes fully resolved before that day's "
    "first tested timestamp. This is leakage-safe but much faster than refitting "
    "for every individual prediction."
)

def _brier(y, p):
    return float(np.mean((p-y)**2)) if len(y) else float("nan")

def _logloss(y, p):
    if not len(y):
        return float("nan")
    p = np.clip(p, 1e-9, 1-1e-9)
    return float(-np.mean(y*np.log(p) + (1-y)*np.log(1-p)))

def _bins(records):
    result = []
    for low in range(0, 100, 10):
        high = low + 10
        rows = [
            r for r in records
            if low <= r["p_up"] < high or (high == 100 and r["p_up"] == 100)
        ]
        if not rows:
            continue
        pred = float(np.mean([r["p_up"] for r in rows]))
        actual = float(np.mean([r["actual_up"] for r in rows]) * 100)
        result.append({
            "range": f"{low}-{high}",
            "count": len(rows),
            "average_predicted_up_pct": round(pred, 2),
            "actual_up_rate_pct": round(actual, 2),
            "calibration_gap_pct": round(actual-pred, 2),
        })
    return result

def _ece(bins):
    total = sum(x["count"] for x in bins)
    if not total:
        return None
    return round(
        sum((x["count"]/total) * abs(x["calibration_gap_pct"]) for x in bins),
        3,
    )

def _summary(records):
    if not records:
        return {"available": False, "prediction_count": 0}

    y = np.array([r["actual_up"] for r in records], dtype=float)
    p = np.array([r["p_up"]/100 for r in records], dtype=float)

    directional = (p >= .55) | (p <= .45)
    dacc = None
    if directional.any():
        pred = (p[directional] >= .5).astype(float)
        dacc = round(float(np.mean(pred == y[directional])) * 100, 2)

    def confident(th):
        mask = (p >= th) | (p <= 1-th)
        if not mask.any():
            return {"count": 0, "accuracy_pct": None}
        pred = (p[mask] >= .5).astype(float)
        return {
            "count": int(mask.sum()),
            "accuracy_pct": round(float(np.mean(pred == y[mask])) * 100, 2),
        }

    bins = _bins(records)
    return {
        "available": True,
        "prediction_count": len(records),
        "actual_up_rate_pct": round(float(np.mean(y))*100, 2),
        "average_predicted_up_pct": round(float(np.mean(p))*100, 2),
        "accuracy_at_50_pct": round(float(np.mean((p>=.5).astype(float) == y))*100, 2),
        "directional_prediction_count": int(directional.sum()),
        "directional_accuracy_pct": dacc,
        "confident_60": confident(.60),
        "confident_65": confident(.65),
        "brier_score": round(_brier(y,p), 5),
        "log_loss": round(_logloss(y,p), 5),
        "expected_calibration_error_pct": _ece(bins),
        "calibration_bins": bins,
    }

def _train_daily_model(dataset, first_ts, horizon):
    target = f"target_up_{horizon}"
    cutoff = first_ts - pd.Timedelta(minutes=HORIZON_MINUTES[horizon])

    train = dataset.loc[
        dataset.index <= cutoff
    ].dropna(subset=FEATURES + [target]).copy()

    if len(train) < MIN_TRAIN[horizon]:
        return None

    split = max(MIN_TRAIN[horizon]//2, int(len(train)*.80))
    fit = train.iloc[:split]
    cal = train.iloc[split:]

    if len(cal) < 40:
        fit = train
        cal = train.iloc[0:0]

    X, med, scale = _scale_fit(fit)
    y = fit[target].to_numpy(float)
    weights = _fit_logistic(X, y, l2=L2[horizon])

    calibration = None
    if len(cal):
        Xc = np.vstack([_scale_one(row, med, scale) for _, row in cal.iterrows()])
        cp = _predict(weights, Xc)
        cy = cal[target].to_numpy(float)
        calibration = (cp, cy)

    reliability = min(1.0, len(train)/1200.0)

    return {
        "weights": weights,
        "med": med,
        "scale": scale,
        "calibration": calibration,
        "reliability": reliability,
        "training_samples": len(train),
    }

def _predict_with_model(model, row):
    x = _scale_one(row, model["med"], model["scale"]).reshape(1,-1)
    raw = float(_predict(model["weights"], x)[0])

    if model["calibration"] is not None:
        cp, cy = model["calibration"]
        p, _ = _local_calibrate(raw, cp, cy)
    else:
        p = raw

    p = 0.5 + (p - 0.5) * model["reliability"]
    return round(float(np.clip(p, .03, .97))*100, 1)

def walk_forward_v2_fast_frame(
    stock,
    spy,
    *,
    symbol="TEST",
    initial_training_days=15,
    stride_bars=6,
):
    stock = _normalize_ohlcv(stock)
    spy = _normalize_ohlcv(spy)
    dataset = attach_targets(build_statistical_features(stock, spy))

    local = dataset.index.tz_convert(NEW_YORK)
    dates = pd.Series(local.date, index=dataset.index)
    unique = list(dict.fromkeys(dates.tolist()))

    if len(unique) <= initial_training_days:
        return {"symbol": symbol, "available": False, "warnings": ["Insufficient history."]}

    test_dates = unique[initial_training_days:]
    records = {h: [] for h in HORIZONS}
    skipped = {h: 0 for h in HORIZONS}
    refits = {h: 0 for h in HORIZONS}

    for day in test_dates:
        day_rows = dataset.loc[dates == day].dropna(subset=FEATURES)
        if day_rows.empty:
            continue

        test_rows = day_rows.iloc[::max(1,int(stride_bars))]
        if test_rows.empty:
            continue

        first_ts = test_rows.index[0]

        daily_models = {}
        for h in HORIZONS:
            daily_models[h] = _train_daily_model(dataset, first_ts, h)
            if daily_models[h] is not None:
                refits[h] += 1

        for ts, row in test_rows.iterrows():
            for h in HORIZONS:
                actual = row.get(f"target_up_{h}")
                if pd.isna(actual):
                    skipped[h] += 1
                    continue

                model = daily_models[h]
                if model is None:
                    skipped[h] += 1
                    continue

                p_up = _predict_with_model(model, row)
                records[h].append({
                    "timestamp": pd.Timestamp(ts).isoformat(),
                    "p_up": p_up,
                    "actual_up": int(actual),
                })

    return {
        "symbol": symbol.upper(),
        "available": any(records[h] for h in HORIZONS),
        "method": "daily_refit_walk_forward_horizon_specific_logistic_v2",
        "bar_count": len(stock),
        "initial_training_days": initial_training_days,
        "stride_bars": stride_bars,
        "daily_model_refits": refits,
        "horizons": {h: _summary(records[h]) for h in HORIZONS},
        "skipped_predictions": skipped,
        "semantics": SEMANTICS,
    }

def walk_forward_v2_fast(symbol, period="60d", interval="5m"):
    import yfinance as yf

    ticker = symbol.strip().upper()
    stock = yf.download(
        ticker, period=period, interval=interval,
        auto_adjust=False, prepost=False, progress=False, threads=False
    )
    spy = yf.download(
        "SPY", period=period, interval=interval,
        auto_adjust=False, prepost=False, progress=False, threads=False
    )

    result = walk_forward_v2_fast_frame(stock, spy, symbol=ticker)
    result["period"] = period
    result["interval"] = interval
    return result

if __name__ == "__main__":
    import json, sys
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "NVDA"
    print(json.dumps(
        walk_forward_v2_fast(ticker),
        indent=2,
        ensure_ascii=False,
        default=str,
    ))
