from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.intraday_probability_engine import (
    HORIZONS, HORIZON_MINUTES, NEW_YORK, _normalize_ohlcv,
)
from app.services.intraday_probability_statistical_engine import (
    FEATURES, MIN_TRAIN, L2,
    attach_targets, build_statistical_features,
    _scale_fit, _scale_one, _fit_logistic, _predict,
)

SEMANTICS = (
    "Leakage-safe daily-refit walk-forward validation of conservative logistic v3. "
    "Hyperparameters are selected only from historical observations whose outcomes "
    "were fully resolved before the first tested timestamp of each day."
)

L2_MULTIPLIERS = (0.5, 1.0, 2.0, 4.0, 8.0)
SHRINK_GRID = (0.15, 0.25, 0.35, 0.50, 0.65, 0.80, 1.00)


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
        rows = [r for r in records if low <= r["p_up"] < high or (high == 100 and r["p_up"] == 100)]
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
    return round(sum((x["count"]/total)*abs(x["calibration_gap_pct"]) for x in bins), 3)


def _summary(records):
    if not records:
        return {"available": False, "prediction_count": 0}

    y = np.array([r["actual_up"] for r in records], dtype=float)
    p = np.array([r["p_up"]/100 for r in records], dtype=float)

    directional = (p >= .55) | (p <= .45)
    dacc = None
    if directional.any():
        pred = (p[directional] >= .5).astype(float)
        dacc = round(float(np.mean(pred == y[directional]))*100, 2)

    def confident(th):
        mask = (p >= th) | (p <= 1-th)
        if not mask.any():
            return {"count": 0, "accuracy_pct": None}
        pred = (p[mask] >= .5).astype(float)
        return {
            "count": int(mask.sum()),
            "accuracy_pct": round(float(np.mean(pred == y[mask]))*100, 2),
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


def _scaled_matrix(frame, med, scale):
    return np.vstack([_scale_one(row, med, scale) for _, row in frame.iterrows()])


def _validation_loss(y, p):
    return _brier(y, p) + 0.25*_logloss(y, p)


def _select_l2_and_shrink(train, target, horizon):
    split = max(MIN_TRAIN[horizon]//2, int(len(train)*0.72))
    split = min(split, len(train)-40)
    if split < 40 or len(train)-split < 40:
        return float(L2[horizon]), 0.50, None

    fit = train.iloc[:split]
    val = train.iloc[split:]

    Xfit, med, scale = _scale_fit(fit)
    yfit = fit[target].to_numpy(float)
    Xval = _scaled_matrix(val, med, scale)
    yval = val[target].to_numpy(float)

    base_l2 = float(L2[horizon])
    best = None

    for mult in L2_MULTIPLIERS:
        l2_value = base_l2*mult
        weights = _fit_logistic(Xfit, yfit, l2=l2_value)
        raw = np.asarray(_predict(weights, Xval), dtype=float)

        for shrink in SHRINK_GRID:
            p = np.clip(0.5 + (raw-0.5)*shrink, .03, .97)
            loss = _validation_loss(yval, p)
            if best is None or loss < best[0]:
                best = (loss, l2_value, shrink)

    if best is None:
        return base_l2, 0.50, None
    return float(best[1]), float(best[2]), float(best[0])


def _train_daily_model(dataset, first_ts, horizon):
    target = f"target_up_{horizon}"
    cutoff = first_ts - pd.Timedelta(minutes=HORIZON_MINUTES[horizon])

    train = dataset.loc[dataset.index <= cutoff].dropna(subset=FEATURES + [target]).copy()
    if len(train) < MIN_TRAIN[horizon]:
        return None

    selected_l2, selected_shrink, inner_loss = _select_l2_and_shrink(train, target, horizon)

    X, med, scale = _scale_fit(train)
    y = train[target].to_numpy(float)
    weights = _fit_logistic(X, y, l2=selected_l2)

    return {
        "weights": weights,
        "med": med,
        "scale": scale,
        "shrink": selected_shrink,
        "reliability": min(1.0, len(train)/1200.0),
        "selected_l2": selected_l2,
        "inner_validation_loss": inner_loss,
        "training_samples": len(train),
    }


def _predict_with_model(model, row):
    x = _scale_one(row, model["med"], model["scale"]).reshape(1,-1)
    raw = float(_predict(model["weights"], x)[0])
    shrink = float(model["shrink"]) * float(model["reliability"])
    p = 0.5 + (raw-0.5)*shrink
    return round(float(np.clip(p, .03, .97))*100, 1)


def walk_forward_v3_frame(stock, spy, *, symbol="TEST", initial_training_days=15, stride_bars=6):
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
        test_rows = day_rows.iloc[::max(1, int(stride_bars))]
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
                records[h].append({
                    "timestamp": pd.Timestamp(ts).isoformat(),
                    "p_up": _predict_with_model(model, row),
                    "actual_up": int(actual),
                })

    return {
        "symbol": symbol.upper(),
        "available": any(records[h] for h in HORIZONS),
        "method": "daily_refit_walk_forward_conservative_regularized_logistic_v3",
        "bar_count": len(stock),
        "initial_training_days": initial_training_days,
        "stride_bars": stride_bars,
        "daily_model_refits": refits,
        "horizons": {h: _summary(records[h]) for h in HORIZONS},
        "skipped_predictions": skipped,
        "semantics": SEMANTICS,
    }


def walk_forward_v3(symbol, period="60d", interval="5m"):
    import yfinance as yf
    ticker = symbol.strip().upper()
    stock = yf.download(ticker, period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    spy = yf.download("SPY", period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    result = walk_forward_v3_frame(stock, spy, symbol=ticker)
    result["period"] = period
    result["interval"] = interval
    return result


if __name__ == "__main__":
    import json, sys
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "NVDA"
    print(json.dumps(walk_forward_v3(ticker), indent=2, ensure_ascii=False, default=str))
