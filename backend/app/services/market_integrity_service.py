from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

import pandas as pd
import yfinance as yf

from app.services.market_integrity_engine import analyze_market_integrity


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if pd.notna(number) else None


def _history_to_ohlcv(history: Any) -> Optional[pd.DataFrame]:
    if not isinstance(history, pd.DataFrame) or history.empty:
        return None

    frame = history.copy()

    if isinstance(frame.columns, pd.MultiIndex):
        # yfinance can return multi-index columns in some configurations.
        if len(frame.columns.levels) >= 2:
            frame.columns = [
                col[0] if isinstance(col, tuple) else col
                for col in frame.columns
            ]

    rename = {}
    for col in frame.columns:
        low = str(col).lower()
        if low == "open":
            rename[col] = "Open"
        elif low == "high":
            rename[col] = "High"
        elif low == "low":
            rename[col] = "Low"
        elif low == "close":
            rename[col] = "Close"
        elif low == "volume":
            rename[col] = "Volume"

    frame = frame.rename(columns=rename)
    required = ["Open", "High", "Low", "Close", "Volume"]

    if any(col not in frame.columns for col in required):
        return None

    frame = frame[required].copy()

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")

    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")

    return frame


def analyze_ticker_market_integrity(
    ticker: str,
    *,
    period: str = "1d",
    interval: str = "1m",
    prepost: bool = True,
    news_score: Any = None,
    benchmark_return_pct: Any = None,
    sector_return_pct: Any = None,
) -> Dict[str, Any]:
    """Single-ticker integrity analysis for Orion Analyze.

    Uses yfinance only as a bounded single-ticker adapter. Premarket and opening
    workflows continue to use their existing Alpaca-fed minute data directly.
    """

    symbol = str(ticker or "").strip().upper()

    if not symbol:
        raise ValueError("ticker is required")

    warnings = []

    ticker_obj = yf.Ticker(symbol)

    try:
        raw_history = ticker_obj.history(
            period=period,
            interval=interval,
            prepost=prepost,
            auto_adjust=False,
            actions=False,
        )
    except Exception as exc:
        return {
            "ticker": symbol,
            "available": False,
            "market_integrity_risk": None,
            "market_integrity_score": None,
            "directional_distortion": None,
            "state": "DATA_PROVIDER_ERROR",
            "reasons": [],
            "warnings": [f"Minute-history request failed: {type(exc).__name__}"],
        }

    history = _history_to_ohlcv(raw_history)

    if history is None or len(history) < 3:
        return {
            "ticker": symbol,
            "available": False,
            "market_integrity_risk": None,
            "market_integrity_score": None,
            "directional_distortion": None,
            "state": "INSUFFICIENT_DATA",
            "reasons": [],
            "warnings": ["Insufficient minute OHLCV data for market-integrity analysis."],
        }

    fast = {}
    try:
        fast = dict(ticker_obj.fast_info or {})
    except Exception:
        fast = {}

    info = {}
    try:
        # info can be slower; use it only for float/quote fields unavailable in fast_info.
        info = ticker_obj.get_info() or {}
    except Exception:
        info = {}

    bid = _finite(info.get("bid"))
    ask = _finite(info.get("ask"))
    current_price = (
        _finite(fast.get("lastPrice"))
        or _finite(info.get("currentPrice"))
        or _finite(history["Close"].iloc[-1])
    )

    spread_pct = None
    if (
        bid is not None
        and ask is not None
        and ask >= bid
        and bid > 0
        and ask > 0
    ):
        midpoint = (bid + ask) / 2.0
        if midpoint > 0:
            spread_pct = (ask - bid) / midpoint * 100.0

    avg_volume = (
        _finite(fast.get("threeMonthAverageVolume"))
        or _finite(fast.get("tenDayAverageVolume"))
        or _finite(info.get("averageVolume"))
        or _finite(info.get("averageVolume10days"))
    )

    average_dollar_volume = (
        avg_volume * current_price
        if avg_volume is not None and current_price is not None
        else None
    )

    float_shares = (
        _finite(info.get("floatShares"))
        or _finite(info.get("sharesOutstanding"))
    )

    result = analyze_market_integrity(
        symbol,
        history,
        bid=bid,
        ask=ask,
        spread_pct=spread_pct,
        average_dollar_volume=average_dollar_volume,
        float_shares=float_shares,
        news_score=news_score,
        benchmark_return_pct=benchmark_return_pct,
        sector_return_pct=sector_return_pct,
    )

    # Normalize the public key used by the Orion score adjustment layer.
    if "market_integrity_risk" not in result:
        result["market_integrity_risk"] = result.get(
            "manipulation_risk_score"
        )

    result["provider_context"] = {
        "provider": "yfinance",
        "period": period,
        "interval": interval,
        "prepost": bool(prepost),
        "spread_available": spread_pct is not None,
        "average_dollar_volume_available": average_dollar_volume is not None,
        "float_available": float_shares is not None,
    }

    if not info:
        warnings.append("Detailed quote/company metadata was unavailable.")

    if warnings:
        result.setdefault("warnings", []).extend(warnings)

    return result


if __name__ == "__main__":
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "NVDA"
    print(json.dumps(
        analyze_ticker_market_integrity(ticker),
        indent=2,
        ensure_ascii=False,
        default=str,
    ))
