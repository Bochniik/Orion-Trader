from __future__ import annotations

import math
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

MODEL_NAME = "logistic_v4_short_horizon"
PRIMARY_HORIZONS = ("30m", "1h")

# Fixed before benchmark.
L2_MULTIPLIERS = (0.5, 1.0, 2.0, 4.0, 8.0)
SHRINK_GRID = (0.15, 0.25, 0.35, 0.50, 0.65, 0.80)
RECENCY_SESSIONS = 15

# Extra short-horizon features are deliberately compact and derived only from
# current/past bars. No future information is used.
EXTRA_FEATURES = [
    "ret_1",
    "ret_3",
    "ret_6",
    "ret_12",
    "mom_accel_3_6",
    "vol_ratio_3_12",
    "range_pos_12",
    "range_pos_24",
    "vwap_dist",
    "vwap_slope_6",
    "volatility_6",
    "volatility_12",
    "spy_rel_3",
    "spy_rel_6",
    "tod_sin",
    "tod_cos",
]

SHORT_FEATURES = FEATURES + EXTRA_FEATURES


def _brier(y, p):
    return float(np.mean((p - y) ** 2)) if len(y) else float("nan")


def _logloss(y, p):
    if not len(y):
        return float("nan")
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _validation_loss(y, p):
    return _brier(y, p) + 0.25 * _logloss(y, p)


def _rolling_vwap(df):
    # intraday cumulative VWAP reset by NY trading date
    local_date = pd.Series(df.index.tz_convert(NEW_YORK).date, index=df.index)
    typical = (df["High"] + df["Low"] + df["Close"]) / 3.0
    pv = typical * df["Volume"]
    out = pd.Series(index=df.index, dtype=float)
    for day in dict.fromkeys(local_date.tolist()):
        mask = local_date == day
        vol = df.loc[mask, "Volume"].cumsum().replace(0, np.nan)
        out.loc[mask] = pv.loc[mask].cumsum() / vol
    return out


def _add_short_features(stock, spy, dataset):
    frame = dataset.copy()
    stock = stock.reindex(frame.index)
    spy = spy.reindex(frame.index).ffill()

    close = stock["Close"].astype(float)
    volume = stock["Volume"].astype(float)

    frame["ret_1"] = close.pct_change(1)
    frame["ret_3"] = close.pct_change(3)
    frame["ret_6"] = close.pct_change(6)
    frame["ret_12"] = close.pct_change(12)
    frame["mom_accel_3_6"] = frame["ret_3"] - frame["ret_6"] / 2.0

    vol3 = volume.rolling(3).mean()
    vol12 = volume.rolling(12).mean().replace(0, np.nan)
    frame["vol_ratio_3_12"] = vol3 / vol12

    for window in (12, 24):
        lo = stock["Low"].rolling(window).min()
        hi = stock["High"].rolling(window).max()
        span = (hi - lo).replace(0, np.nan)
        frame[f"range_pos_{window}"] = (close - lo) / span

    vwap = _rolling_vwap(stock)
    frame["vwap_dist"] = (close / vwap) - 1.0
    frame["vwap_slope_6"] = vwap.pct_change(6)

    ret1 = close.pct_change()
    frame["volatility_6"] = ret1.rolling(6).std()
    frame["volatility_12"] = ret1.rolling(12).std()

    spy_ret3 = spy["Close"].astype(float).pct_change(3)
    spy_ret6 = spy["Close"].astype(float).pct_change(6)
    frame["spy_rel_3"] = frame["ret_3"] - spy_ret3
    frame["spy_rel_6"] = frame["ret_6"] - spy_ret6

    local = frame.index.tz_convert(NEW_YORK)
    minute = local.hour * 60 + local.minute
    phase = 2 * np.pi * ((minute - 570) / 390.0)
    frame["tod_sin"] = np.sin(phase)
    frame["tod_cos"] = np.cos(phase)

    return frame


def _scale_fit_short(frame):
    med = frame[SHORT_FEATURES].median()
    scale = frame[SHORT_FEATURES].std().replace(0, 1.0).fillna(1.0)
    X = ((frame[SHORT_FEATURES] - med) / scale).fillna(0.0).to_numpy(float)
    return X, med, scale


def _scale_one_short(row, med, scale):
    values = []
    for key in SHORT_FEATURES:
        value = row.get(key)
        if pd.isna(value):
            value = med.get(key, 0.0)
        values.append((float(value) - float(med.get(key, 0.0))) / float(scale.get(key, 1.0)))
    return np.asarray(values, dtype=float)


def _scaled_matrix(frame, med, scale):
    return np.vstack([_scale_one_short(row, med, scale) for _, row in frame.iterrows()])


def _restrict_sessions(frame, sessions):
    if sessions is None or frame.empty:
        return frame
    local_dates = pd.Series(frame.index.tz_convert(NEW_YORK).date, index=frame.index)
    unique = list(dict.fromkeys(local_dates.tolist()))
    keep = set(unique[-int(sessions):])
    return frame.loc[local_dates.isin(keep)]


def _select(train, target, horizon):
    split = max(MIN_TRAIN[horizon] // 2, int(len(train) * 0.72))
    split = min(split, len(train) - 40)
    if split < 40 or len(train) - split < 40:
        return float(L2[horizon]), 0.35

    fit = train.iloc[:split]
    val = train.iloc[split:]
    Xfit, med, scale = _scale_fit_short(fit)
    yfit = fit[target].to_numpy(float)
    Xval = _scaled_matrix(val, med, scale)
    yval = val[target].to_numpy(float)

    best = None
    base = float(L2[horizon])

    for mult in L2_MULTIPLIERS:
        l2_value = base * mult
        weights = _fit_logistic(Xfit, yfit, l2=l2_value)
        raw = np.asarray(_predict(weights, Xval), dtype=float)
        for shrink in SHRINK_GRID:
            p = np.clip(0.5 + (raw - 0.5) * shrink, 0.03, 0.97)
            loss = _validation_loss(yval, p)
            if best is None or loss < best[0]:
                best = (loss, l2_value, shrink)

    return float(best[1]), float(best[2])


def _train_daily_model(dataset, first_ts, horizon):
    target = f"target_up_{horizon}"
    cutoff = first_ts - pd.Timedelta(minutes=HORIZON_MINUTES[horizon])

    train = (
        dataset.loc[dataset.index <= cutoff]
        .dropna(subset=SHORT_FEATURES + [target])
        .copy()
    )

    train = _restrict_sessions(train, RECENCY_SESSIONS)

    if len(train) < MIN_TRAIN[horizon]:
        return None

    selected_l2, selected_shrink = _select(train, target, horizon)
    X, med, scale = _scale_fit_short(train)
    y = train[target].to_numpy(float)
    weights = _fit_logistic(X, y, l2=selected_l2)

    return {
        "weights": weights,
        "med": med,
        "scale": scale,
        "shrink": selected_shrink,
        "reliability": min(1.0, len(train) / 1200.0),
        "training_samples": len(train),
        "selected_l2": selected_l2,
    }


def _predict_with_model(model, row):
    x = _scale_one_short(row, model["med"], model["scale"]).reshape(1, -1)
    raw = float(_predict(model["weights"], x)[0])
    effective_shrink = float(model["shrink"]) * float(model["reliability"])
    p = 0.5 + (raw - 0.5) * effective_shrink
    return round(float(np.clip(p, 0.03, 0.97)) * 100, 1)


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
            "calibration_gap_pct": round(actual - pred, 2),
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
    p = np.array([r["p_up"]/100.0 for r in records], dtype=float)

    directional = (p >= 0.55) | (p <= 0.45)

    directional_accuracy = None
    if directional.any():
        pred = (p[directional] >= 0.5).astype(float)
        directional_accuracy = round(float(np.mean(pred == y[directional]))*100, 2)

    def confident(threshold):
        mask = (p >= threshold) | (p <= 1-threshold)
        if not mask.any():
            return {"count": 0, "accuracy_pct": None}
        pred = (p[mask] >= 0.5).astype(float)
        return {
            "count": int(mask.sum()),
            "accuracy_pct": round(float(np.mean(pred == y[mask]))*100, 2),
        }

    bins = _bins(records)
    return {
        "available": True,
        "prediction_count": len(records),
        "directional_prediction_count": int(directional.sum()),
        "directional_accuracy_pct": directional_accuracy,
        "confident_60": confident(0.60),
        "confident_65": confident(0.65),
        "brier_score": round(_brier(y, p), 5),
        "log_loss": round(_logloss(y, p), 5),
        "expected_calibration_error_pct": _ece(bins),
        "calibration_bins": bins,
    }


def walk_forward_v4_short_frame(stock, spy, *, symbol="TEST", initial_training_days=15, stride_bars=6):
    stock = _normalize_ohlcv(stock)
    spy = _normalize_ohlcv(spy)
    dataset = attach_targets(build_statistical_features(stock, spy))
    dataset = _add_short_features(stock, spy, dataset)

    local = dataset.index.tz_convert(NEW_YORK)
    dates = pd.Series(local.date, index=dataset.index)
    unique_dates = list(dict.fromkeys(dates.tolist()))

    if len(unique_dates) <= initial_training_days:
        return {"symbol": symbol, "available": False, "warnings": ["Insufficient history."]}

    test_dates = unique_dates[initial_training_days:]
    records = {h: [] for h in HORIZONS}
    skipped = {h: 0 for h in HORIZONS}

    for day in test_dates:
        day_rows = dataset.loc[dates == day].dropna(subset=SHORT_FEATURES)
        if day_rows.empty:
            continue

        test_rows = day_rows.iloc[::max(1, int(stride_bars))]
        if test_rows.empty:
            continue

        first_ts = test_rows.index[0]
        daily_models = {
            h: _train_daily_model(dataset, first_ts, h)
            for h in HORIZONS
        }

        for ts, row in test_rows.iterrows():
            for horizon in HORIZONS:
                actual = row.get(f"target_up_{horizon}")
                if pd.isna(actual):
                    skipped[horizon] += 1
                    continue

                model = daily_models[horizon]
                if model is None:
                    skipped[horizon] += 1
                    continue

                records[horizon].append({
                    "timestamp": pd.Timestamp(ts).isoformat(),
                    "p_up": _predict_with_model(model, row),
                    "actual_up": int(actual),
                })

    return {
        "symbol": symbol.upper(),
        "available": any(records[h] for h in HORIZONS),
        "method": MODEL_NAME,
        "primary_horizons": list(PRIMARY_HORIZONS),
        "bar_count": len(stock),
        "initial_training_days": initial_training_days,
        "stride_bars": stride_bars,
        "recency_sessions": RECENCY_SESSIONS,
        "feature_count": len(SHORT_FEATURES),
        "extra_features": EXTRA_FEATURES,
        "horizons": {h: _summary(records[h]) for h in HORIZONS},
        "skipped_predictions": skipped,
        "semantics": (
            "Leakage-safe daily-refit short-horizon logistic challenger using "
            "current/past intraday momentum, volume, range-position, VWAP, "
            "volatility, benchmark-relative-strength and time-of-day features. "
            "All training rows have fully resolved targets before the first "
            "tested timestamp of each day."
        ),
        "production_modified": False,
    }


def walk_forward_v4_short(symbol, period="60d", interval="5m"):
    import yfinance as yf

    ticker = symbol.strip().upper()
    stock = yf.download(
        ticker, period=period, interval=interval,
        auto_adjust=False, prepost=False,
        progress=False, threads=False,
    )
    spy = yf.download(
        "SPY", period=period, interval=interval,
        auto_adjust=False, prepost=False,
        progress=False, threads=False,
    )

    result = walk_forward_v4_short_frame(stock, spy, symbol=ticker)
    result["period"] = period
    result["interval"] = interval
    return result


if __name__ == "__main__":
    import json, sys
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "NVDA"
    print(json.dumps(walk_forward_v4_short(ticker), indent=2, ensure_ascii=False, default=str))
