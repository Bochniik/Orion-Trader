
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import yfinance as yf


_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 45
MAX_SYMBOLS = 100


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if not math.isfinite(number):
        return None

    return number


def _normalize_symbols(
    symbols: Iterable[str],
) -> List[str]:
    return list(
        dict.fromkeys(
            str(symbol or "").strip().upper()
            for symbol in symbols
            if str(symbol or "").strip()
        )
    )[:MAX_SYMBOLS]


def _series(
    frame: pd.DataFrame,
    field: str,
    symbol: str,
) -> Optional[pd.Series]:
    if frame is None or frame.empty:
        return None

    try:
        if isinstance(frame.columns, pd.MultiIndex):
            if (field, symbol) in frame.columns:
                return pd.to_numeric(
                    frame[(field, symbol)],
                    errors="coerce",
                )

            if (symbol, field) in frame.columns:
                return pd.to_numeric(
                    frame[(symbol, field)],
                    errors="coerce",
                )

        if field in frame.columns:
            return pd.to_numeric(
                frame[field],
                errors="coerce",
            )
    except Exception:
        return None

    return None


def _sparkline(
    close: pd.Series,
    *,
    points: int = 28,
) -> List[float]:
    values = [
        float(value)
        for value in pd.to_numeric(
            close,
            errors="coerce",
        ).dropna().tail(points).tolist()
        if _finite(value) is not None
    ]

    return [
        round(value, 4)
        for value in values
    ]


def _previous_session_close(
    close: pd.Series,
) -> Optional[float]:
    usable = pd.to_numeric(
        close,
        errors="coerce",
    ).dropna()

    if usable.empty:
        return None

    index = usable.index

    try:
        local_dates = [
            stamp.date()
            if hasattr(stamp, "date")
            else None
            for stamp in index
        ]
    except Exception:
        return None

    distinct = []
    for value in local_dates:
        if value is not None and value not in distinct:
            distinct.append(value)

    if len(distinct) < 2:
        return None

    previous_date = distinct[-2]

    positions = [
        i
        for i, value in enumerate(local_dates)
        if value == previous_date
    ]

    if not positions:
        return None

    return _finite(
        usable.iloc[positions[-1]]
    )


def _download(
    symbols: List[str],
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()

    return yf.download(
        tickers=" ".join(symbols),
        period="5d",
        interval="5m",
        group_by="column",
        auto_adjust=False,
        progress=False,
        threads=True,
        prepost=True,
    )


def get_market_rows(
    symbols: Iterable[str],
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    clean = _normalize_symbols(symbols)

    if not clean:
        return {
            "available": True,
            "items": {},
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "delayed": True,
            "semantics": (
                "No symbols requested."
            ),
        }

    cache_key = ",".join(clean)
    now_mono = time.monotonic()

    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)

        if (
            not force_refresh
            and cached is not None
            and 0
            <= now_mono
            - float(
                cached.get(
                    "created_at_monotonic",
                    0.0,
                )
            )
            < CACHE_TTL_SECONDS
        ):
            return cached["payload"]

    try:
        frame = _download(clean)
    except Exception as exc:
        return {
            "available": False,
            "items": {},
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "error": type(exc).__name__,
            "delayed": True,
            "semantics": (
                "Market quote enrichment is best-effort and "
                "must not block catalogue navigation."
            ),
        }

    result: Dict[str, Any] = {}

    for symbol in clean:
        close = _series(
            frame,
            "Close",
            symbol,
        )

        volume = _series(
            frame,
            "Volume",
            symbol,
        )

        if close is None:
            continue

        usable_close = close.dropna()

        if usable_close.empty:
            continue

        current = _finite(
            usable_close.iloc[-1]
        )

        if current is None:
            continue

        previous_close = _previous_session_close(
            usable_close
        )

        change_pct = None

        if previous_close not in (
            None,
            0,
        ):
            change_pct = (
                current / previous_close
                - 1.0
            ) * 100.0

        latest_volume = None

        if volume is not None:
            usable_volume = volume.dropna()
            if not usable_volume.empty:
                latest_volume = _finite(
                    usable_volume.iloc[-1]
                )

        result[symbol] = {
            "ticker": symbol,
            "price": round(
                current,
                4,
            ),
            "previous_close": (
                round(
                    previous_close,
                    4,
                )
                if previous_close is not None
                else None
            ),
            "change_pct": (
                round(
                    change_pct,
                    3,
                )
                if change_pct is not None
                else None
            ),
            "latest_5m_volume": (
                int(latest_volume)
                if latest_volume is not None
                else None
            ),
            "sparkline": _sparkline(
                usable_close
            ),
            "as_of": (
                usable_close.index[-1].isoformat()
                if hasattr(
                    usable_close.index[-1],
                    "isoformat",
                )
                else str(
                    usable_close.index[-1]
                )
            ),
        }

    payload = {
        "available": True,
        "items": result,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "delayed": True,
        "cache_ttl_seconds": (
            CACHE_TTL_SECONDS
        ),
        "semantics": (
            "Best-effort market display enrichment from recent "
            "5-minute data. It is for catalogue presentation only "
            "and is not an Orion trading signal."
        ),
    }

    with _CACHE_LOCK:
        _CACHE[cache_key] = {
            "created_at_monotonic": (
                now_mono
            ),
            "payload": payload,
        }

    return payload
