from __future__ import annotations

from math import isfinite
from typing import Any, Dict, Optional

import pandas as pd


SEMANTICS = (
    "Heuristic market-integrity / anomalous-price-action score. "
    "It does not prove manipulation, identify intent, or establish illegal conduct."
)


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _zscore(value: float, series: pd.Series) -> Optional[float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < 10:
        return None

    mean = float(clean.mean())
    std = float(clean.std(ddof=0))

    if std <= 1e-12:
        return None

    return (float(value) - mean) / std


def _session_vwap(frame: pd.DataFrame) -> Optional[float]:
    if frame.empty:
        return None

    volume = pd.to_numeric(frame["Volume"], errors="coerce").fillna(0.0)
    total = float(volume.sum())

    if total <= 0:
        return None

    typical = (
        pd.to_numeric(frame["High"], errors="coerce")
        + pd.to_numeric(frame["Low"], errors="coerce")
        + pd.to_numeric(frame["Close"], errors="coerce")
    ) / 3.0

    return float((typical * volume).sum() / total)


def _coerce_history(history: Any) -> Optional[pd.DataFrame]:
    if not isinstance(history, pd.DataFrame) or history.empty:
        return None

    frame = history.copy()

    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(column not in frame.columns for column in required):
        return None

    frame[required] = frame[required].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=required)

    if frame.empty:
        return None

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, errors="coerce")

    frame = frame[~frame.index.isna()].sort_index()

    if frame.empty:
        return None

    if (
        (frame[["Open", "High", "Low", "Close"]] <= 0).any().any()
        or (frame["Volume"] < 0).any()
    ):
        return None

    return frame


def analyze_market_integrity(
    ticker: str,
    history: Any,
    *,
    bid: Any = None,
    ask: Any = None,
    spread_pct: Any = None,
    float_shares: Any = None,
    news_score: Any = None,
    market_return_pct: Any = None,
    benchmark_return_pct: Any = None,
    sector_return_pct: Any = None,
    average_dollar_volume: Any = None,
    relative_volume: Any = None,
    now: Any = None,
) -> Dict[str, Any]:
    """Estimate anomalous market behavior from available public market data.

    V1 deliberately avoids calling this "manipulation detected". It measures:
      - abnormal return
      - abnormal volume
      - candle rejection / wick behavior
      - short-term reversal behavior
      - VWAP extension
      - liquidity weakness
      - spread deterioration
      - low-float susceptibility when float is supplied
      - catalyst mismatch when news score is supplied
      - market/sector decoupling when supplied

    It does not have Level 2/order-cancellation data, so spoofing/layering cannot
    be reliably detected here.
    """
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise ValueError("ticker is required")

    frame = _coerce_history(history)
    if frame is None or len(frame) < 12:
        return {
            "ticker": symbol,
            "available": False,
            "manipulation_risk_score": None,
            "market_integrity_risk": None,
            "market_integrity_score": None,
            "distortion_direction": "unknown",
            "directional_distortion_score": None,
            "reason": "At least 12 valid OHLCV bars are required.",
            "missing": ["sufficient_ohlcv_history"],
            "semantics": SEMANTICS,
        }

    close = frame["Close"].astype(float)
    open_ = frame["Open"].astype(float)
    high = frame["High"].astype(float)
    low = frame["Low"].astype(float)
    volume = frame["Volume"].astype(float)

    returns = close.pct_change().dropna()
    current_return = float(returns.iloc[-1])
    return_z = _zscore(current_return, returns.iloc[:-1])

    current_volume = float(volume.iloc[-1])
    volume_z = _zscore(current_volume, volume.iloc[:-1])

    # Dollar-volume liquidity.
    dollar_volume = close * volume
    recent_dollar_volume = float(dollar_volume.tail(min(20, len(dollar_volume))).mean())

    # Candle wick/rejection anomaly.
    candle_range = (high - low).replace(0, pd.NA)
    body = (close - open_).abs()
    upper_wick = high - pd.concat([open_, close], axis=1).max(axis=1)
    lower_wick = pd.concat([open_, close], axis=1).min(axis=1) - low

    wick_ratio = ((upper_wick + lower_wick) / candle_range).astype(float)
    latest_wick_ratio = _finite(wick_ratio.iloc[-1]) or 0.0
    wick_z = _zscore(latest_wick_ratio, wick_ratio.iloc[:-1])

    # Reversal intensity: latest return versus immediately preceding impulse.
    lookback = returns.tail(min(6, len(returns)))
    prior_impulse = float(lookback.iloc[:-1].sum()) if len(lookback) > 1 else 0.0

    reversal_strength = 0.0
    if prior_impulse != 0 and current_return * prior_impulse < 0:
        reversal_strength = min(
            abs(current_return) / max(abs(prior_impulse), 1e-9),
            2.0,
        )

    # Use latest date/session if intraday index is available; otherwise trailing bars.
    if isinstance(frame.index, pd.DatetimeIndex) and len(frame):
        last_date = frame.index[-1].date()
        session = frame[frame.index.date == last_date]
        if len(session) < 3:
            session = frame.tail(min(50, len(frame)))
    else:
        session = frame.tail(min(50, len(frame)))

    vwap = _session_vwap(session)
    last_price = float(close.iloc[-1])
    vwap_extension_pct = (
        (last_price / vwap - 1.0) * 100.0
        if vwap and vwap > 0
        else None
    )

    # Spread, if quote fields are available. A precomputed spread_pct is also
    # accepted for compatibility with adapters that already calculated it.
    bid_value = _finite(bid)
    ask_value = _finite(ask)
    supplied_spread_pct = _finite(spread_pct)
    computed_spread_pct = supplied_spread_pct

    if (
        computed_spread_pct is None
        and bid_value is not None
        and ask_value is not None
        and bid_value > 0
        and ask_value >= bid_value
    ):
        mid = (bid_value + ask_value) / 2.0
        if mid > 0:
            computed_spread_pct = (ask_value - bid_value) / mid * 100.0

    spread_pct = computed_spread_pct

    # Optional completed-session / average-dollar-volume baseline may be a
    # better liquidity input than the short recent-bar sample.
    supplied_average_dollar_volume = _finite(average_dollar_volume)
    if supplied_average_dollar_volume is not None and supplied_average_dollar_volume > 0:
        recent_dollar_volume = supplied_average_dollar_volume

    float_value = _finite(float_shares)
    news = _finite(news_score)

    # benchmark_return_pct is an explicit alias used by the single-ticker service.
    market_ret = _finite(
        market_return_pct
        if market_return_pct is not None
        else benchmark_return_pct
    )
    sector_ret = _finite(sector_return_pct)

    components = {}
    reasons = []
    warnings = []

    # 1) Abnormal return.
    if return_z is not None:
        score = _clamp(abs(return_z) / 4.0 * 100.0)
        components["abnormal_return"] = round(score, 2)
        if abs(return_z) >= 2.5:
            reasons.append(f"Latest return is {return_z:+.2f} standard deviations from recent bars.")
    else:
        warnings.append("Return anomaly z-score unavailable.")

    # 2) Abnormal volume.
    if volume_z is not None:
        score = _clamp(abs(volume_z) / 5.0 * 100.0)
        components["abnormal_volume"] = round(score, 2)
        if volume_z >= 2.5:
            reasons.append(f"Latest volume is {volume_z:+.2f} standard deviations above recent bars.")
    else:
        warnings.append("Volume anomaly z-score unavailable.")

    # 3) Wick / rejection anomaly.
    if wick_z is not None:
        score = _clamp(max(0.0, wick_z) / 3.0 * 100.0)
        components["wick_rejection"] = round(score, 2)
        if wick_z >= 1.5:
            reasons.append("Latest candle has unusually large rejection wicks.")
    else:
        components["wick_rejection"] = round(_clamp(latest_wick_ratio * 100.0), 2)

    # 4) Reversal / pump-dump style instability.
    reversal_score = _clamp(reversal_strength / 1.0 * 100.0)
    components["reversal_instability"] = round(reversal_score, 2)
    if reversal_score >= 60:
        reasons.append("Latest bar strongly reverses the immediately preceding price impulse.")

    # 5) VWAP extension.
    if vwap_extension_pct is not None:
        vwap_score = _clamp(abs(vwap_extension_pct) / 5.0 * 100.0)
        components["vwap_extension"] = round(vwap_score, 2)
        if abs(vwap_extension_pct) >= 3.0:
            reasons.append(f"Price is {vwap_extension_pct:+.2f}% away from session VWAP.")
    else:
        warnings.append("Session VWAP unavailable.")

    # 6) Weak liquidity increases susceptibility.
    if recent_dollar_volume >= 50_000_000:
        liquidity_risk = 5.0
    elif recent_dollar_volume >= 20_000_000:
        liquidity_risk = 15.0
    elif recent_dollar_volume >= 10_000_000:
        liquidity_risk = 30.0
    elif recent_dollar_volume >= 5_000_000:
        liquidity_risk = 50.0
    elif recent_dollar_volume >= 1_000_000:
        liquidity_risk = 70.0
    else:
        liquidity_risk = 90.0

    components["liquidity_susceptibility"] = liquidity_risk
    if liquidity_risk >= 70:
        reasons.append("Recent dollar volume is low enough to make price easier to move.")

    # 7) Spread risk.
    if spread_pct is not None:
        spread_risk = _clamp(spread_pct / 1.0 * 100.0)
        components["spread_anomaly"] = round(spread_risk, 2)
        if spread_pct >= 0.5:
            reasons.append(f"Bid/ask spread is wide at approximately {spread_pct:.2f}%.")
    else:
        warnings.append("Bid/ask spread unavailable; spread anomaly excluded.")

    # 8) Low-float susceptibility.
    if float_value is not None and float_value > 0:
        if float_value < 5_000_000:
            float_risk = 100.0
        elif float_value < 10_000_000:
            float_risk = 85.0
        elif float_value < 20_000_000:
            float_risk = 65.0
        elif float_value < 50_000_000:
            float_risk = 40.0
        else:
            float_risk = 10.0

        components["low_float_susceptibility"] = float_risk
        if float_risk >= 65:
            reasons.append("Low public float increases susceptibility to sharp price displacement.")
    else:
        warnings.append("Float unavailable; low-float susceptibility excluded.")

    # 9) Catalyst mismatch. Strong move without supportive news = more anomalous.
    if news is not None and return_z is not None:
        move_sign = 1.0 if current_return > 0 else -1.0 if current_return < 0 else 0.0
        aligned_news = move_sign * max(-1.0, min(1.0, news))
        mismatch = _clamp((1.0 - aligned_news) * 50.0)
        if abs(return_z) < 1.5:
            mismatch *= 0.4
        components["catalyst_mismatch"] = round(mismatch, 2)
        if mismatch >= 65:
            reasons.append("Price move is large relative to the available directional news signal.")
    else:
        warnings.append("Catalyst mismatch unavailable because news score or return anomaly is missing.")

    # 10) Market / sector decoupling.
    context_values = [v for v in (market_ret, sector_ret) if v is not None]
    if context_values:
        context_return = sum(context_values) / len(context_values)
        latest_return_pct = current_return * 100.0
        decoupling = abs(latest_return_pct - context_return)
        context_score = _clamp(decoupling / 3.0 * 100.0)
        components["market_sector_decoupling"] = round(context_score, 2)
        if context_score >= 65:
            reasons.append("Stock move is unusually decoupled from available market/sector context.")
    else:
        warnings.append("Market/sector decoupling unavailable.")

    weights = {
        "abnormal_return": 0.18,
        "abnormal_volume": 0.16,
        "wick_rejection": 0.10,
        "reversal_instability": 0.10,
        "vwap_extension": 0.10,
        "liquidity_susceptibility": 0.14,
        "spread_anomaly": 0.08,
        "low_float_susceptibility": 0.06,
        "catalyst_mismatch": 0.05,
        "market_sector_decoupling": 0.03,
    }

    active_weight = sum(
        weight
        for name, weight in weights.items()
        if name in components
    )

    risk = (
        sum(components[name] * weight for name, weight in weights.items() if name in components)
        / active_weight
        if active_weight > 0
        else 0.0
    )

    risk = round(_clamp(risk), 1)
    integrity = round(100.0 - risk, 1)

    # Directional distortion is deliberately separate from risk.
    # Positive = upward distortion risk, negative = downward distortion risk.
    direction_basis = 0.0
    if return_z is not None:
        direction_basis += max(-1.0, min(1.0, return_z / 3.0)) * 0.50
    if vwap_extension_pct is not None:
        direction_basis += max(-1.0, min(1.0, vwap_extension_pct / 4.0)) * 0.30
    if prior_impulse != 0:
        direction_basis += max(-1.0, min(1.0, prior_impulse / 0.05)) * 0.20

    distortion = max(-1.0, min(1.0, direction_basis * (risk / 100.0)))

    if distortion >= 0.15:
        distortion_direction = "upward"
    elif distortion <= -0.15:
        distortion_direction = "downward"
    else:
        distortion_direction = "mixed_or_neutral"

    if risk >= 75:
        state = "extreme_anomaly"
    elif risk >= 60:
        state = "high_anomaly"
    elif risk >= 45:
        state = "elevated_anomaly"
    elif risk >= 25:
        state = "mild_anomaly"
    else:
        state = "normal"

    missing = []
    if spread_pct is None:
        missing.append("spread")
    if float_value is None:
        missing.append("float_shares")
    if news is None:
        missing.append("news_score")
    if not context_values:
        missing.append("market_or_sector_return")

    return {
        "ticker": symbol,
        "available": True,
        "manipulation_risk_score": risk,
        "market_integrity_risk": risk,
        "market_integrity_score": integrity,
        "state": state,
        "distortion_direction": distortion_direction,
        "directional_distortion_score": round(distortion, 3),
        "directional_distortion": round(distortion, 3),
        "latest_return_pct": round(current_return * 100.0, 4),
        "return_zscore": round(return_z, 3) if return_z is not None else None,
        "volume_zscore": round(volume_z, 3) if volume_z is not None else None,
        "session_vwap": round(vwap, 6) if vwap is not None else None,
        "vwap_extension_pct": round(vwap_extension_pct, 4) if vwap_extension_pct is not None else None,
        "recent_average_dollar_volume": round(recent_dollar_volume, 2),
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "float_shares": round(float_value, 0) if float_value is not None else None,
        "components": components,
        "reasons": reasons,
        "warnings": list(dict.fromkeys(warnings)),
        "missing": missing,
        "level2_analysis_available": False,
        "spoofing_or_layering_detection_available": False,
        "semantics": SEMANTICS,
    }


if __name__ == "__main__":
    import json

    index = pd.date_range(
        "2026-09-04 09:30",
        periods=40,
        freq="5min",
        tz="America/New_York",
    )

    opens = [10 + i * 0.01 for i in range(40)]
    closes = [x + 0.02 for x in opens]
    highs = [max(o, c) + 0.03 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.03 for o, c in zip(opens, closes)]
    volumes = [100000 + i * 1000 for i in range(40)]

    # Make the final bar intentionally anomalous.
    opens[-1] = 10.40
    closes[-1] = 11.20
    highs[-1] = 11.80
    lows[-1] = 10.30
    volumes[-1] = 1_500_000

    frame = pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        },
        index=index,
    )

    print(json.dumps(
        analyze_market_integrity(
            "DEMO",
            frame,
            bid=11.10,
            ask=11.30,
            float_shares=6_000_000,
            news_score=0.0,
            market_return_pct=0.1,
            sector_return_pct=0.2,
        ),
        indent=2,
        ensure_ascii=False,
    ))
