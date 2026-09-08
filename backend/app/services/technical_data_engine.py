from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

try:
    from dotenv import load_dotenv

    BACKEND_ROOT = Path(__file__).resolve().parents[2]

    load_dotenv(BACKEND_ROOT / ".env")
    load_dotenv(BACKEND_ROOT.parent / ".env")

except ImportError:
    pass


ALPACA_DATA_BASE = "https://data.alpaca.markets"


# =============================================================================
# HELPERS
# =============================================================================

def _safe_float(
    value: Any,
    default: Optional[float] = None,
) -> Optional[float]:
    try:
        if value is None:
            return default

        result = float(value)

        if math.isnan(result) or math.isinf(result):
            return default

        return result

    except (TypeError, ValueError):
        return default


def _clamp(
    value: float,
    low: float = -1.0,
    high: float = 1.0,
) -> float:
    return max(
        low,
        min(high, value),
    )


def _mean(
    values: List[float],
) -> Optional[float]:
    if not values:
        return None

    return sum(values) / len(values)


def _pct_change(
    newer: float,
    older: float,
) -> Optional[float]:
    if older == 0:
        return None

    return (
        (newer - older)
        / older
    ) * 100.0


def _utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


# =============================================================================
# CREDENTIALS
# =============================================================================

def _get_credentials() -> tuple[
    Optional[str],
    Optional[str],
]:
    key = (
        os.getenv("APCA_API_KEY_ID")
        or os.getenv("ALPACA_API_KEY")
        or os.getenv("ALPACA_API_KEY_ID")
        or os.getenv("APCA_API_KEY")
    )

    secret = (
        os.getenv("APCA_API_SECRET_KEY")
        or os.getenv("ALPACA_SECRET_KEY")
        or os.getenv("ALPACA_API_SECRET")
        or os.getenv("APCA_SECRET_KEY")
    )

    return key, secret


def _headers() -> Dict[str, str]:
    key, secret = _get_credentials()

    if not key or not secret:
        raise RuntimeError(
            "Alpaca credentials are missing."
        )

    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }


# =============================================================================
# ALPACA BAR FETCHING
# =============================================================================

def fetch_bars(
    symbol: str,
    *,
    timeframe: str,
    lookback_days: int,
    limit: int = 1000,
    feed: Optional[str] = None,
    timeout: float = 12.0,
) -> List[Dict[str, Any]]:

    symbol = symbol.upper().strip()

    end = datetime.now(
        timezone.utc
    )

    start = end - timedelta(
        days=lookback_days
    )

    url = (
        f"{ALPACA_DATA_BASE}"
        f"/v2/stocks/{symbol}/bars"
    )

    feeds_to_try = (
        [feed]
        if feed
        else ["sip", "iex"]
    )

    last_error = None

    for selected_feed in feeds_to_try:

        params = {
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": min(
                max(int(limit), 1),
                10000,
            ),
            "adjustment": "raw",
            "sort": "asc",
            "feed": selected_feed,
        }

        try:
            response = requests.get(
                url,
                headers=_headers(),
                params=params,
                timeout=timeout,
            )

        except requests.RequestException as exc:
            last_error = (
                f"{selected_feed}: {exc}"
            )
            continue

        if response.status_code == 200:
            payload = response.json()

            bars = payload.get(
                "bars",
                [],
            )

            if isinstance(bars, list):
                return bars

            return []

        if response.status_code == 401:
            raise RuntimeError(
                "Alpaca authentication failed."
            )

        if response.status_code == 429:
            raise RuntimeError(
                "Alpaca rate limit reached."
            )

        if response.status_code == 403:
            last_error = (
                f"Feed {selected_feed} unavailable for {symbol}."
            )
            continue

        last_error = (
            f"Alpaca HTTP {response.status_code} "
            f"for {symbol} using {selected_feed}."
        )

    raise RuntimeError(
        last_error
        or f"No bar data available for {symbol}."
    )


# =============================================================================
# SERIES EXTRACTION
# =============================================================================

def _extract_series(
    bars: List[Dict[str, Any]],
) -> Dict[str, List[float]]:

    opens: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    closes: List[float] = []
    volumes: List[float] = []

    for bar in bars:
        o = _safe_float(bar.get("o"))
        h = _safe_float(bar.get("h"))
        l = _safe_float(bar.get("l"))
        c = _safe_float(bar.get("c"))
        v = _safe_float(bar.get("v"))

        if None in {o, h, l, c, v}:
            continue

        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(v)

    return {
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }


# =============================================================================
# MOVING AVERAGES
# =============================================================================

def sma(
    values: List[float],
    period: int,
) -> Optional[float]:

    if len(values) < period:
        return None

    return _mean(
        values[-period:]
    )


def ema_series(
    values: List[float],
    period: int,
) -> List[float]:

    if len(values) < period:
        return []

    seed = _mean(
        values[:period]
    )

    if seed is None:
        return []

    multiplier = 2.0 / (
        period + 1.0
    )

    result = [seed]

    current = seed

    for value in values[period:]:
        current = (
            (value - current)
            * multiplier
            + current
        )

        result.append(current)

    return result


def ema(
    values: List[float],
    period: int,
) -> Optional[float]:

    series = ema_series(
        values,
        period,
    )

    return (
        series[-1]
        if series
        else None
    )


# =============================================================================
# RSI
# =============================================================================

def calculate_rsi(
    closes: List[float],
    period: int = 14,
) -> Optional[float]:

    if len(closes) <= period:
        return None

    gains: List[float] = []
    losses: List[float] = []

    for index in range(
        1,
        period + 1,
    ):
        change = (
            closes[index]
            - closes[index - 1]
        )

        gains.append(
            max(change, 0.0)
        )

        losses.append(
            max(-change, 0.0)
        )

    avg_gain = (
        sum(gains) / period
    )

    avg_loss = (
        sum(losses) / period
    )

    for index in range(
        period + 1,
        len(closes),
    ):
        change = (
            closes[index]
            - closes[index - 1]
        )

        gain = max(
            change,
            0.0,
        )

        loss = max(
            -change,
            0.0,
        )

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gain
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + loss
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return (
        100.0
        - (
            100.0
            / (1.0 + rs)
        )
    )


# =============================================================================
# MACD
# =============================================================================

def calculate_macd(
    closes: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Dict[str, Optional[float]]:

    if len(closes) < (
        slow + signal
    ):
        return {
            "macd": None,
            "signal": None,
            "histogram": None,
        }

    fast_series = ema_series(
        closes,
        fast,
    )

    slow_series = ema_series(
        closes,
        slow,
    )

    if not fast_series or not slow_series:
        return {
            "macd": None,
            "signal": None,
            "histogram": None,
        }

    common_length = min(
        len(fast_series),
        len(slow_series),
    )

    fast_aligned = (
        fast_series[-common_length:]
    )

    slow_aligned = (
        slow_series[-common_length:]
    )

    macd_line = [
        f - s
        for f, s in zip(
            fast_aligned,
            slow_aligned,
        )
    ]

    signal_series = ema_series(
        macd_line,
        signal,
    )

    if not signal_series:
        return {
            "macd": macd_line[-1],
            "signal": None,
            "histogram": None,
        }

    macd_value = (
        macd_line[-1]
    )

    signal_value = (
        signal_series[-1]
    )

    return {
        "macd": macd_value,
        "signal": signal_value,
        "histogram": (
            macd_value
            - signal_value
        ),
    }


# =============================================================================
# ATR
# =============================================================================

def calculate_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> Optional[float]:

    if len(closes) <= period:
        return None

    true_ranges: List[float] = []

    for index in range(
        1,
        len(closes),
    ):
        high = highs[index]
        low = lows[index]
        previous_close = (
            closes[index - 1]
        )

        tr = max(
            high - low,
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            ),
        )

        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    atr = (
        sum(
            true_ranges[:period]
        )
        / period
    )

    for tr in true_ranges[
        period:
    ]:
        atr = (
            (
                atr
                * (period - 1)
            )
            + tr
        ) / period

    return atr


# =============================================================================
# ADX
# =============================================================================

def calculate_adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> Optional[float]:

    if len(closes) < (
        period * 2 + 1
    ):
        return None

    tr_values: List[float] = []
    plus_dm_values: List[float] = []
    minus_dm_values: List[float] = []

    for index in range(
        1,
        len(closes),
    ):

        up_move = (
            highs[index]
            - highs[index - 1]
        )

        down_move = (
            lows[index - 1]
            - lows[index]
        )

        plus_dm = (
            up_move
            if (
                up_move > down_move
                and up_move > 0
            )
            else 0.0
        )

        minus_dm = (
            down_move
            if (
                down_move > up_move
                and down_move > 0
            )
            else 0.0
        )

        tr = max(
            highs[index]
            - lows[index],
            abs(
                highs[index]
                - closes[index - 1]
            ),
            abs(
                lows[index]
                - closes[index - 1]
            ),
        )

        tr_values.append(tr)
        plus_dm_values.append(
            plus_dm
        )
        minus_dm_values.append(
            minus_dm
        )

    atr_sum = sum(
        tr_values[:period]
    )

    plus_dm_sum = sum(
        plus_dm_values[:period]
    )

    minus_dm_sum = sum(
        minus_dm_values[:period]
    )

    dx_values: List[float] = []

    for index in range(
        period,
        len(tr_values),
    ):

        if index > period:
            atr_sum = (
                atr_sum
                - (
                    atr_sum
                    / period
                )
                + tr_values[index]
            )

            plus_dm_sum = (
                plus_dm_sum
                - (
                    plus_dm_sum
                    / period
                )
                + plus_dm_values[
                    index
                ]
            )

            minus_dm_sum = (
                minus_dm_sum
                - (
                    minus_dm_sum
                    / period
                )
                + minus_dm_values[
                    index
                ]
            )

        if atr_sum == 0:
            continue

        plus_di = (
            100.0
            * plus_dm_sum
            / atr_sum
        )

        minus_di = (
            100.0
            * minus_dm_sum
            / atr_sum
        )

        denominator = (
            plus_di
            + minus_di
        )

        if denominator == 0:
            dx = 0.0
        else:
            dx = (
                100.0
                * abs(
                    plus_di
                    - minus_di
                )
                / denominator
            )

        dx_values.append(dx)

    if len(dx_values) < period:
        return None

    adx = (
        sum(
            dx_values[:period]
        )
        / period
    )

    for dx in dx_values[
        period:
    ]:
        adx = (
            (
                adx
                * (period - 1)
            )
            + dx
        ) / period

    return adx


# =============================================================================
# VWAP
# =============================================================================

def calculate_vwap(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
) -> Optional[float]:

    if not closes:
        return None

    cumulative_pv = 0.0
    cumulative_volume = 0.0

    for high, low, close, volume in zip(
        highs,
        lows,
        closes,
        volumes,
    ):

        typical_price = (
            high
            + low
            + close
        ) / 3.0

        cumulative_pv += (
            typical_price
            * volume
        )

        cumulative_volume += (
            volume
        )

    if cumulative_volume <= 0:
        return None

    return (
        cumulative_pv
        / cumulative_volume
    )


# =============================================================================
# RELATIVE VOLUME
# =============================================================================

def calculate_relative_volume(
    volumes: List[float],
    period: int = 20,
) -> Optional[float]:

    if len(volumes) < (
        period + 1
    ):
        return None

    current = volumes[-1]

    baseline = _mean(
        volumes[
            -(period + 1):-1
        ]
    )

    if not baseline:
        return None

    return (
        current
        / baseline
    )


# =============================================================================
# SUPPORT / RESISTANCE
# =============================================================================

def calculate_support_resistance(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback: int = 20,
) -> Dict[str, Optional[float]]:

    if not closes:
        return {
            "support": None,
            "resistance": None,
        }

    size = min(
        lookback,
        len(closes),
    )

    recent_highs = (
        highs[-size:]
    )

    recent_lows = (
        lows[-size:]
    )

    if not recent_highs or not recent_lows:
        return {
            "support": None,
            "resistance": None,
        }

    return {
        "support": min(
            recent_lows
        ),
        "resistance": max(
            recent_highs
        ),
    }


# =============================================================================
# BREAKOUT SCORE
# =============================================================================

def calculate_breakout_score(
    price: float,
    highs: List[float],
    lows: List[float],
    *,
    lookback: int = 20,
) -> float:

    if len(highs) < (
        lookback + 1
    ):
        return 0.0

    historical_high = max(
        highs[
            -(lookback + 1):-1
        ]
    )

    historical_low = min(
        lows[
            -(lookback + 1):-1
        ]
    )

    if historical_high <= historical_low:
        return 0.0

    if price > historical_high:

        distance = (
            (
                price
                - historical_high
            )
            / historical_high
        ) * 100.0

        return _clamp(
            0.65
            + distance / 5.0
        )

    if price < historical_low:

        distance = (
            (
                historical_low
                - price
            )
            / historical_low
        ) * 100.0

        return _clamp(
            -0.65
            - distance / 5.0
        )

    range_position = (
        (
            price
            - historical_low
        )
        / (
            historical_high
            - historical_low
        )
    )

    return _clamp(
        (
            range_position
            - 0.5
        )
        * 0.8
    )


# =============================================================================
# RELATIVE STRENGTH
# =============================================================================

def calculate_relative_strength(
    stock_closes: List[float],
    benchmark_closes: List[float],
    period: int = 20,
) -> float:

    if (
        len(stock_closes)
        < period + 1
        or len(benchmark_closes)
        < period + 1
    ):
        return 0.0

    stock_return = _pct_change(
        stock_closes[-1],
        stock_closes[
            -(period + 1)
        ],
    )

    benchmark_return = _pct_change(
        benchmark_closes[-1],
        benchmark_closes[
            -(period + 1)
        ],
    )

    if (
        stock_return is None
        or benchmark_return is None
    ):
        return 0.0

    difference = (
        stock_return
        - benchmark_return
    )

    return _clamp(
        difference / 10.0
    )


# =============================================================================
# OPENING RANGE
# =============================================================================

def calculate_opening_range(
    bars: List[Dict[str, Any]],
    opening_minutes: int = 30,
) -> Dict[str, Optional[float]]:

    if not bars:
        return {
            "opening_range_high": None,
            "opening_range_low": None,
        }

    # This expects recent 1-minute bars.
    # We use the first bars of the latest trading session.
    dated: List[
        tuple[datetime, Dict[str, Any]]
    ] = []

    for bar in bars:
        timestamp = bar.get("t")

        if not timestamp:
            continue

        try:
            text = str(timestamp)

            if text.endswith("Z"):
                text = (
                    text[:-1]
                    + "+00:00"
                )

            dt = datetime.fromisoformat(
                text
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            dated.append(
                (
                    dt,
                    bar,
                )
            )

        except ValueError:
            continue

    if not dated:
        return {
            "opening_range_high": None,
            "opening_range_low": None,
        }

    latest_date = (
        dated[-1][0]
        .astimezone(
            timezone.utc
        )
        .date()
    )

    session_bars = [
        bar
        for dt, bar in dated
        if (
            dt.astimezone(
                timezone.utc
            ).date()
            == latest_date
        )
    ]

    if not session_bars:
        return {
            "opening_range_high": None,
            "opening_range_low": None,
        }

    opening_bars = (
        session_bars[
            :opening_minutes
        ]
    )

    highs = [
        _safe_float(
            bar.get("h")
        )
        for bar in opening_bars
    ]

    lows = [
        _safe_float(
            bar.get("l")
        )
        for bar in opening_bars
    ]

    highs = [
        value
        for value in highs
        if value is not None
    ]

    lows = [
        value
        for value in lows
        if value is not None
    ]

    if not highs or not lows:
        return {
            "opening_range_high": None,
            "opening_range_low": None,
        }

    return {
        "opening_range_high": max(
            highs
        ),
        "opening_range_low": min(
            lows
        ),
    }


# =============================================================================
# DAILY TECHNICALS
# =============================================================================

def build_daily_technicals(
    symbol: str,
) -> Dict[str, Any]:

    bars = fetch_bars(
        symbol,
        timeframe="1Day",
        lookback_days=420,
        limit=350,
    )

    series = _extract_series(
        bars
    )

    highs = series["high"]
    lows = series["low"]
    closes = series["close"]
    volumes = series["volume"]

    if not closes:
        raise RuntimeError(
            f"No daily bars available for {symbol}."
        )

    price = closes[-1]

    macd = calculate_macd(
        closes
    )

    atr = calculate_atr(
        highs,
        lows,
        closes,
    )

    levels = (
        calculate_support_resistance(
            highs,
            lows,
            closes,
            lookback=20,
        )
    )

    momentum_5d = (
        _pct_change(
            closes[-1],
            closes[-6],
        )
        if len(closes) >= 6
        else None
    )

    momentum_20d = (
        _pct_change(
            closes[-1],
            closes[-21],
        )
        if len(closes) >= 21
        else None
    )

    atr_pct = (
        (
            atr
            / price
        )
        * 100.0
        if (
            atr is not None
            and price > 0
        )
        else None
    )

    return {
        "price": price,

        "ema_20": ema(
            closes,
            20,
        ),

        "ema_50": ema(
            closes,
            50,
        ),

        "ema_200": ema(
            closes,
            200,
        ),

        "sma_50": sma(
            closes,
            50,
        ),

        "sma_200": sma(
            closes,
            200,
        ),

        "rsi": calculate_rsi(
            closes
        ),

        "macd": macd[
            "macd"
        ],

        "macd_signal": macd[
            "signal"
        ],

        "macd_hist": macd[
            "histogram"
        ],

        "atr": atr,
        "atr_pct": atr_pct,

        "adx": calculate_adx(
            highs,
            lows,
            closes,
        ),

        "relative_volume": (
            calculate_relative_volume(
                volumes
            )
        ),

        "momentum_5d_pct": (
            momentum_5d
        ),

        "momentum_20d_pct": (
            momentum_20d
        ),

        "support": levels[
            "support"
        ],

        "resistance": levels[
            "resistance"
        ],

        "breakout_score": (
            calculate_breakout_score(
                price,
                highs,
                lows,
                lookback=20,
            )
        ),

        "_daily_closes": closes,

        "daily_bar_count": len(
            closes
        ),
    }


# =============================================================================
# INTRADAY TECHNICALS
# =============================================================================

def build_intraday_technicals(
    symbol: str,
) -> Dict[str, Any]:

    bars = fetch_bars(
        symbol,
        timeframe="1Min",
        lookback_days=7,
        limit=10000,
    )

    series = _extract_series(
        bars
    )

    highs = series["high"]
    lows = series["low"]
    closes = series["close"]
    volumes = series["volume"]

    if not closes:
        raise RuntimeError(
            f"No intraday bars available for {symbol}."
        )

    price = closes[-1]

    macd = calculate_macd(
        closes
    )

    atr = calculate_atr(
        highs,
        lows,
        closes,
    )

    levels = (
        calculate_support_resistance(
            highs,
            lows,
            closes,
            lookback=60,
        )
    )

    opening_range = (
        calculate_opening_range(
            bars,
            opening_minutes=30,
        )
    )

    momentum_5m = (
        _pct_change(
            closes[-1],
            closes[-6],
        )
        if len(closes) >= 6
        else None
    )

    momentum_15m = (
        _pct_change(
            closes[-1],
            closes[-16],
        )
        if len(closes) >= 16
        else None
    )

    atr_pct = (
        (
            atr
            / price
        )
        * 100.0
        if (
            atr is not None
            and price > 0
        )
        else None
    )

    return {
        "price": price,

        "vwap": calculate_vwap(
            highs[-390:],
            lows[-390:],
            closes[-390:],
            volumes[-390:],
        ),

        "ema_9": ema(
            closes,
            9,
        ),

        "ema_20": ema(
            closes,
            20,
        ),

        "ema_50": ema(
            closes,
            50,
        ),

        "rsi": calculate_rsi(
            closes
        ),

        "macd": macd[
            "macd"
        ],

        "macd_signal": macd[
            "signal"
        ],

        "macd_hist": macd[
            "histogram"
        ],

        "atr": atr,
        "atr_pct": atr_pct,

        "relative_volume": (
            calculate_relative_volume(
                volumes,
                period=20,
            )
        ),

        "momentum_5m_pct": (
            momentum_5m
        ),

        "momentum_15m_pct": (
            momentum_15m
        ),

        "opening_range_high": (
            opening_range[
                "opening_range_high"
            ]
        ),

        "opening_range_low": (
            opening_range[
                "opening_range_low"
            ]
        ),

        "support": levels[
            "support"
        ],

        "resistance": levels[
            "resistance"
        ],

        "intraday_bar_count": len(
            closes
        ),
    }


# =============================================================================
# BENCHMARK RELATIVE STRENGTH
# =============================================================================

def build_relative_strength(
    stock_daily_closes: List[float],
    benchmark: str = "SPY",
) -> float:

    try:
        benchmark_bars = fetch_bars(
            benchmark,
            timeframe="1Day",
            lookback_days=90,
            limit=80,
        )

        benchmark_series = (
            _extract_series(
                benchmark_bars
            )
        )

        benchmark_closes = (
            benchmark_series[
                "close"
            ]
        )

        return calculate_relative_strength(
            stock_daily_closes,
            benchmark_closes,
            period=20,
        )

    except Exception:
        return 0.0


# =============================================================================
# MAIN PUBLIC API
# =============================================================================

def get_technical_strategy_data(
    symbol: str,
    horizon: str,
) -> Dict[str, Any]:

    symbol = symbol.upper().strip()
    horizon = str(
        horizon
    ).strip().lower()

    aliases = {
        "daytrade": "day",
        "day_trade": "day",
        "intraday": "day",

        "swingtrade": "swing",
        "swing_trade": "swing",

        "long-term": "long_term",
        "longterm": "long_term",
        "investing": "long_term",
    }

    horizon = aliases.get(
        horizon,
        horizon,
    )

    if horizon == "day":
        data = build_intraday_technicals(
            symbol
        )

        data["symbol"] = symbol
        data["horizon"] = horizon
        data["technical_generated_at"] = (
            _utc_now_iso()
        )

        return data

    if horizon in {
        "swing",
        "long_term",
    }:

        data = build_daily_technicals(
            symbol
        )

        daily_closes = data.pop(
            "_daily_closes",
            [],
        )

        data[
            "relative_strength_score"
        ] = build_relative_strength(
            daily_closes,
            benchmark="SPY",
        )

        data["symbol"] = symbol
        data["horizon"] = horizon
        data["technical_generated_at"] = (
            _utc_now_iso()
        )

        return data

    raise ValueError(
        f"Unsupported horizon: {horizon}"
    )


# =============================================================================
# MANUAL TEST
# =============================================================================

if __name__ == "__main__":

    import json
    import sys

    ticker = (
        sys.argv[1].upper()
        if len(sys.argv) > 1
        else "NVDA"
    )

    horizon = (
        sys.argv[2].lower()
        if len(sys.argv) > 2
        else "day"
    )

    result = (
        get_technical_strategy_data(
            ticker,
            horizon,
        )
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )