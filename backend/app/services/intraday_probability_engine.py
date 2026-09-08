from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, isfinite, sqrt
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


NEW_YORK = ZoneInfo("America/New_York")

HORIZONS = {
    "30m": 6,    # 6 x 5-minute bars
    "1h": 12,
    "3h": 36,
    "5h": 60,
}

HORIZON_MINUTES = {
    "30m": 30,
    "1h": 60,
    "3h": 180,
    "5h": 300,
}

FEATURE_COLUMNS = [
    "ret_5m",
    "ret_15m",
    "ret_30m",
    "ret_60m",
    "volatility_30m",
    "volume_z",
    "vwap_distance",
    "range_position",
    "trend_slope",
]

SEMANTICS = (
    "Empirical intraday directional probability estimated from historical "
    "same-session analogs using only information available at each prediction "
    "timestamp. It is not a guarantee, not an Orion Score, and not order execution."
)


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _regular_session_only(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")

    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")

    local = frame.index.tz_convert(NEW_YORK)
    mask = (
        (local.weekday < 5)
        & (local.time >= pd.Timestamp("09:30").time())
        & (local.time < pd.Timestamp("16:00").time())
    )
    return frame.loc[mask].copy()


def _normalize_ohlcv(raw: Any) -> pd.DataFrame:
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return pd.DataFrame()

    frame = raw.copy()

    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [
            col[0] if isinstance(col, tuple) else col
            for col in frame.columns
        ]

    rename = {}
    for col in frame.columns:
        key = str(col).lower()
        if key == "open":
            rename[col] = "Open"
        elif key == "high":
            rename[col] = "High"
        elif key == "low":
            rename[col] = "Low"
        elif key == "close":
            rename[col] = "Close"
        elif key == "volume":
            rename[col] = "Volume"

    frame = frame.rename(columns=rename)
    required = ["Open", "High", "Low", "Close", "Volume"]

    if any(col not in frame.columns for col in required):
        return pd.DataFrame()

    frame = frame[required].copy()
    frame[required] = frame[required].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=required)

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")

    frame = frame.loc[~frame.index.isna()].sort_index()

    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")

    return _regular_session_only(frame)


def _session_key(index: pd.DatetimeIndex) -> pd.Series:
    local = index.tz_convert(NEW_YORK)
    return pd.Series(local.date, index=index)


def _build_features(frame: pd.DataFrame) -> pd.DataFrame:
    f = frame.copy()
    close = f["Close"].astype(float)
    volume = f["Volume"].astype(float)

    f["ret_5m"] = close.pct_change(1)
    f["ret_15m"] = close.pct_change(3)
    f["ret_30m"] = close.pct_change(6)
    f["ret_60m"] = close.pct_change(12)

    f["volatility_30m"] = close.pct_change().rolling(6, min_periods=4).std()

    vol_mean = volume.rolling(20, min_periods=8).mean()
    vol_std = volume.rolling(20, min_periods=8).std().replace(0, np.nan)
    f["volume_z"] = (volume - vol_mean) / vol_std

    typical = (f["High"] + f["Low"] + f["Close"]) / 3.0
    session = _session_key(f.index)

    cumulative_pv = (typical * volume).groupby(session.values).cumsum()
    cumulative_v = volume.groupby(session.values).cumsum().replace(0, np.nan)
    f["session_vwap"] = cumulative_pv / cumulative_v
    f["vwap_distance"] = close / f["session_vwap"] - 1.0

    rolling_high = f["High"].rolling(12, min_periods=4).max()
    rolling_low = f["Low"].rolling(12, min_periods=4).min()
    denom = (rolling_high - rolling_low).replace(0, np.nan)
    f["range_position"] = (close - rolling_low) / denom

    log_close = np.log(close.replace(0, np.nan))
    f["trend_slope"] = (
        log_close.diff(6) / 6.0
    )

    return f


def _attach_targets(features: pd.DataFrame) -> pd.DataFrame:
    result = features.copy()
    session = _session_key(result.index)

    for label, bars_ahead in HORIZONS.items():
        future_close = result["Close"].shift(-bars_ahead)
        future_session = session.shift(-bars_ahead)
        same_session = session.eq(future_session)

        ret = future_close / result["Close"] - 1.0
        ret = ret.where(same_session)

        result[f"target_return_{label}"] = ret
        result[f"target_up_{label}"] = (ret > 0).astype(float).where(ret.notna())

    return result


def _robust_standardize(
    history: pd.DataFrame,
    current: pd.Series,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Dict[str, float]]]:
    hist_matrix = history[FEATURE_COLUMNS].astype(float).copy()
    current_vec = current[FEATURE_COLUMNS].astype(float).copy()

    stats: Dict[str, Dict[str, float]] = {}

    for col in FEATURE_COLUMNS:
        series = hist_matrix[col]
        median = float(series.median())
        q1 = float(series.quantile(0.25))
        q3 = float(series.quantile(0.75))
        scale = q3 - q1

        if not isfinite(scale) or scale <= 1e-12:
            std = float(series.std())
            scale = std if isfinite(std) and std > 1e-12 else 1.0

        hist_matrix[col] = (series - median) / scale
        current_vec[col] = (float(current_vec[col]) - median) / scale
        stats[col] = {"center": median, "scale": scale}

    return (
        hist_matrix.to_numpy(dtype=float),
        current_vec.to_numpy(dtype=float),
        stats,
    )


def _wilson_interval(successes: float, total: float, z: float = 1.96) -> Tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0

    p = successes / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    margin = (
        z
        * sqrt((p * (1.0 - p) / total) + (z * z / (4.0 * total * total)))
        / denom
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _estimate_one_horizon(
    history: pd.DataFrame,
    current: pd.Series,
    label: str,
    *,
    neighbor_count: int = 180,
    min_samples: int = 80,
) -> Dict[str, Any]:
    target_col = f"target_up_{label}"
    return_col = f"target_return_{label}"

    usable = history.dropna(subset=FEATURE_COLUMNS + [target_col, return_col]).copy()

    if len(usable) < min_samples:
        return {
            "available": False,
            "horizon": label,
            "probability_up": None,
            "probability_down": None,
            "sample_size": len(usable),
            "reason": f"Need at least {min_samples} historical resolved samples.",
        }

    matrix, vector, _ = _robust_standardize(usable, current)

    distances = np.sqrt(np.nanmean((matrix - vector) ** 2, axis=1))
    valid = np.isfinite(distances)

    usable = usable.iloc[np.where(valid)[0]].copy()
    distances = distances[valid]

    if len(usable) < min_samples:
        return {
            "available": False,
            "horizon": label,
            "probability_up": None,
            "probability_down": None,
            "sample_size": len(usable),
            "reason": "Too few finite historical analogs after feature validation.",
        }

    order = np.argsort(distances)
    k = min(neighbor_count, len(order))
    selected_idx = order[:k]

    analogs = usable.iloc[selected_idx].copy()
    selected_distances = distances[selected_idx]

    # Similarity weights. Closer historical states contribute more.
    distance_scale = float(np.median(selected_distances))
    if not isfinite(distance_scale) or distance_scale <= 1e-12:
        distance_scale = 1.0

    weights = np.exp(-selected_distances / distance_scale)
    weights = np.clip(weights, 1e-6, None)

    y = analogs[target_col].to_numpy(dtype=float)
    returns = analogs[return_col].to_numpy(dtype=float)

    weighted_up = float(np.sum(weights * y))
    weighted_total = float(np.sum(weights))

    raw_probability = weighted_up / weighted_total

    # Conservative beta-binomial style shrinkage toward 50%.
    # The prior prevents small/weak analog sets from pretending to be certain.
    prior_strength = 30.0
    effective_n = (weighted_total ** 2) / float(np.sum(weights ** 2))
    shrunk_probability = (
        raw_probability * effective_n + 0.5 * prior_strength
    ) / (effective_n + prior_strength)

    up_pct = round(shrunk_probability * 100.0, 1)
    down_pct = round(100.0 - up_pct, 1)

    successes_for_interval = shrunk_probability * effective_n
    lo, hi = _wilson_interval(successes_for_interval, effective_n)

    weighted_mean_return = float(np.sum(weights * returns) / weighted_total)
    weighted_abs_return = float(np.sum(weights * np.abs(returns)) / weighted_total)

    direction = (
        "bullish"
        if up_pct >= 55.0
        else "bearish"
        if up_pct <= 45.0
        else "neutral"
    )

    confidence = abs(up_pct - 50.0) * 2.0

    # Penalize weak analog similarity and small effective sample size.
    similarity_score = 100.0 * exp(-float(np.mean(selected_distances)))
    sample_score = min(100.0, effective_n / 120.0 * 100.0)
    evidence_quality = 0.55 * similarity_score + 0.45 * sample_score

    return {
        "available": True,
        "horizon": label,
        "direction": direction,
        "probability_up": up_pct,
        "probability_down": down_pct,
        "directional_confidence": round(confidence, 1),
        "expected_return_pct": round(weighted_mean_return * 100.0, 3),
        "expected_absolute_move_pct": round(weighted_abs_return * 100.0, 3),
        "probability_interval_95": {
            "low": round(lo * 100.0, 1),
            "high": round(hi * 100.0, 1),
        },
        "sample_size": len(usable),
        "neighbors_used": k,
        "effective_sample_size": round(effective_n, 1),
        "average_analog_distance": round(float(np.mean(selected_distances)), 4),
        "evidence_quality": round(max(0.0, min(100.0, evidence_quality)), 1),
        "method": "historical_same_session_nearest_analogs_with_shrinkage",
    }


def estimate_intraday_probabilities(
    symbol: str,
    *,
    period: str = "60d",
    interval: str = "5m",
    neighbor_count: int = 180,
    min_samples: int = 80,
) -> Dict[str, Any]:
    """Estimate P(up)/P(down) for 30m, 1h, 3h and 5h.

    The model uses 5-minute regular-session data and historical analog states.
    Targets never cross the 16:00 ET session boundary, preventing overnight
    returns from contaminating the requested intraday horizons.
    """

    ticker = str(symbol or "").strip().upper()
    if not ticker:
        raise ValueError("symbol is required")

    warnings: List[str] = []

    try:
        import yfinance as yf
    except Exception as exc:
        return {
            "symbol": ticker,
            "available": False,
            "horizons": {},
            "warnings": [f"yfinance import failed: {type(exc).__name__}"],
            "semantics": SEMANTICS,
        }

    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        return {
            "symbol": ticker,
            "available": False,
            "horizons": {},
            "warnings": [f"Historical intraday data request failed: {type(exc).__name__}"],
            "semantics": SEMANTICS,
        }

    frame = _normalize_ohlcv(raw)

    if len(frame) < 100:
        return {
            "symbol": ticker,
            "available": False,
            "bar_count": len(frame),
            "horizons": {},
            "warnings": ["Insufficient regular-session 5-minute history."],
            "semantics": SEMANTICS,
        }

    dataset = _attach_targets(_build_features(frame))

    current_candidates = dataset.dropna(subset=FEATURE_COLUMNS)
    if current_candidates.empty:
        return {
            "symbol": ticker,
            "available": False,
            "bar_count": len(frame),
            "horizons": {},
            "warnings": ["Current feature vector is incomplete."],
            "semantics": SEMANTICS,
        }

    current = current_candidates.iloc[-1]
    current_timestamp = current.name

    # Historical analogs must be strictly earlier than the current observation.
    history = dataset.loc[dataset.index < current_timestamp].copy()

    results = {}

    local_current = pd.Timestamp(current_timestamp).tz_convert(NEW_YORK)
    close_minutes = 16 * 60
    current_minutes = local_current.hour * 60 + local_current.minute
    minutes_remaining = max(0, close_minutes - current_minutes)

    for label in HORIZONS:
        required_minutes = HORIZON_MINUTES[label]

        if minutes_remaining < required_minutes:
            results[label] = {
                "available": False,
                "horizon": label,
                "probability_up": None,
                "probability_down": None,
                "sample_size": 0,
                "reason": (
                    f"Only {minutes_remaining} regular-session minutes remain; "
                    f"{required_minutes} are required for a same-session {label} forecast."
                ),
                "current_session_feasible": False,
            }
            continue

        results[label] = _estimate_one_horizon(
            history,
            current,
            label,
            neighbor_count=neighbor_count,
            min_samples=min_samples,
        )
        results[label]["current_session_feasible"] = True

    available_results = [
        item for item in results.values() if item.get("available")
    ]

    if not available_results:
        warnings.append(
            "No requested horizon had enough resolved historical analog samples."
        )

    # A simple cross-horizon consensus diagnostic, not another probability.
    bullish = sum(
        1 for item in available_results if item.get("direction") == "bullish"
    )
    bearish = sum(
        1 for item in available_results if item.get("direction") == "bearish"
    )

    if bullish > bearish:
        consensus = "bullish"
    elif bearish > bullish:
        consensus = "bearish"
    else:
        consensus = "mixed_or_neutral"

    return {
        "symbol": ticker,
        "available": bool(available_results),
        "as_of": pd.Timestamp(current_timestamp).isoformat(),
        "bar_interval": interval,
        "history_period": period,
        "bar_count": len(frame),
        "feature_count": len(FEATURE_COLUMNS),
        "regular_session_minutes_remaining": minutes_remaining,
        "horizons": results,
        "cross_horizon_consensus": consensus,
        "warnings": warnings,
        "limitations": [
            "Probabilities are empirical estimates from historical analogs, not guarantees.",
            "A 60-day 5-minute history is a limited sample and should be validated walk-forward before being treated as production-calibrated.",
            "The model uses regular-session data only and does not let targets cross the 16:00 ET boundary.",
            "Market regime, sector regime and news are not yet included in the analog feature vector.",
        ],
        "semantics": SEMANTICS,
    }


def _synthetic_self_test() -> Dict[str, Any]:
    rng = np.random.default_rng(42)
    sessions = []

    start = pd.Timestamp("2026-05-01", tz=NEW_YORK)
    business_days = pd.bdate_range(start.date(), periods=55)

    price = 100.0

    for day_index, day in enumerate(business_days):
        index = pd.date_range(
            pd.Timestamp(day.date(), tz=NEW_YORK) + pd.Timedelta(hours=9, minutes=30),
            periods=78,
            freq="5min",
        )

        # Alternate regimes while preserving some momentum persistence.
        regime = 0.00035 if (day_index % 4 in {0, 1}) else -0.00020
        shock = rng.normal(0.0, 0.0015, len(index))
        returns = regime + 0.30 * np.r_[0.0, shock[:-1]] + shock
        close = price * np.cumprod(1.0 + returns)
        open_ = np.r_[price, close[:-1]]
        spread = np.abs(rng.normal(0.0010, 0.0004, len(index)))
        high = np.maximum(open_, close) * (1.0 + spread)
        low = np.minimum(open_, close) * (1.0 - spread)
        volume = rng.integers(500_000, 2_000_000, len(index))

        sessions.append(
            pd.DataFrame(
                {
                    "Open": open_,
                    "High": high,
                    "Low": low,
                    "Close": close,
                    "Volume": volume,
                },
                index=index,
            )
        )
        price = float(close[-1])

    frame = pd.concat(sessions)
    dataset = _attach_targets(_build_features(frame))
    current = dataset.dropna(subset=FEATURE_COLUMNS).iloc[-70]  # around 10:10 ET
    current_timestamp = current.name
    history = dataset.loc[dataset.index < current_timestamp].copy()

    results = {}
    for label in HORIZONS:
        results[label] = _estimate_one_horizon(
            history,
            current,
            label,
            neighbor_count=180,
            min_samples=80,
        )

    return {
        "self_test": True,
        "symbol": "SYNTHETIC",
        "as_of": pd.Timestamp(current_timestamp).isoformat(),
        "horizons": results,
        "semantics": SEMANTICS,
    }


if __name__ == "__main__":
    import json
    import sys

    if "--self-test" in sys.argv:
        output = _synthetic_self_test()
    else:
        ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "NVDA"
        output = estimate_intraday_probabilities(ticker)

    print(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
