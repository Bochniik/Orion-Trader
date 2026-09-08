"""Historical market brief only. No snapshot, model, prediction or order path.

Alpaca's calendar supplies actual regular-session closes (including early closes).
Yahoo daily indexes are session labels, not the time at which Close was known.
Never place these rows into the live pool or rewrite their age to retrieval time.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.liquidity_engine import historical_liquidity_metrics, _adv_points, _activity_points, _volatility_points
from app.services.market_intelligence import compact_observation
from app.services.staged_market_scanner import finite, liquidity_filter, screening_quality

NY = ZoneInfo("America/New_York")


def completed_sessions(calendar, now):
    sessions = {}
    for item in calendar:
        day = item["date"]
        opened = datetime.fromisoformat(day + "T" + item["open"]).replace(tzinfo=NY)
        closed = datetime.fromisoformat(day + "T" + item["close"]).replace(tzinfo=NY)
        if day in sessions or opened >= closed:
            raise ValueError("Invalid market calendar")
        if closed <= now:
            sessions[day] = {"date": day, "open": opened, "close": closed}
    result = sorted(sessions.values(), key=lambda row: row["date"])
    if len(result) < 2:
        raise ValueError("Latest completed sessions could not be verified")
    return result[-2:]


def historical_row(symbol, frame, sessions, now, config):
    """Return (qualified row or None, valid history). Reject missing exact sessions."""
    if frame is None or frame.empty or not {"Close", "Volume"}.issubset(frame.columns):
        return None, False
    previous, session = sessions
    labels = [stamp.date().isoformat() for stamp in frame.index]
    if len(labels) != len(set(labels)) or labels != sorted(labels):
        return None, False
    if session["date"] not in labels or previous["date"] not in labels:
        return None, False
    target = labels.index(session["date"])
    preceding = frame.iloc[:target]
    # Ten genuinely usable preceding sessions, not ten rows with corrupt data.
    if any(finite(row.Close) is None or row.Close <= 0 or finite(row.Volume) is None or row.Volume < 0
           for row in frame.iloc[max(0, target - 20):target + 1].itertuples()):
        return None, False
    metrics = historical_liquidity_metrics(preceding, now=session["close"])
    if metrics["history_sessions"] < config.minimum_daily_sessions:
        return None, False
    close, volume = float(frame.iloc[target]["Close"]), float(frame.iloc[target]["Volume"])
    previous_close = finite(frame.iloc[labels.index(previous["date"])]["Close"])
    average = metrics["average_daily_volume_20d"]
    if not previous_close or not average:
        return None, False
    relative = volume / average
    rate = volume / (session["close"] - session["open"]).total_seconds()
    score = (_adv_points(metrics["average_dollar_volume_20d"]) + _activity_points(relative, rate)
             + _volatility_points(metrics["realized_volatility_20d_percent"]))
    screen = {"price": close, "average_dollar_volume": metrics["average_dollar_volume_20d"],
              "dollar_volume": close * volume, "relative_volume": relative,
              "intraday_return": close / previous_close - 1, "liquidity_score": score,
              "spread_pct": None, "history_sessions": metrics["history_sessions"],
              "data_timestamp": session["close"].isoformat(), "history_as_of": previous["close"].isoformat(),
              "provider": "yahoo", "history_provider": "yahoo", "feed": "historical_daily_adjusted",
              "price_delayed": True, "data_status": "valid", "session_return_source": "completed_session_close_to_close"}
    if not screening_quality(screen, config, session["close"])["eligible"]:
        return None, False
    if not liquidity_filter(screen, config)["eligible"]:
        return None, True
    row = compact_observation(symbol, screen, now)
    row.update(historical=True, session_date=session["date"], retrieved_at=now.isoformat(),
               raw_timestamp=frame.index[target].isoformat(), price_type="adjusted_daily_close",
               timestamp_normalization="daily session label -> Alpaca calendar regular-session close",
               calendar_provider="alpaca", resolution="1d", liquidity_score_basis="partial: dollar volume, activity, volatility only; no quotes/trades/coverage points",
               relative_volume_basis="completed session shares / preceding 20-session average shares")
    return row, True
