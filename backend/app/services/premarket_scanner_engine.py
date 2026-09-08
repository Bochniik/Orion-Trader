from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from math import isfinite
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd


NEW_YORK = ZoneInfo("America/New_York")
PREMARKET_START = time(4, 0)
REGULAR_OPEN = time(9, 30)

SCORE_MEANING = (
    "Deterministic premarket setup-quality research score from 0 to 100. "
    "It is not probability of profit, not Orion buy suitability, and not "
    "regular-session confirmation."
)


def finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def signed_unit(value: float, scale: float) -> float:
    if scale <= 0:
        raise ValueError("scale must be positive")
    return clamp(value / scale, -1.0, 1.0)


def _coerce_history(history: Any) -> Optional[pd.DataFrame]:
    if not isinstance(history, pd.DataFrame) or history.empty:
        return None

    frame = history.copy()

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")

    if frame.index.isna().any() or frame.index.tz is None:
        return None

    frame = frame.sort_index()

    needed = ["Open", "High", "Low", "Close", "Volume"]

    if any(column not in frame.columns for column in needed):
        return None

    values = frame[needed].apply(pd.to_numeric, errors="coerce")

    if values.isna().any().any():
        return None

    if (
        (values[["Open", "High", "Low", "Close"]] <= 0).any().any()
        or (values["Volume"] < 0).any()
    ):
        return None

    frame[needed] = values
    return frame


def extract_premarket_session(
    history: Any,
    *,
    now: Optional[datetime] = None,
) -> Optional[pd.DataFrame]:
    """Return today's usable 04:00 <= t < 09:30 ET premarket bars."""
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
        & (local_index.time >= PREMARKET_START)
        & (local_index.time < REGULAR_OPEN)
        & (local_index <= local_now)
    )

    result = frame.loc[mask].copy()
    return result if not result.empty else None


def _linear_slope_pct_per_bar(values) -> Optional[float]:
    numbers = [finite(v) for v in values]
    if len(numbers) < 3 or any(v is None for v in numbers):
        return None

    y = [float(v) for v in numbers]
    n = len(y)
    x_mean = (n - 1) / 2.0
    y_mean = sum(y) / n

    numerator = sum(
        (i - x_mean) * (value - y_mean)
        for i, value in enumerate(y)
    )
    denominator = sum(
        (i - x_mean) ** 2
        for i in range(n)
    )

    if denominator <= 0 or y[0] <= 0:
        return None

    slope = numerator / denominator
    return (slope / y[0]) * 100.0


def _volume_acceleration(volume_series) -> Optional[float]:
    values = [finite(v) for v in volume_series]
    if len(values) < 6 or any(v is None for v in values):
        return None

    n = len(values)
    segment = max(2, n // 3)

    first = values[:segment]
    last = values[-segment:]

    first_mean = sum(first) / len(first)
    last_mean = sum(last) / len(last)

    if first_mean <= 0:
        return None

    return last_mean / first_mean


def _vwap(session: pd.DataFrame) -> Optional[float]:
    volume = session["Volume"].astype(float)
    total_volume = float(volume.sum())

    if total_volume <= 0:
        return None

    typical = (
        session["High"].astype(float)
        + session["Low"].astype(float)
        + session["Close"].astype(float)
    ) / 3.0

    return float((typical * volume).sum() / total_volume)


def _absolute_dollar_volume_score(dollar_volume: Optional[float]) -> Optional[float]:
    value = finite(dollar_volume)
    if value is None or value <= 0:
        return None

    if value >= 100_000_000:
        return 100.0
    if value >= 50_000_000:
        return 92.0
    if value >= 25_000_000:
        return 82.0
    if value >= 10_000_000:
        return 68.0
    if value >= 5_000_000:
        return 55.0
    if value >= 1_000_000:
        return 38.0

    return 20.0


@dataclass(frozen=True)
class PremarketResult:
    ticker: str
    eligible: bool
    direction: str
    score: float
    label: str

    previous_close: Optional[float]
    premarket_open: Optional[float]
    premarket_price: Optional[float]
    premarket_high: Optional[float]
    premarket_low: Optional[float]
    premarket_vwap: Optional[float]

    gap_pct: Optional[float]
    premarket_return_pct: Optional[float]
    range_pct: Optional[float]
    vwap_position_pct: Optional[float]
    distance_from_premarket_high_pct: Optional[float]
    distance_from_premarket_low_pct: Optional[float]
    trend_slope_pct_per_bar: Optional[float]

    premarket_volume: Optional[float]
    premarket_dollar_volume: Optional[float]
    relative_premarket_volume: Optional[float]
    volume_acceleration: Optional[float]

    bar_count: int
    data_timestamp: Optional[str]

    technical_component: float
    volume_component: float
    context_component: Optional[float]
    catalyst_component: Optional[float]
    data_quality_component: float

    confirmation_required: bool
    setup_state: str
    invalidation_reference: Optional[float]

    reasons: tuple
    warnings: tuple
    semantics: str = SCORE_MEANING

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _score_label(score: float) -> str:
    if score >= 85:
        return "strong_premarket_setup"
    if score >= 70:
        return "premarket_setup"
    if score >= 56:
        return "interesting"
    if score >= 45:
        return "neutral_wait"
    if score >= 25:
        return "weak"
    return "very_weak"


def analyze_premarket(
    ticker: str,
    minute_history: Any,
    *,
    previous_close: Any,
    average_premarket_volume: Any = None,
    news_score: Any = None,
    market_score: Any = None,
    sector_score: Any = None,
    thematic_score: Any = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Analyze already-supplied REAL premarket minute OHLCV.

    No network calls and no order/execution logic occur here.

    `score` measures setup quality regardless of bullish/bearish direction.
    Direction is returned separately.
    """
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise ValueError("ticker is required")

    previous_close = finite(previous_close)
    if previous_close is not None and previous_close <= 0:
        previous_close = None

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    session = extract_premarket_session(minute_history, now=now)
    warnings = []
    reasons = []

    if session is None:
        result = PremarketResult(
            ticker=symbol,
            eligible=False,
            direction="neutral",
            score=0.0,
            label="unavailable",
            previous_close=previous_close,
            premarket_open=None,
            premarket_price=None,
            premarket_high=None,
            premarket_low=None,
            premarket_vwap=None,
            gap_pct=None,
            premarket_return_pct=None,
            range_pct=None,
            vwap_position_pct=None,
            distance_from_premarket_high_pct=None,
            distance_from_premarket_low_pct=None,
            trend_slope_pct_per_bar=None,
            premarket_volume=None,
            premarket_dollar_volume=None,
            relative_premarket_volume=None,
            volume_acceleration=None,
            bar_count=0,
            data_timestamp=None,
            technical_component=0.0,
            volume_component=0.0,
            context_component=None,
            catalyst_component=None,
            data_quality_component=0.0,
            confirmation_required=True,
            setup_state="WAIT_FOR_OPEN_CONFIRMATION",
            invalidation_reference=None,
            reasons=("No usable current-day premarket minute bars.",),
            warnings=tuple(warnings),
        )
        return result.to_dict()

    open_price = finite(session.iloc[0]["Open"])
    last_price = finite(session.iloc[-1]["Close"])
    high = finite(session["High"].max())
    low = finite(session["Low"].min())
    volume = finite(session["Volume"].sum())

    if not all(
        value is not None and value > 0
        for value in (open_price, last_price, high, low)
    ):
        raise ValueError("Invalid premarket OHLC values")

    bar_count = len(session)
    timestamp = session.index[-1]
    data_timestamp = pd.Timestamp(timestamp).isoformat()

    gap = (
        (last_price / previous_close - 1.0)
        if previous_close
        else None
    )
    session_return = last_price / open_price - 1.0

    range_pct = (
        (high - low) / previous_close
        if previous_close
        else (high - low) / open_price
    )

    pm_vwap = _vwap(session)
    vwap_position = (
        last_price / pm_vwap - 1.0
        if pm_vwap and pm_vwap > 0
        else None
    )

    distance_high = (
        last_price / high - 1.0
        if high > 0
        else None
    )
    distance_low = (
        last_price / low - 1.0
        if low > 0
        else None
    )

    trend_slope_pct_per_bar = _linear_slope_pct_per_bar(
        session["Close"].tolist()
    )

    volume_acceleration = _volume_acceleration(
        session["Volume"].tolist()
    )

    # Use actual bar prices rather than last-price × total shares.
    typical = (
        session["High"].astype(float)
        + session["Low"].astype(float)
        + session["Close"].astype(float)
    ) / 3.0
    dollar_volume = finite(
        float((typical * session["Volume"].astype(float)).sum())
    )

    average_pm_volume = finite(average_premarket_volume)
    if (
        average_pm_volume is not None
        and average_pm_volume > 0
        and volume is not None
    ):
        relative_pm_volume = volume / average_pm_volume
    else:
        relative_pm_volume = None
        warnings.append(
            "Historical comparable premarket volume is unavailable; "
            "relative premarket volume was not invented."
        )

    location = (
        (last_price - low) / (high - low)
        if high > low
        else 0.5
    )

    # ------------------------------------------------------------------
    # Direction. Separate from setup-quality score.
    # ------------------------------------------------------------------
    votes = []

    if gap is not None:
        votes.append((signed_unit(gap, 0.03), 0.30))

    votes.append((signed_unit(session_return, 0.02), 0.25))

    if vwap_position is not None:
        votes.append((signed_unit(vwap_position, 0.01), 0.20))

    votes.append((((location - 0.5) * 2.0), 0.15))

    if trend_slope_pct_per_bar is not None:
        votes.append((
            signed_unit(trend_slope_pct_per_bar / 100.0, 0.002),
            0.10,
        ))

    vote_weight = sum(weight for _, weight in votes)
    directional_vote = (
        sum(value * weight for value, weight in votes) / vote_weight
        if vote_weight
        else 0.0
    )

    if directional_vote >= 0.18:
        direction = "bullish"
    elif directional_vote <= -0.18:
        direction = "bearish"
    else:
        direction = "neutral"

    # ------------------------------------------------------------------
    # Technical setup quality.
    # ------------------------------------------------------------------
    gap_strength = (
        abs(signed_unit(gap, 0.04)) * 100
        if gap is not None
        else None
    )
    move_strength = abs(signed_unit(session_return, 0.025)) * 100

    vwap_strength = (
        abs(signed_unit(vwap_position, 0.015)) * 100
        if vwap_position is not None
        else None
    )

    location_strength = abs(location - 0.5) * 2.0 * 100

    slope_strength = (
        abs(
            signed_unit(
                trend_slope_pct_per_bar / 100.0,
                0.0025,
            )
        ) * 100
        if trend_slope_pct_per_bar is not None
        else None
    )

    technical_parts = [
        (gap_strength, 0.30),
        (move_strength, 0.25),
        (vwap_strength, 0.20),
        (location_strength, 0.15),
        (slope_strength, 0.10),
    ]

    technical_weight = sum(
        weight
        for value, weight in technical_parts
        if value is not None
    )
    technical_component = (
        sum(
            value * weight
            for value, weight in technical_parts
            if value is not None
        ) / technical_weight
        if technical_weight
        else 0.0
    )

    # ------------------------------------------------------------------
    # Volume/activity quality.
    # ------------------------------------------------------------------
    absolute_volume_score = _absolute_dollar_volume_score(dollar_volume)

    relative_volume_score = (
        clamp((relative_pm_volume - 0.5) / 2.0, 0.0, 1.0) * 100
        if relative_pm_volume is not None
        else None
    )

    acceleration_score = (
        clamp(
            (volume_acceleration - 0.7) / 1.8,
            0.0,
            1.0,
        ) * 100
        if volume_acceleration is not None
        else None
    )

    volume_parts = [
        (relative_volume_score, 0.50),
        (absolute_volume_score, 0.30),
        (acceleration_score, 0.20),
    ]
    volume_weight = sum(
        weight
        for value, weight in volume_parts
        if value is not None
    )
    volume_component = (
        sum(
            value * weight
            for value, weight in volume_parts
            if value is not None
        ) / volume_weight
        if volume_weight
        else 0.0
    )

    # ------------------------------------------------------------------
    # Context ALIGNMENT with direction. Missing context stays missing.
    # ------------------------------------------------------------------
    context_values = []
    for value in (market_score, sector_score, thematic_score):
        number = finite(value)
        if number is not None:
            context_values.append(clamp(number, -1.0, 1.0))

    context_component = None
    if context_values and direction != "neutral":
        context_signed = sum(context_values) / len(context_values)
        direction_sign = 1.0 if direction == "bullish" else -1.0
        context_component = clamp(
            50.0 + 50.0 * direction_sign * context_signed,
            0.0,
            100.0,
        )
    elif context_values:
        context_component = 50.0
    else:
        warnings.append(
            "Market/sector/theme context is unavailable; it was excluded from the score."
        )

    news = finite(news_score)
    catalyst_component = None
    if news is not None and direction != "neutral":
        direction_sign = 1.0 if direction == "bullish" else -1.0
        catalyst_component = clamp(
            50.0 + 50.0 * direction_sign * clamp(news, -1.0, 1.0),
            0.0,
            100.0,
        )
    elif news is not None:
        catalyst_component = 50.0
    else:
        warnings.append(
            "Current news/catalyst score is unavailable; it was excluded from the score."
        )

    # ------------------------------------------------------------------
    # Data quality. Bar count matters because 3 isolated bars are not enough
    # for robust intrapremarket structure.
    # ------------------------------------------------------------------
    quality_fields = [
        previous_close,
        open_price,
        last_price,
        high,
        low,
        pm_vwap,
        volume,
        trend_slope_pct_per_bar,
        volume_acceleration,
    ]
    present_ratio = (
        sum(value is not None for value in quality_fields)
        / len(quality_fields)
    )

    bar_coverage = clamp(bar_count / 20.0, 0.0, 1.0)

    data_quality_component = (
        present_ratio * 70.0
        + bar_coverage * 30.0
    )

    # ------------------------------------------------------------------
    # Dynamic-weight score: missing context/news is EXCLUDED, not neutralized.
    # ------------------------------------------------------------------
    score_parts = [
        (technical_component, 0.45),
        (volume_component, 0.25),
        (context_component, 0.15),
        (catalyst_component, 0.10),
        (data_quality_component, 0.05),
    ]

    active_weight = sum(
        weight
        for value, weight in score_parts
        if value is not None
    )

    score = (
        sum(
            value * weight
            for value, weight in score_parts
            if value is not None
        ) / active_weight
        if active_weight
        else 0.0
    )

    # Neutral-direction setups cannot become top-confidence directional setups.
    if direction == "neutral":
        score = min(score, 69.0)

    # Poor data quality cannot produce a strong full setup.
    if data_quality_component < 60:
        score = min(score, 55.0)

    score = round(clamp(score, 0.0, 100.0), 1)

    if gap is not None:
        reasons.append(
            f"Premarket gap vs prior close: {gap * 100:+.2f}%."
        )

    reasons.append(
        f"Premarket move from first bar: {session_return * 100:+.2f}%."
    )

    if pm_vwap is not None and vwap_position is not None:
        reasons.append(
            f"Price is {vwap_position * 100:+.2f}% vs premarket VWAP."
        )

    reasons.append(
        f"Premarket price location within range: {location * 100:.1f}%."
    )

    if trend_slope_pct_per_bar is not None:
        reasons.append(
            f"Premarket close slope: {trend_slope_pct_per_bar:+.4f}% per bar."
        )

    if volume_acceleration is not None:
        reasons.append(
            f"Late/early premarket volume ratio: {volume_acceleration:.2f}x."
        )

    if relative_pm_volume is not None:
        reasons.append(
            f"Relative premarket volume: {relative_pm_volume:.2f}x."
        )

    reasons.append(
        "Regular-session confirmation is required before this setup can be treated as confirmed."
    )

    eligible = (
        previous_close is not None
        and bar_count >= 5
        and data_quality_component >= 60
    )

    if not eligible:
        warnings.append(
            "Premarket evidence is incomplete; setup remains research-only."
        )

    invalidation_reference = None
    if direction == "bullish":
        invalidation_reference = low
    elif direction == "bearish":
        invalidation_reference = high

    result = PremarketResult(
        ticker=symbol,
        eligible=eligible,
        direction=direction,
        score=score,
        label=_score_label(score) if eligible else "insufficient_data",
        previous_close=round(previous_close, 6) if previous_close is not None else None,
        premarket_open=round(open_price, 6),
        premarket_price=round(last_price, 6),
        premarket_high=round(high, 6),
        premarket_low=round(low, 6),
        premarket_vwap=round(pm_vwap, 6) if pm_vwap is not None else None,
        gap_pct=round(gap * 100, 4) if gap is not None else None,
        premarket_return_pct=round(session_return * 100, 4),
        range_pct=round(range_pct * 100, 4),
        vwap_position_pct=round(vwap_position * 100, 4) if vwap_position is not None else None,
        distance_from_premarket_high_pct=round(distance_high * 100, 4) if distance_high is not None else None,
        distance_from_premarket_low_pct=round(distance_low * 100, 4) if distance_low is not None else None,
        trend_slope_pct_per_bar=round(trend_slope_pct_per_bar, 6) if trend_slope_pct_per_bar is not None else None,
        premarket_volume=round(volume, 4) if volume is not None else None,
        premarket_dollar_volume=round(dollar_volume, 2) if dollar_volume is not None else None,
        relative_premarket_volume=round(relative_pm_volume, 4) if relative_pm_volume is not None else None,
        volume_acceleration=round(volume_acceleration, 4) if volume_acceleration is not None else None,
        bar_count=bar_count,
        data_timestamp=data_timestamp,
        technical_component=round(technical_component, 2),
        volume_component=round(volume_component, 2),
        context_component=round(context_component, 2) if context_component is not None else None,
        catalyst_component=round(catalyst_component, 2) if catalyst_component is not None else None,
        data_quality_component=round(data_quality_component, 2),
        confirmation_required=True,
        setup_state="WAIT_FOR_OPEN_CONFIRMATION",
        invalidation_reference=(
            round(invalidation_reference, 6)
            if invalidation_reference is not None
            else None
        ),
        reasons=tuple(reasons),
        warnings=tuple(dict.fromkeys(warnings)),
    )

    return result.to_dict()


if __name__ == "__main__":
    import json

    index = pd.date_range(
        "2026-09-04 08:00",
        periods=12,
        freq="5min",
        tz="America/New_York",
    )

    history = pd.DataFrame(
        {
            "Open":  [102.0,102.3,102.5,102.8,103.0,103.2,103.4,103.6,103.9,104.1,104.3,104.5],
            "High":  [102.5,102.7,102.9,103.2,103.4,103.6,103.8,104.0,104.3,104.5,104.7,105.0],
            "Low":   [101.9,102.1,102.3,102.6,102.8,103.0,103.2,103.4,103.7,103.9,104.1,104.3],
            "Close": [102.3,102.5,102.8,103.0,103.2,103.4,103.6,103.9,104.1,104.3,104.5,104.8],
            "Volume":[80000,90000,100000,110000,120000,130000,150000,170000,190000,220000,250000,280000],
        },
        index=index,
    )

    print(json.dumps(
        analyze_premarket(
            "DEMO",
            history,
            previous_close=100.0,
            average_premarket_volume=900000,
            news_score=0.45,
            market_score=0.35,
            sector_score=0.50,
            thematic_score=0.40,
            now=datetime(2026, 9, 4, 12, 30, tzinfo=timezone.utc),
        ),
        indent=2,
        ensure_ascii=False,
    ))
