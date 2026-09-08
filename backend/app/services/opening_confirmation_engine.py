from __future__ import annotations

from datetime import datetime, time, timezone
from math import isfinite
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd


NEW_YORK = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
CONFIRMATION_WINDOW_END = time(10, 15)

SEMANTICS = (
    "Deterministic opening confirmation score for an existing premarket setup. "
    "It is not probability of profit, not a new trade signal, and not order execution."
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


def _coerce_history(history: Any) -> Optional[pd.DataFrame]:
    if not isinstance(history, pd.DataFrame) or history.empty:
        return None

    frame = history.copy()

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")

    if frame.index.isna().any() or frame.index.tz is None:
        return None

    required = ["Open", "High", "Low", "Close", "Volume"]

    if any(column not in frame.columns for column in required):
        return None

    frame[required] = frame[required].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=required).sort_index()

    if frame.empty:
        return None

    if (
        (frame[["Open", "High", "Low", "Close"]] <= 0).any().any()
        or (frame["Volume"] < 0).any()
    ):
        return None

    return frame


def extract_opening_session(
    history: Any,
    *,
    now: Optional[datetime] = None,
) -> Optional[pd.DataFrame]:
    frame = _coerce_history(history)

    if frame is None:
        return None

    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    local_now = now.astimezone(NEW_YORK)
    local_index = frame.index.tz_convert(NEW_YORK)

    mask = (
        (local_index.date == local_now.date())
        & (local_index.time >= REGULAR_OPEN)
        & (local_index.time <= CONFIRMATION_WINDOW_END)
        & (local_index <= local_now)
    )

    result = frame.loc[mask].copy()
    return result if not result.empty else None


def _vwap(frame: pd.DataFrame) -> Optional[float]:
    volume = frame["Volume"].astype(float)
    total_volume = float(volume.sum())

    if total_volume <= 0:
        return None

    typical = (
        frame["High"].astype(float)
        + frame["Low"].astype(float)
        + frame["Close"].astype(float)
    ) / 3.0

    return float((typical * volume).sum() / total_volume)


def evaluate_opening_confirmation(
    premarket_item: Dict[str, Any],
    regular_minute_history: Any,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Confirm, wait, or invalidate an existing premarket setup after 09:30 ET."""

    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    ticker = str(premarket_item.get("ticker") or "").strip().upper()
    direction = str(premarket_item.get("direction") or "").lower()

    pm_high = _finite(premarket_item.get("premarket_high"))
    pm_low = _finite(premarket_item.get("premarket_low"))
    pm_vwap = _finite(premarket_item.get("premarket_vwap"))
    pm_score = _finite(premarket_item.get("premarket_score"))

    if direction not in {"bullish", "bearish"}:
        return {
            "ticker": ticker,
            "setup_state": "WAIT",
            "confirmation_score": None,
            "direction": direction or None,
            "confirmation_required": True,
            "reason": "Premarket direction is neutral or unavailable.",
            "semantics": SEMANTICS,
        }

    if pm_high is None or pm_low is None:
        return {
            "ticker": ticker,
            "setup_state": "WAIT",
            "confirmation_score": None,
            "direction": direction,
            "confirmation_required": True,
            "reason": "Premarket high/low levels are unavailable.",
            "semantics": SEMANTICS,
        }

    session = extract_opening_session(regular_minute_history, now=now)

    if session is None or len(session) < 3:
        return {
            "ticker": ticker,
            "setup_state": "WAIT",
            "confirmation_score": None,
            "direction": direction,
            "confirmation_required": True,
            "reason": "Not enough regular-session minute bars for opening confirmation.",
            "bar_count": 0 if session is None else len(session),
            "semantics": SEMANTICS,
        }

    latest = _finite(session.iloc[-1]["Close"])
    open_price = _finite(session.iloc[0]["Open"])
    opening_high = _finite(session["High"].max())
    opening_low = _finite(session["Low"].min())
    opening_vwap = _vwap(session)
    bar_count = len(session)

    if not all(value is not None and value > 0 for value in (
        latest, open_price, opening_high, opening_low
    )):
        return {
            "ticker": ticker,
            "setup_state": "WAIT",
            "confirmation_score": None,
            "direction": direction,
            "confirmation_required": True,
            "reason": "Opening OHLC data are invalid.",
            "bar_count": bar_count,
            "semantics": SEMANTICS,
        }

    first_n = session.iloc[: min(5, len(session))]
    opening_range_high = _finite(first_n["High"].max())
    opening_range_low = _finite(first_n["Low"].min())

    session_return_pct = (latest / open_price - 1.0) * 100.0

    price_vs_pm_vwap_pct = (
        (latest / pm_vwap - 1.0) * 100.0
        if pm_vwap
        else None
    )

    price_vs_opening_vwap_pct = (
        (latest / opening_vwap - 1.0) * 100.0
        if opening_vwap
        else None
    )

    price_vs_pm_high_pct = (latest / pm_high - 1.0) * 100.0
    price_vs_pm_low_pct = (latest / pm_low - 1.0) * 100.0

    # Simple current-session volume acceleration; this is NOT historical RVOL.
    volume_acceleration = None
    if len(session) >= 6:
        segment = max(2, len(session) // 3)
        early = float(session["Volume"].iloc[:segment].mean())
        late = float(session["Volume"].iloc[-segment:].mean())
        if early > 0:
            volume_acceleration = late / early

    reasons = []
    blockers = []

    components = []

    # Premarket setup quality is only a modest prior.
    if pm_score is not None:
        components.append((_clamp(pm_score), 0.15))

    # Price structure after open.
    if direction == "bullish":
        breakout_score = _clamp(50.0 + (price_vs_pm_high_pct / 1.0) * 50.0)
        session_score = _clamp(50.0 + (session_return_pct / 1.5) * 50.0)
        pm_vwap_score = (
            _clamp(50.0 + (price_vs_pm_vwap_pct / 1.0) * 50.0)
            if price_vs_pm_vwap_pct is not None
            else None
        )
        opening_vwap_score = (
            _clamp(50.0 + (price_vs_opening_vwap_pct / 0.75) * 50.0)
            if price_vs_opening_vwap_pct is not None
            else None
        )
        or_break = latest >= opening_range_high if opening_range_high else False

        invalidated = (
            price_vs_pm_low_pct <= -0.25
            or (
                price_vs_pm_vwap_pct is not None
                and price_vs_pm_vwap_pct <= -0.75
                and session_return_pct < 0
            )
        )

        strong_confirmation = (
            latest >= pm_high
            and (pm_vwap is None or latest >= pm_vwap)
            and (opening_vwap is None or latest >= opening_vwap)
            and or_break
        )

        reasons.append(f"Price vs premarket high: {price_vs_pm_high_pct:+.2f}%.")
        if price_vs_pm_vwap_pct is not None:
            reasons.append(f"Price vs premarket VWAP: {price_vs_pm_vwap_pct:+.2f}%.")
        if price_vs_opening_vwap_pct is not None:
            reasons.append(f"Price vs opening VWAP: {price_vs_opening_vwap_pct:+.2f}%.")

    else:
        breakout_score = _clamp(50.0 + (-price_vs_pm_low_pct / 1.0) * 50.0)
        session_score = _clamp(50.0 + (-session_return_pct / 1.5) * 50.0)
        pm_vwap_score = (
            _clamp(50.0 + (-price_vs_pm_vwap_pct / 1.0) * 50.0)
            if price_vs_pm_vwap_pct is not None
            else None
        )
        opening_vwap_score = (
            _clamp(50.0 + (-price_vs_opening_vwap_pct / 0.75) * 50.0)
            if price_vs_opening_vwap_pct is not None
            else None
        )
        or_break = latest <= opening_range_low if opening_range_low else False

        invalidated = (
            price_vs_pm_high_pct >= 0.25
            or (
                price_vs_pm_vwap_pct is not None
                and price_vs_pm_vwap_pct >= 0.75
                and session_return_pct > 0
            )
        )

        strong_confirmation = (
            latest <= pm_low
            and (pm_vwap is None or latest <= pm_vwap)
            and (opening_vwap is None or latest <= opening_vwap)
            and or_break
        )

        reasons.append(f"Price vs premarket low: {price_vs_pm_low_pct:+.2f}%.")
        if price_vs_pm_vwap_pct is not None:
            reasons.append(f"Price vs premarket VWAP: {price_vs_pm_vwap_pct:+.2f}%.")
        if price_vs_opening_vwap_pct is not None:
            reasons.append(f"Price vs opening VWAP: {price_vs_opening_vwap_pct:+.2f}%.")

    components.extend([
        (breakout_score, 0.30),
        (session_score, 0.20),
    ])

    if pm_vwap_score is not None:
        components.append((pm_vwap_score, 0.15))

    if opening_vwap_score is not None:
        components.append((opening_vwap_score, 0.15))

    if volume_acceleration is not None:
        volume_score = _clamp(
            50.0 + ((volume_acceleration - 1.0) / 1.0) * 50.0
        )
        components.append((volume_score, 0.05))
        reasons.append(f"Opening volume acceleration: {volume_acceleration:.2f}x.")

    total_weight = sum(weight for _, weight in components)
    confirmation_score = (
        sum(value * weight for value, weight in components) / total_weight
        if total_weight
        else 0.0
    )

    confirmation_score = round(_clamp(confirmation_score), 1)

    if invalidated:
        state = "INVALIDATED"
        blockers.append("Opening price action invalidated the premarket structure.")
    elif strong_confirmation and confirmation_score >= 70:
        state = "OPEN_CONFIRMED"
        reasons.append("Premarket direction is confirmed by opening price structure.")
    else:
        state = "WAIT"
        blockers.append(
            "Opening structure has not yet met all confirmation requirements."
        )

    return {
        "ticker": ticker,
        "direction": direction,
        "setup_state": state,
        "confirmation_score": confirmation_score,
        "confirmation_required": state != "OPEN_CONFIRMED",
        "premarket_score": pm_score,
        "premarket_high": round(pm_high, 6),
        "premarket_low": round(pm_low, 6),
        "premarket_vwap": round(pm_vwap, 6) if pm_vwap is not None else None,
        "opening_price": round(open_price, 6),
        "latest_price": round(latest, 6),
        "opening_high": round(opening_high, 6),
        "opening_low": round(opening_low, 6),
        "opening_vwap": round(opening_vwap, 6) if opening_vwap is not None else None,
        "opening_range_high": round(opening_range_high, 6) if opening_range_high is not None else None,
        "opening_range_low": round(opening_range_low, 6) if opening_range_low is not None else None,
        "session_return_pct": round(session_return_pct, 4),
        "price_vs_premarket_high_pct": round(price_vs_pm_high_pct, 4),
        "price_vs_premarket_low_pct": round(price_vs_pm_low_pct, 4),
        "price_vs_premarket_vwap_pct": (
            round(price_vs_pm_vwap_pct, 4)
            if price_vs_pm_vwap_pct is not None
            else None
        ),
        "price_vs_opening_vwap_pct": (
            round(price_vs_opening_vwap_pct, 4)
            if price_vs_opening_vwap_pct is not None
            else None
        ),
        "volume_acceleration": (
            round(volume_acceleration, 4)
            if volume_acceleration is not None
            else None
        ),
        "bar_count": bar_count,
        "data_timestamp": pd.Timestamp(session.index[-1]).isoformat(),
        "reasons": reasons,
        "blockers": blockers,
        "regular_session_confirmed": state == "OPEN_CONFIRMED",
        "semantics": SEMANTICS,
    }


if __name__ == "__main__":
    import json

    idx = pd.date_range(
        "2026-09-04 09:30",
        periods=8,
        freq="1min",
        tz="America/New_York",
    )

    bars = pd.DataFrame(
        {
            "Open":  [102.0,102.3,102.6,102.9,103.2,103.5,103.7,103.9],
            "High":  [102.4,102.7,103.0,103.3,103.6,103.8,104.0,104.2],
            "Low":   [101.9,102.2,102.5,102.8,103.1,103.4,103.6,103.8],
            "Close": [102.3,102.6,102.9,103.2,103.5,103.7,103.9,104.1],
            "Volume":[250000,240000,220000,210000,230000,260000,300000,340000],
        },
        index=idx,
    )

    pm = {
        "ticker": "DEMO",
        "direction": "bullish",
        "premarket_score": 82,
        "premarket_high": 103.2,
        "premarket_low": 99.8,
        "premarket_vwap": 102.5,
    }

    print(json.dumps(
        evaluate_opening_confirmation(
            pm,
            bars,
            now=datetime(2026, 9, 4, 13, 38, tzinfo=timezone.utc),
        ),
        indent=2,
        ensure_ascii=False,
    ))
