"""Bounded longer-horizon OHLCV from existing Yahoo and Alpaca clients."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


def daily_inputs(market, broker, user, symbols, now):
    raw_calendar = broker.research_calendar(user, now)
    calendar = []
    for row in raw_calendar:
        def stamp(key):
            return datetime.fromisoformat(row["date"] + "T" + row[key]).replace(tzinfo=ZoneInfo("America/New_York")).isoformat()
        calendar.append({"date": row["date"], "open": stamp("open"), "close": stamp("close")})
    calendar.sort(key=lambda item: item["date"])
    if not calendar or len({r["date"] for r in calendar}) != len(calendar):
        raise ValueError("Invalid research calendar")
    sessions = {r["date"]: r for r in calendar if pd.Timestamp(r["close"]) <= now}
    latest = max(sessions)
    frames, errors = {}, []
    for symbol in dict.fromkeys(["SPY", *symbols]):
        try:
            raw = market.get_price_history(symbol, period="2y", interval="1d")
            labels = [stamp.date().isoformat() for stamp in raw.index]
            if len(labels) != len(set(labels)) or latest not in labels:
                raise ValueError("Missing latest completed session or duplicate daily labels")
            positions = [i for i, day in enumerate(labels) if day in sessions]
            frame = raw.iloc[positions].copy()
            frame.index = pd.to_datetime([sessions[labels[i]]["close"] for i in positions], utc=True)
            if not frame.index.is_monotonic_increasing:
                raise ValueError("Unsorted daily history")
            frames[symbol] = frame
        except Exception as exc:
            errors.append(symbol + ": daily OHLCV unavailable (" + type(exc).__name__ + ")")
    return frames, calendar, errors
