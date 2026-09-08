"""Point-in-time price/volume replay for the Explosive-Move research lab.

Features are computed only from bars at or before each decision close. Forward
bars are isolated in a separate outcome window. The resulting frequencies are
descriptive historical observations, never calibrated probabilities.
"""

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd


THRESHOLDS = (20, 50, 100)
SCORE_BANDS = ((0, 24), (25, 49), (50, 74), (75, 100))


def _finite(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _round(value, digits=3):
    number = _finite(value)
    return round(number, digits) if number is not None else None


def _frame(value):
    if not isinstance(value, pd.DataFrame) or value.empty:
        return pd.DataFrame()
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(value.columns):
        return pd.DataFrame()
    result = value.copy()
    result.index = pd.to_datetime(result.index, utc=True, errors="coerce")
    result = result[~result.index.isna()].sort_index()
    result = result[~result.index.duplicated(keep="last")]
    for column in ("Open", "High", "Low", "Close", "Volume"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["High", "Low", "Close", "Volume"]
    )


def _true_range(frame):
    previous = frame["Close"].shift(1)
    return pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous).abs(),
            (frame["Low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _return(series, sessions):
    if len(series) <= sessions:
        return None
    current = _finite(series.iloc[-1])
    prior = _finite(series.iloc[-sessions - 1])
    if current is None or prior in (None, 0):
        return None
    return (current / prior - 1) * 100


def _factor(factor_id, label, maximum, points, available, detail):
    awarded = int(max(0, min(maximum, round(points)))) if available else 0
    return {
        "id": factor_id,
        "label": label,
        "points": awarded,
        "max_points": int(maximum),
        "available": bool(available),
        "matched": bool(available and awarded > 0),
        "detail": detail,
        "source": "Point-in-time daily OHLCV",
    }


def build_replay_preparation_score(asset_history, benchmark_history=None):
    """Build a historical-only preparation score ending at the decision bar."""
    asset = _frame(asset_history)
    benchmark = _frame(benchmark_history)
    if len(asset) < 60:
        raise ValueError("Replay preparation requires at least 60 prior daily bars")

    close = asset["Close"]
    factors = []
    metrics = {}

    recent_volume = _finite(asset["Volume"].tail(5).mean())
    prior_volume = _finite(asset["Volume"].iloc[-25:-5].mean())
    volume_ratio = recent_volume / prior_volume if prior_volume else None
    volume_points = (
        20 if volume_ratio is not None and volume_ratio >= 1.5
        else 15 if volume_ratio is not None and volume_ratio >= 1.2
        else 8 if volume_ratio is not None and volume_ratio >= 1.0
        else 0
    )
    factors.append(_factor(
        "volume_accumulation", "Five-session volume versus prior 20", 20,
        volume_points, volume_ratio is not None,
        f"Recent volume was {volume_ratio:.2f}x the preceding 20-session average."
        if volume_ratio is not None else "Comparable historical volume was unavailable.",
    ))

    true_range = _true_range(asset)
    atr5 = _finite(true_range.tail(5).mean())
    atr20_prior = _finite(true_range.iloc[-25:-5].mean())
    atr_ratio = atr5 / atr20_prior if atr20_prior else None
    rolling_range = (
        asset["High"].rolling(10).max() - asset["Low"].rolling(10).min()
    ) / close * 100
    range_now = _finite(rolling_range.iloc[-1])
    range_prior = _finite(rolling_range.iloc[-50:-10].median())
    range_ratio = range_now / range_prior if range_prior else None
    compression_available = atr_ratio is not None and range_ratio is not None
    compression_points = 0
    if compression_available:
        compression_points += 12 if atr_ratio <= 0.75 else 8 if atr_ratio <= 0.9 else 0
        compression_points += 8 if range_ratio <= 0.75 else 5 if range_ratio <= 0.9 else 0
    factors.append(_factor(
        "volatility_compression", "ATR and trading-range contraction", 20,
        compression_points, compression_available,
        f"ATR ratio {atr_ratio:.2f}; 10-session range ratio {range_ratio:.2f}."
        if compression_available else "Comparable historical contraction windows were unavailable.",
    ))

    current = _finite(close.iloc[-1])
    ema20 = _finite(close.ewm(span=20, adjust=False).mean().iloc[-1])
    sma50_series = close.rolling(50).mean()
    sma50 = _finite(sma50_series.iloc[-1])
    sma50_prior = _finite(sma50_series.iloc[-11])
    trend_available = all(value is not None for value in (current, ema20, sma50, sma50_prior))
    trend_points = 0
    if trend_available:
        trend_points += 7 if current > sma50 else 0
        trend_points += 7 if ema20 > sma50 else 0
        trend_points += 6 if sma50 > sma50_prior else 0
    factors.append(_factor(
        "trend_alignment", "Price, EMA20 and rising SMA50", 20,
        trend_points, trend_available,
        f"Close {current:.2f}; EMA20 {ema20:.2f}; SMA50 {sma50:.2f}; prior SMA50 {sma50_prior:.2f}."
        if trend_available else "Historical moving-average alignment was unavailable.",
    ))

    prior_high20 = _finite(asset["High"].iloc[-21:-1].max())
    distance = (
        (prior_high20 - current) / current * 100
        if current not in (None, 0) and prior_high20 is not None else None
    )
    base_range_percent = (
        (asset["High"].tail(10).max() - asset["Low"].tail(10).min()) / current * 100
        if current not in (None, 0) else None
    )
    structure_available = distance is not None and base_range_percent is not None
    structure_points = 0
    if structure_available:
        structure_points += 12 if 0 <= distance <= 3 else 8 if -2 <= distance <= 6 else 0
        structure_points += 8 if base_range_percent <= 8 else 4 if base_range_percent <= 12 else 0
    factors.append(_factor(
        "base_and_resistance", "Base tightness and prior-high proximity", 20,
        structure_points, structure_available,
        f"Close was {distance:.2f}% below the prior 20-session high; 10-session range was {base_range_percent:.2f}%."
        if structure_available else "Historical base/resistance structure was unavailable.",
    ))

    relative20 = relative5 = None
    if not benchmark.empty:
        aligned = pd.concat(
            [close.rename("asset"), benchmark["Close"].rename("benchmark")],
            axis=1, join="inner",
        ).dropna()
        if len(aligned) >= 22:
            asset20, benchmark20 = _return(aligned["asset"], 20), _return(aligned["benchmark"], 20)
            asset5, benchmark5 = _return(aligned["asset"], 5), _return(aligned["benchmark"], 5)
            if None not in (asset20, benchmark20):
                relative20 = asset20 - benchmark20
            if None not in (asset5, benchmark5):
                relative5 = asset5 - benchmark5
    relative_available = relative20 is not None and relative5 is not None
    relative_points = 0
    if relative_available:
        relative_points += 12 if relative20 >= 10 else 8 if relative20 >= 3 else 0
        relative_points += 8 if relative5 >= 3 else 5 if relative5 > 0 else 0
    factors.append(_factor(
        "relative_strength", "Relative strength versus SPY", 20,
        relative_points, relative_available,
        f"20-session excess return {relative20:.2f}%; five-session excess return {relative5:.2f}%."
        if relative_available else "Aligned point-in-time benchmark history was unavailable.",
    ))

    score = sum(item["points"] for item in factors)
    available_points = sum(item["max_points"] for item in factors if item["available"])
    metrics.update(
        volume_ratio=_round(volume_ratio), atr_contraction_ratio=_round(atr_ratio),
        range_contraction_ratio=_round(range_ratio), distance_to_20_day_high_percent=_round(distance),
        base_range_percent=_round(base_range_percent), relative_strength_20d=_round(relative20),
        relative_strength_5d=_round(relative5), close=_round(current, 4),
    )
    return {
        "score": int(score),
        "maximum_score": 100,
        "evidence_coverage_percent": round(available_points, 2),
        "factors": factors,
        "metrics": metrics,
        "score_meaning": "Historical rule points from information available at the decision close; not the live PreMoveScore and not a calibrated probability.",
    }


def _outcome(anchor_close, forward):
    maximum_high = _finite(forward["High"].max())
    minimum_low = _finite(forward["Low"].min())
    final_close = _finite(forward["Close"].iloc[-1])
    gains = (forward["High"] / anchor_close - 1) * 100
    losses = (forward["Low"] / anchor_close - 1) * 100
    hits = {}
    for threshold in THRESHOLDS:
        qualifying = gains[gains >= threshold]
        hits[str(threshold)] = {
            "hit": not qualifying.empty,
            "sessions_to_hit": (
                int(forward.index.get_loc(qualifying.index[0])) + 1
                if not qualifying.empty else None
            ),
        }
    highest = max((value for value in THRESHOLDS if hits[str(value)]["hit"]), default=0)
    peak_index = gains.idxmax()
    trough_index = losses.idxmin()
    return {
        "maximum_gain_percent": _round((maximum_high / anchor_close - 1) * 100),
        "maximum_drawdown_percent": _round((minimum_low / anchor_close - 1) * 100),
        "ending_return_percent": _round((final_close / anchor_close - 1) * 100),
        "highest_threshold_hit": highest,
        "threshold_hits": hits,
        "sessions_to_peak": int(forward.index.get_loc(peak_index)) + 1,
        "sessions_to_trough": int(forward.index.get_loc(trough_index)) + 1,
        "peak_date": peak_index.isoformat(),
        "trough_date": trough_index.isoformat(),
        "path": [
            {
                "session": index + 1,
                "date": timestamp.isoformat(),
                "high_return_percent": _round((row["High"] / anchor_close - 1) * 100),
                "low_return_percent": _round((row["Low"] / anchor_close - 1) * 100),
                "close_return_percent": _round((row["Close"] / anchor_close - 1) * 100),
            }
            for index, (timestamp, row) in enumerate(forward.iterrows())
        ],
    }


def _metrics(rows, minimum_score):
    flagged = [row for row in rows if row["preparation_score"]["score"] >= minimum_score]
    hits20 = [row for row in rows if row["outcome"]["threshold_hits"]["20"]["hit"]]
    flagged_hits = [row for row in flagged if row["outcome"]["threshold_hits"]["20"]["hit"]]
    missed = [row for row in hits20 if row["preparation_score"]["score"] < minimum_score]
    return {
        "observations": len(rows),
        "flagged_observations": len(flagged),
        "twenty_percent_outcomes": len(hits20),
        "flagged_twenty_percent_outcomes": len(flagged_hits),
        "false_positive_observations": len(flagged) - len(flagged_hits),
        "missed_twenty_percent_outcomes": len(missed),
        "flagged_hit_frequency_percent": _round(len(flagged_hits) / len(flagged) * 100, 2) if flagged else None,
        "extreme_outcome_capture_percent": _round(len(flagged_hits) / len(hits20) * 100, 2) if hits20 else None,
    }


def _score_bands(rows):
    result = []
    for lower, upper in SCORE_BANDS:
        selected = [row for row in rows if lower <= row["preparation_score"]["score"] <= upper]
        gains = [row["outcome"]["maximum_gain_percent"] for row in selected]
        drawdowns = [row["outcome"]["maximum_drawdown_percent"] for row in selected]
        result.append({
            "label": f"{lower}-{upper}",
            "minimum_score": lower,
            "maximum_score": upper,
            "observations": len(selected),
            "hit_counts": {
                str(threshold): sum(row["outcome"]["threshold_hits"][str(threshold)]["hit"] for row in selected)
                for threshold in THRESHOLDS
            },
            "descriptive_hit_frequencies_percent": {
                str(threshold): _round(
                    sum(row["outcome"]["threshold_hits"][str(threshold)]["hit"] for row in selected)
                    / len(selected) * 100, 2,
                ) if selected else None
                for threshold in THRESHOLDS
            },
            "median_maximum_gain_percent": _round(np.median(gains), 2) if gains else None,
            "median_maximum_drawdown_percent": _round(np.median(drawdowns), 2) if drawdowns else None,
        })
    return result


def _non_overlapping_examples(rows, forward_sessions, limit=12):
    candidates = [row for row in rows if row["outcome"]["highest_threshold_hit"] >= 20]
    selected = []
    for row in sorted(candidates, key=lambda item: item["outcome"]["maximum_gain_percent"], reverse=True):
        if all(abs(row["_anchor_index"] - item["_anchor_index"]) >= forward_sessions for item in selected):
            selected.append(row)
        if len(selected) >= limit:
            break
    return [_public_row(row, include_path=True) for row in selected]


def _public_row(row, include_path=False):
    public = {key: value for key, value in row.items() if not key.startswith("_")}
    if not include_path and "outcome" in public:
        public["outcome"] = dict(public["outcome"])
        public["outcome"].pop("path", None)
    return public


def run_extreme_move_replay(
    symbol,
    history,
    benchmark_history=None,
    *,
    forward_sessions=20,
    stride_sessions=5,
    minimum_score=60,
    period="5y",
):
    asset = _frame(history)
    benchmark = _frame(benchmark_history)
    forward_sessions = max(5, min(int(forward_sessions), 60))
    stride_sessions = max(5, min(int(stride_sessions), 20))
    minimum_score = max(0, min(int(minimum_score), 100))
    required = 60 + forward_sessions + 1
    if len(asset) < required:
        raise ValueError(
            f"Replay requires at least {required} usable daily bars; provider returned {len(asset)}"
        )

    observations = []
    for anchor_index in range(59, len(asset) - forward_sessions, stride_sessions):
        anchor_time = asset.index[anchor_index]
        history_window = asset.iloc[:anchor_index + 1]
        benchmark_window = benchmark[benchmark.index <= anchor_time] if not benchmark.empty else benchmark
        forward = asset.iloc[anchor_index + 1:anchor_index + 1 + forward_sessions]
        anchor_close = _finite(asset["Close"].iloc[anchor_index])
        if anchor_close in (None, 0) or len(forward) < forward_sessions:
            continue
        observations.append({
            "_anchor_index": anchor_index,
            "anchor_date": anchor_time.isoformat(),
            "anchor_close": _round(anchor_close, 4),
            "anchor_average_daily_volume_20": _round(
                history_window["Volume"].tail(20).mean(), 2
            ),
            "feature_window_end": anchor_time.isoformat(),
            "outcome_window_start": forward.index[0].isoformat(),
            "outcome_window_end": forward.index[-1].isoformat(),
            "preparation_score": build_replay_preparation_score(history_window, benchmark_window),
            "outcome": _outcome(anchor_close, forward),
        })
    if not observations:
        raise ValueError("No complete replay observations were available")

    split_index = max(1, int(len(observations) * 0.7))
    development, holdout = observations[:split_index], observations[split_index:]
    threshold_counts = {
        str(threshold): sum(row["outcome"]["threshold_hits"][str(threshold)]["hit"] for row in observations)
        for threshold in THRESHOLDS
    }
    false_positives = sorted(
        [row for row in observations if row["preparation_score"]["score"] >= minimum_score and row["outcome"]["highest_threshold_hit"] < 20],
        key=lambda item: (item["preparation_score"]["score"], -item["outcome"]["maximum_gain_percent"]),
        reverse=True,
    )[:8]
    missed = sorted(
        [row for row in observations if row["preparation_score"]["score"] < minimum_score and row["outcome"]["highest_threshold_hit"] >= 20],
        key=lambda item: item["outcome"]["maximum_gain_percent"],
        reverse=True,
    )[:8]

    public_observations = [_public_row(row) for row in observations]
    return {
        "version": "extreme-replay-v1",
        "symbol": str(symbol).strip().upper(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "period": period,
            "forward_sessions": forward_sessions,
            "stride_sessions": stride_sessions,
            "minimum_score": minimum_score,
            "thresholds_percent": list(THRESHOLDS),
        },
        "sample": {
            "first_feature_date": observations[0]["anchor_date"],
            "last_feature_date": observations[-1]["anchor_date"],
            "usable_daily_bars": len(asset),
            "observations": len(observations),
            "overlapping_outcomes": stride_sessions < forward_sessions,
            "observations_are_independent": False,
        },
        "summary": {
            **_metrics(observations, minimum_score),
            "threshold_hit_counts": threshold_counts,
            "highest_observed_gain_percent": max(row["outcome"]["maximum_gain_percent"] for row in observations),
            "worst_observed_drawdown_percent": min(row["outcome"]["maximum_drawdown_percent"] for row in observations),
        },
        "score_bands": _score_bands(observations),
        "date_split": {
            "method": "Chronological 70/30 descriptive split; the fixed rules are not fitted on either segment.",
            "development": _metrics(development, minimum_score),
            "holdout": _metrics(holdout, minimum_score),
            "split_anchor_date": holdout[0]["anchor_date"] if holdout else None,
        },
        "extreme_examples": _non_overlapping_examples(observations, forward_sessions),
        "false_positive_examples": [_public_row(row, include_path=True) for row in false_positives],
        "missed_extreme_examples": [_public_row(row, include_path=True) for row in missed],
        "observations": public_observations,
        "leakage_controls": {
            "feature_cutoff": "Every feature window ends at the displayed decision close.",
            "future_isolation": "Thresholds and drawdowns use only the following outcome window and never feed the score.",
            "current_profile_excluded": True,
            "current_news_excluded": True,
            "current_fundamentals_excluded": True,
        },
        "limitations": [
            "The free provider history is not a point-in-time security master and may omit delisted or failed securities, creating survivorship bias.",
            "Provider back-adjustments can apply later split or corporate-action normalization to earlier bars; the feature cutoff prevents future rows, not every form of vendor restatement.",
            "Historical news, filings, float, short interest, spreads, halts, LULD events, bid/ask depth and executable fills are not included.",
            "Provider-adjusted daily OHLCV cannot reproduce intraday event order or prove that the displayed high was executable.",
            "Stride windows can overlap, so observations and descriptive frequencies are not statistically independent.",
            "This single-symbol replay is diagnostic research, not a calibrated forecast, expected return or trading instruction.",
        ],
        "probability_model": {
            "status": "not_calibrated",
            "probabilities": None,
            "message": "Historical frequencies are descriptive only and must not be presented as future probabilities.",
        },
        "safety_boundary": "Research replay only. No order preparation, confirmation or submission path is connected.",
    }
