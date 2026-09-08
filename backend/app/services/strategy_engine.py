from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, List, Optional
import math


class TradingHorizon(str, Enum):
    DAY = "day"
    SWING = "swing"
    LONG_TERM = "long_term"


class Bias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class FactorScore:
    name: str
    score: float
    weight: float
    contribution: float
    reason: str


@dataclass
class StrategyResult:
    horizon: str
    bias: str
    quality_score: float
    bullish_score: float
    bearish_score: float

    strategy: str

    entry_low: Optional[float]
    entry_high: Optional[float]
    stop_loss: Optional[float]
    target_1: Optional[float]
    target_2: Optional[float]

    risk_reward_1: Optional[float]
    risk_reward_2: Optional[float]

    factors: List[Dict[str, Any]]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default

        result = float(value)

        if math.isnan(result) or math.isinf(result):
            return default

        return result
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalized_signed(value: float, scale: float) -> float:
    """
    Convert a signed raw value into approximately [-1, 1].

    Example:
        momentum_pct = +2
        scale = 3
        => +0.666
    """
    if scale <= 0:
        return 0.0

    return _clamp(value / scale, -1.0, 1.0)


def _price_distance_pct(price: float, reference: float) -> float:
    if reference == 0:
        return 0.0

    return ((price - reference) / reference) * 100.0


def _rr_ratio(
    entry: Optional[float],
    stop: Optional[float],
    target: Optional[float],
) -> Optional[float]:
    if entry is None or stop is None or target is None:
        return None

    risk = abs(entry - stop)
    reward = abs(target - entry)

    if risk <= 0:
        return None

    return round(reward / risk, 2)


def _final_bias(
    signed_score: float,
    bullish_threshold: float = 0.15,
    bearish_threshold: float = -0.15,
) -> Bias:
    if signed_score >= bullish_threshold:
        return Bias.BULLISH

    if signed_score <= bearish_threshold:
        return Bias.BEARISH

    return Bias.NEUTRAL


def _quality_from_signed_score(score: float) -> float:
    """
    IMPORTANT:
    This is a setup QUALITY score, not probability of success.

    Converts magnitude in [-1, 1] to 0-100.
    """
    return round(_clamp(abs(score), 0.0, 1.0) * 100.0, 1)


def _direction_scores(signed_score: float) -> tuple[float, float]:
    """
    Returns directional strengths, NOT calibrated probabilities.
    """
    normalized = _clamp(signed_score, -1.0, 1.0)

    bullish = max(0.0, normalized) * 100.0
    bearish = max(0.0, -normalized) * 100.0

    return round(bullish, 1), round(bearish, 1)


def _add_factor(
    factors: List[FactorScore],
    name: str,
    raw_score: float,
    weight: float,
    reason: str,
) -> float:
    raw_score = _clamp(raw_score, -1.0, 1.0)

    contribution = raw_score * weight

    factors.append(
        FactorScore(
            name=name,
            score=round(raw_score, 4),
            weight=round(weight, 4),
            contribution=round(contribution, 4),
            reason=reason,
        )
    )

    return contribution


# ---------------------------------------------------------------------------
# DAY TRADING ENGINE
# ---------------------------------------------------------------------------

def analyze_day_strategy(data: Dict[str, Any]) -> StrategyResult:
    """
    Intraday strategy engine.

    Expected useful fields in `data`:
        price
        vwap
        ema_9
        ema_20
        ema_50
        rsi
        macd_hist
        atr
        atr_pct
        volume
        relative_volume
        spread_pct
        momentum_5m_pct
        momentum_15m_pct
        opening_range_high
        opening_range_low
        resistance
        support

        market_score       [-1, +1]
        sector_score       [-1, +1]
        news_score         [-1, +1]
        catalyst_strength  [0, 1]
    """

    factors: List[FactorScore] = []
    warnings: List[str] = []

    price = _safe_float(data.get("price"))
    vwap = _safe_float(data.get("vwap"))

    ema9 = _safe_float(data.get("ema_9"))
    ema20 = _safe_float(data.get("ema_20"))
    ema50 = _safe_float(data.get("ema_50"))

    rsi = _safe_float(data.get("rsi"))
    macd_hist = _safe_float(data.get("macd_hist"), 0.0)

    atr = _safe_float(data.get("atr"))
    atr_pct = _safe_float(data.get("atr_pct"))

    rvol = _safe_float(data.get("relative_volume"), 1.0)
    spread_pct = _safe_float(data.get("spread_pct"))

    momentum_5m = _safe_float(data.get("momentum_5m_pct"), 0.0)
    momentum_15m = _safe_float(data.get("momentum_15m_pct"), 0.0)

    opening_high = _safe_float(data.get("opening_range_high"))
    opening_low = _safe_float(data.get("opening_range_low"))

    support = _safe_float(data.get("support"))
    resistance = _safe_float(data.get("resistance"))

    market_score = _clamp(
        _safe_float(data.get("market_score"), 0.0),
        -1.0,
        1.0,
    )

    sector_score = _clamp(
        _safe_float(data.get("sector_score"), 0.0),
        -1.0,
        1.0,
    )

    news_score = _clamp(
        _safe_float(data.get("news_score"), 0.0),
        -1.0,
        1.0,
    )

    catalyst_strength = _clamp(
        _safe_float(data.get("catalyst_strength"), 0.0),
        0.0,
        1.0,
    )

    if price is None:
        raise ValueError("Day strategy requires 'price'.")

    total = 0.0
    total_weight = 0.0

    # ------------------------------------------------------------------
    # 1. Intraday momentum - 18%
    # ------------------------------------------------------------------

    momentum_score = (
        _normalized_signed(momentum_5m, 2.0) * 0.55
        + _normalized_signed(momentum_15m, 3.0) * 0.45
    )

    weight = 0.18

    total += _add_factor(
        factors,
        "intraday_momentum",
        momentum_score,
        weight,
        f"5m momentum {momentum_5m:.2f}%, "
        f"15m momentum {momentum_15m:.2f}%.",
    )

    total_weight += weight

    # ------------------------------------------------------------------
    # 2. VWAP - 14%
    # ------------------------------------------------------------------

    if vwap and vwap > 0:
        distance = _price_distance_pct(price, vwap)

        vwap_score = _normalized_signed(distance, 1.5)

        total += _add_factor(
            factors,
            "vwap",
            vwap_score,
            0.14,
            f"Price is {distance:+.2f}% from VWAP.",
        )

        total_weight += 0.14
    else:
        warnings.append("VWAP unavailable.")

    # ------------------------------------------------------------------
    # 3. EMA structure - 12%
    # ------------------------------------------------------------------

    ema_score = 0.0
    ema_parts = 0

    if ema9 and ema20:
        ema_score += 1.0 if ema9 > ema20 else -1.0
        ema_parts += 1

    if ema20 and ema50:
        ema_score += 1.0 if ema20 > ema50 else -1.0
        ema_parts += 1

    if ema9:
        ema_score += 1.0 if price > ema9 else -1.0
        ema_parts += 1

    if ema_parts:
        ema_score /= ema_parts

        total += _add_factor(
            factors,
            "ema_structure",
            ema_score,
            0.12,
            "Intraday EMA alignment and price position.",
        )

        total_weight += 0.12
    else:
        warnings.append("EMA structure incomplete.")

    # ------------------------------------------------------------------
    # 4. Relative volume - 12%
    # ------------------------------------------------------------------

    if rvol is not None:
        if rvol >= 3.0:
            volume_score = 1.0
        elif rvol >= 2.0:
            volume_score = 0.8
        elif rvol >= 1.5:
            volume_score = 0.55
        elif rvol >= 1.0:
            volume_score = 0.2
        elif rvol >= 0.7:
            volume_score = -0.15
        else:
            volume_score = -0.45

        # Volume is mainly confirmation.
        # Direction follows current price momentum.
        directional_volume = volume_score

        if momentum_score < 0:
            directional_volume *= -1

        total += _add_factor(
            factors,
            "relative_volume",
            directional_volume,
            0.12,
            f"Relative volume: {rvol:.2f}x.",
        )

        total_weight += 0.12

    # ------------------------------------------------------------------
    # 5. RSI - 7%
    # ------------------------------------------------------------------

    if rsi is not None:
        if 52 <= rsi <= 68:
            rsi_score = 0.65
        elif 32 <= rsi <= 48:
            rsi_score = -0.65
        elif rsi > 80:
            rsi_score = -0.35
        elif rsi < 20:
            rsi_score = 0.35
        else:
            rsi_score = _normalized_signed(rsi - 50.0, 25.0)

        total += _add_factor(
            factors,
            "rsi",
            rsi_score,
            0.07,
            f"RSI: {rsi:.1f}.",
        )

        total_weight += 0.07

    # ------------------------------------------------------------------
    # 6. MACD - 7%
    # ------------------------------------------------------------------

    macd_score = _normalized_signed(macd_hist or 0.0, 0.5)

    total += _add_factor(
        factors,
        "macd_momentum",
        macd_score,
        0.07,
        f"MACD histogram: {macd_hist:.4f}.",
    )

    total_weight += 0.07

    # ------------------------------------------------------------------
    # 7. Opening range - 8%
    # ------------------------------------------------------------------

    if opening_high and opening_low:
        if price > opening_high:
            orb_score = 1.0
            reason = "Price is above opening range high."
        elif price < opening_low:
            orb_score = -1.0
            reason = "Price is below opening range low."
        else:
            middle = (opening_high + opening_low) / 2

            if price > middle:
                orb_score = 0.2
            else:
                orb_score = -0.2

            reason = "Price remains inside opening range."

        total += _add_factor(
            factors,
            "opening_range",
            orb_score,
            0.08,
            reason,
        )

        total_weight += 0.08

    # ------------------------------------------------------------------
    # 8. News catalyst - 10%
    # ------------------------------------------------------------------

    effective_news = news_score * max(0.25, catalyst_strength)

    total += _add_factor(
        factors,
        "news_catalyst",
        effective_news,
        0.10,
        f"News direction {news_score:+.2f}, "
        f"catalyst strength {catalyst_strength:.2f}.",
    )

    total_weight += 0.10

    # ------------------------------------------------------------------
    # 9. Market + sector regime - 7%
    # ------------------------------------------------------------------

    regime_score = market_score * 0.4 + sector_score * 0.6

    total += _add_factor(
        factors,
        "market_sector_regime",
        regime_score,
        0.07,
        f"Market {market_score:+.2f}, sector {sector_score:+.2f}.",
    )

    total_weight += 0.07

    # ------------------------------------------------------------------
    # 10. Liquidity / spread - 5%
    # ------------------------------------------------------------------

    liquidity_score = 0.0

    if spread_pct is not None:
        if spread_pct <= 0.05:
            liquidity_score = 1.0
        elif spread_pct <= 0.10:
            liquidity_score = 0.7
        elif spread_pct <= 0.20:
            liquidity_score = 0.3
        elif spread_pct <= 0.50:
            liquidity_score = -0.4
        else:
            liquidity_score = -1.0

        total += _add_factor(
            factors,
            "spread_liquidity",
            liquidity_score,
            0.05,
            f"Spread: {spread_pct:.3f}%.",
        )

        total_weight += 0.05

    # Normalize according to actually available data.
    signed_score = total / total_weight if total_weight else 0.0

    signed_score = _clamp(signed_score, -1.0, 1.0)

    bias = _final_bias(signed_score)
    quality = _quality_from_signed_score(signed_score)

    bull, bear = _direction_scores(signed_score)

    # ------------------------------------------------------------------
    # Entry / stop / targets
    # ------------------------------------------------------------------

    entry_low = None
    entry_high = None
    stop = None
    target1 = None
    target2 = None

    if atr and atr > 0 and bias != Bias.NEUTRAL:
        if bias == Bias.BULLISH:
            entry_low = round(price - atr * 0.10, 4)
            entry_high = round(price + atr * 0.10, 4)

            technical_stop = price - atr * 0.8

            if support and support < price:
                technical_stop = min(price - atr * 0.4, support - atr * 0.10)

            stop = round(technical_stop, 4)

            risk = price - stop

            target1 = round(price + risk * 1.5, 4)
            target2 = round(price + risk * 2.5, 4)

            if resistance and resistance > price:
                target1 = round(max(target1, resistance), 4)

        else:
            entry_low = round(price - atr * 0.10, 4)
            entry_high = round(price + atr * 0.10, 4)

            technical_stop = price + atr * 0.8

            if resistance and resistance > price:
                technical_stop = max(
                    price + atr * 0.4,
                    resistance + atr * 0.10,
                )

            stop = round(technical_stop, 4)

            risk = stop - price

            target1 = round(price - risk * 1.5, 4)
            target2 = round(price - risk * 2.5, 4)

            if support and support < price:
                target1 = round(min(target1, support), 4)

    strategy = {
        Bias.BULLISH: "intraday_momentum_long",
        Bias.BEARISH: "intraday_momentum_short",
        Bias.NEUTRAL: "no_trade",
    }[bias]

    return StrategyResult(
        horizon=TradingHorizon.DAY.value,
        bias=bias.value,
        quality_score=quality,
        bullish_score=bull,
        bearish_score=bear,
        strategy=strategy,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop,
        target_1=target1,
        target_2=target2,
        risk_reward_1=_rr_ratio(price, stop, target1),
        risk_reward_2=_rr_ratio(price, stop, target2),
        factors=[asdict(x) for x in factors],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# SWING TRADING ENGINE
# ---------------------------------------------------------------------------

def analyze_swing_strategy(data: Dict[str, Any]) -> StrategyResult:
    """
    Multi-day / multi-week swing strategy.

    Useful fields:
        price
        ema_20
        ema_50
        ema_200
        sma_50
        sma_200
        rsi
        macd_hist
        adx
        atr
        relative_volume
        momentum_5d_pct
        momentum_20d_pct
        support
        resistance
        breakout_score
        relative_strength_score
        market_score
        sector_score
        news_score
        catalyst_strength
    """

    factors: List[FactorScore] = []
    warnings: List[str] = []

    price = _safe_float(data.get("price"))

    if price is None:
        raise ValueError("Swing strategy requires 'price'.")

    ema20 = _safe_float(data.get("ema_20"))
    ema50 = _safe_float(data.get("ema_50"))
    ema200 = _safe_float(data.get("ema_200"))

    sma50 = _safe_float(data.get("sma_50"))
    sma200 = _safe_float(data.get("sma_200"))

    rsi = _safe_float(data.get("rsi"))
    macd_hist = _safe_float(data.get("macd_hist"), 0.0)
    adx = _safe_float(data.get("adx"))

    atr = _safe_float(data.get("atr"))
    rvol = _safe_float(data.get("relative_volume"), 1.0)

    momentum_5d = _safe_float(data.get("momentum_5d_pct"), 0.0)
    momentum_20d = _safe_float(data.get("momentum_20d_pct"), 0.0)

    support = _safe_float(data.get("support"))
    resistance = _safe_float(data.get("resistance"))

    breakout_score = _clamp(
        _safe_float(data.get("breakout_score"), 0.0),
        -1.0,
        1.0,
    )

    relative_strength = _clamp(
        _safe_float(data.get("relative_strength_score"), 0.0),
        -1.0,
        1.0,
    )

    market_score = _clamp(
        _safe_float(data.get("market_score"), 0.0),
        -1.0,
        1.0,
    )

    sector_score = _clamp(
        _safe_float(data.get("sector_score"), 0.0),
        -1.0,
        1.0,
    )

    news_score = _clamp(
        _safe_float(data.get("news_score"), 0.0),
        -1.0,
        1.0,
    )

    catalyst_strength = _clamp(
        _safe_float(data.get("catalyst_strength"), 0.0),
        0.0,
        1.0,
    )

    total = 0.0
    total_weight = 0.0

    # Trend structure - 23%

    trend_parts = []

    if ema20 and ema50:
        trend_parts.append(1.0 if ema20 > ema50 else -1.0)

    if ema50 and ema200:
        trend_parts.append(1.0 if ema50 > ema200 else -1.0)

    if ema20:
        trend_parts.append(1.0 if price > ema20 else -1.0)

    if sma50 and sma200:
        trend_parts.append(1.0 if sma50 > sma200 else -1.0)

    if trend_parts:
        trend_score = sum(trend_parts) / len(trend_parts)

        total += _add_factor(
            factors,
            "medium_term_trend",
            trend_score,
            0.23,
            "EMA/SMA medium-term trend alignment.",
        )

        total_weight += 0.23

    # Momentum - 14%

    momentum_score = (
        _normalized_signed(momentum_5d, 8.0) * 0.4
        + _normalized_signed(momentum_20d, 15.0) * 0.6
    )

    total += _add_factor(
        factors,
        "swing_momentum",
        momentum_score,
        0.14,
        f"5d {momentum_5d:+.2f}%, 20d {momentum_20d:+.2f}%.",
    )

    total_weight += 0.14

    # Breakout / technical structure - 13%

    total += _add_factor(
        factors,
        "technical_structure",
        breakout_score,
        0.13,
        "Breakout / consolidation / technical structure score.",
    )

    total_weight += 0.13

    # Relative strength - 12%

    total += _add_factor(
        factors,
        "relative_strength",
        relative_strength,
        0.12,
        "Relative performance versus benchmark.",
    )

    total_weight += 0.12

    # RSI - 7%

    if rsi is not None:
        if 50 <= rsi <= 68:
            rsi_score = 0.65
        elif 32 <= rsi < 50:
            rsi_score = -0.4
        elif rsi > 78:
            rsi_score = -0.3
        elif rsi < 25:
            rsi_score = 0.25
        else:
            rsi_score = _normalized_signed(rsi - 50, 30)

        total += _add_factor(
            factors,
            "rsi",
            rsi_score,
            0.07,
            f"RSI: {rsi:.1f}.",
        )

        total_weight += 0.07

    # MACD - 7%

    total += _add_factor(
        factors,
        "macd",
        _normalized_signed(macd_hist or 0.0, 1.0),
        0.07,
        f"MACD histogram: {macd_hist:.4f}.",
    )

    total_weight += 0.07

    # ADX trend strength - 6%

    if adx is not None:
        if adx >= 35:
            adx_strength = 1.0
        elif adx >= 25:
            adx_strength = 0.7
        elif adx >= 20:
            adx_strength = 0.35
        else:
            adx_strength = -0.25

        direction = 1.0 if momentum_score >= 0 else -1.0
        adx_score = adx_strength * direction

        total += _add_factor(
            factors,
            "adx",
            adx_score,
            0.06,
            f"ADX: {adx:.1f}.",
        )

        total_weight += 0.06

    # Volume confirmation - 5%

    if rvol:
        confirmation = _clamp((rvol - 1.0) / 1.5, -0.5, 1.0)

        if momentum_score < 0:
            confirmation *= -1

        total += _add_factor(
            factors,
            "volume_confirmation",
            confirmation,
            0.05,
            f"Relative volume: {rvol:.2f}x.",
        )

        total_weight += 0.05

    # Market / sector - 7%

    regime = market_score * 0.35 + sector_score * 0.65

    total += _add_factor(
        factors,
        "market_sector_regime",
        regime,
        0.07,
        f"Market {market_score:+.2f}, sector {sector_score:+.2f}.",
    )

    total_weight += 0.07

    # News - 6%

    effective_news = news_score * max(0.3, catalyst_strength)

    total += _add_factor(
        factors,
        "news_catalyst",
        effective_news,
        0.06,
        f"News {news_score:+.2f}, catalyst {catalyst_strength:.2f}.",
    )

    total_weight += 0.06

    signed_score = total / total_weight if total_weight else 0.0
    signed_score = _clamp(signed_score, -1.0, 1.0)

    bias = _final_bias(
        signed_score,
        bullish_threshold=0.18,
        bearish_threshold=-0.18,
    )

    quality = _quality_from_signed_score(signed_score)
    bull, bear = _direction_scores(signed_score)

    entry_low = None
    entry_high = None
    stop = None
    target1 = None
    target2 = None

    if atr and atr > 0 and bias != Bias.NEUTRAL:
        if bias == Bias.BULLISH:
            entry_low = round(price - atr * 0.25, 4)
            entry_high = round(price + atr * 0.10, 4)

            stop = round(
                support - atr * 0.15
                if support and support < price
                else price - atr * 1.4,
                4,
            )

            risk = price - stop
            target1 = round(price + risk * 2.0, 4)
            target2 = round(price + risk * 3.2, 4)

        else:
            entry_low = round(price - atr * 0.10, 4)
            entry_high = round(price + atr * 0.25, 4)

            stop = round(
                resistance + atr * 0.15
                if resistance and resistance > price
                else price + atr * 1.4,
                4,
            )

            risk = stop - price
            target1 = round(price - risk * 2.0, 4)
            target2 = round(price - risk * 3.2, 4)

    strategy = {
        Bias.BULLISH: "swing_trend_long",
        Bias.BEARISH: "swing_trend_short",
        Bias.NEUTRAL: "no_trade",
    }[bias]

    return StrategyResult(
        horizon=TradingHorizon.SWING.value,
        bias=bias.value,
        quality_score=quality,
        bullish_score=bull,
        bearish_score=bear,
        strategy=strategy,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop,
        target_1=target1,
        target_2=target2,
        risk_reward_1=_rr_ratio(price, stop, target1),
        risk_reward_2=_rr_ratio(price, stop, target2),
        factors=[asdict(x) for x in factors],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# LONG-TERM ENGINE
# ---------------------------------------------------------------------------

def analyze_long_term_strategy(data: Dict[str, Any]) -> StrategyResult:
    """
    Sector/profile-aware long-term investment engine.

    Expected useful fields:
        price
        sma_50
        sma_200

        revenue_growth
        eps_growth
        free_cash_flow_growth

        roic
        roe

        debt_to_equity

        valuation_score
        earnings_revision_score
        balance_sheet_score
        business_quality_score
        growth_score

        profile_adjusted_fundamental_score
        fundamental_profile
        fundamental_profile_weights

        market_score
        sector_score
        macro_score
        news_score

        atr
        support
        resistance
    """

    factors: List[FactorScore] = []
    warnings: List[str] = []

    price = _safe_float(
        data.get("price")
    )

    if price is None:
        raise ValueError(
            "Long-term strategy requires 'price'."
        )

    sma50 = _safe_float(
        data.get("sma_50")
    )

    sma200 = _safe_float(
        data.get("sma_200")
    )

    revenue_growth = _safe_float(
        data.get("revenue_growth")
    )

    eps_growth = _safe_float(
        data.get("eps_growth")
    )

    fcf_growth = _safe_float(
        data.get("free_cash_flow_growth")
    )

    roic = _safe_float(
        data.get("roic")
    )

    roe = _safe_float(
        data.get("roe")
    )

    debt_to_equity = _safe_float(
        data.get("debt_to_equity")
    )

    valuation_score = _clamp(
        _safe_float(
            data.get("valuation_score"),
            0.0,
        ),
        -1.0,
        1.0,
    )

    earnings_revision_score = _clamp(
        _safe_float(
            data.get(
                "earnings_revision_score"
            ),
            0.0,
        ),
        -1.0,
        1.0,
    )

    balance_sheet_score = _clamp(
        _safe_float(
            data.get(
                "balance_sheet_score"
            ),
            0.0,
        ),
        -1.0,
        1.0,
    )

    business_quality_score = _clamp(
        _safe_float(
            data.get(
                "business_quality_score"
            ),
            0.0,
        ),
        -1.0,
        1.0,
    )

    growth_score = _clamp(
        _safe_float(
            data.get(
                "growth_score"
            ),
            0.0,
        ),
        -1.0,
        1.0,
    )

    profile_adjusted_score = _clamp(
        _safe_float(
            data.get(
                "profile_adjusted_fundamental_score"
            ),
            0.0,
        ),
        -1.0,
        1.0,
    )

    fundamental_profile = str(
        data.get(
            "fundamental_profile"
        )
        or "general"
    ).strip().lower()

    profile_weights = data.get(
        "fundamental_profile_weights"
    )

    if not isinstance(
        profile_weights,
        dict,
    ):
        profile_weights = {}

    market_score = _clamp(
        _safe_float(
            data.get("market_score"),
            0.0,
        ),
        -1.0,
        1.0,
    )

    sector_score = _clamp(
        _safe_float(
            data.get("sector_score"),
            0.0,
        ),
        -1.0,
        1.0,
    )

    macro_score = _clamp(
        _safe_float(
            data.get("macro_score"),
            0.0,
        ),
        -1.0,
        1.0,
    )

    news_score = _clamp(
        _safe_float(
            data.get("news_score"),
            0.0,
        ),
        -1.0,
        1.0,
    )

    atr = _safe_float(
        data.get("atr")
    )

    support = _safe_float(
        data.get("support")
    )

    resistance = _safe_float(
        data.get("resistance")
    )

    total = 0.0
    total_weight = 0.0

    # =========================================================================
    # PROFILE-AWARE FUNDAMENTAL CORE
    #
    # The profile engine already combines growth / quality / balance sheet /
    # valuation / profitability / revisions using sector-aware weights.
    #
    # We therefore use this as the dominant long-term factor.
    # =========================================================================

    if profile_adjusted_score != 0.0:

        weight = 0.44

        total += _add_factor(
            factors,
            "profile_adjusted_fundamentals",
            profile_adjusted_score,
            weight,
            (
                f"Sector/profile-aware fundamental score "
                f"for profile '{fundamental_profile}'."
            ),
        )

        total_weight += weight

    else:
        warnings.append(
            "Profile-adjusted fundamental score unavailable or neutral."
        )

    # =========================================================================
    # GROWTH DETAIL
    #
    # Still keep an explicit growth factor so Orion can explain whether
    # growth itself is supporting or weakening the thesis.
    # =========================================================================

    growth_components: List[float] = []

    if revenue_growth is not None:
        growth_components.append(
            _normalized_signed(
                revenue_growth,
                25.0,
            )
        )

    if eps_growth is not None:
        growth_components.append(
            _normalized_signed(
                eps_growth,
                30.0,
            )
        )

    if fcf_growth is not None:
        growth_components.append(
            _normalized_signed(
                fcf_growth,
                30.0,
            )
        )

    if growth_components:

        raw_growth = (
            sum(growth_components)
            / len(growth_components)
        )

        # Blend raw growth with the profile engine's deterministic
        # growth score when available.
        combined_growth = (
            raw_growth * 0.55
            + growth_score * 0.45
        )

        weight = 0.10

        total += _add_factor(
            factors,
            "fundamental_growth",
            combined_growth,
            weight,
            (
                f"Revenue growth={revenue_growth}, "
                f"EPS growth={eps_growth}, "
                f"FCF growth={fcf_growth}."
            ),
        )

        total_weight += weight

    # =========================================================================
    # BUSINESS QUALITY / PROFITABILITY
    # =========================================================================

    if business_quality_score != 0.0:

        weight = 0.08

        total += _add_factor(
            factors,
            "business_quality",
            business_quality_score,
            weight,
            "Margins, returns and business-quality metrics.",
        )

        total_weight += weight

    # =========================================================================
    # CAPITAL EFFICIENCY
    # =========================================================================

    profitability_parts: List[float] = []

    if roic is not None:
        profitability_parts.append(
            _normalized_signed(
                roic - 8.0,
                15.0,
            )
        )

    if roe is not None:
        profitability_parts.append(
            _normalized_signed(
                roe - 10.0,
                20.0,
            )
        )

    if profitability_parts:

        capital_efficiency_score = (
            sum(profitability_parts)
            / len(profitability_parts)
        )

        weight = 0.05

        total += _add_factor(
            factors,
            "capital_efficiency",
            capital_efficiency_score,
            weight,
            f"ROIC={roic}, ROE={roe}.",
        )

        total_weight += weight

    # =========================================================================
    # BALANCE SHEET
    # =========================================================================

    if balance_sheet_score != 0.0:

        weight = 0.07

        total += _add_factor(
            factors,
            "balance_sheet",
            balance_sheet_score,
            weight,
            "Profile-aware balance-sheet strength.",
        )

        total_weight += weight

    # =========================================================================
    # LEVERAGE DETAIL
    #
    # Do NOT use conventional D/E penalty for bank-like profiles.
    # =========================================================================

    leverage_ignored_profiles = {
        "banks",
        "insurance",
    }

    if (
        debt_to_equity is not None
        and fundamental_profile
        not in leverage_ignored_profiles
    ):

        normalized_de = (
            debt_to_equity / 100.0
            if debt_to_equity > 10
            else debt_to_equity
        )

        if normalized_de <= 0.30:
            debt_score = 0.75

        elif normalized_de <= 0.75:
            debt_score = 0.40

        elif normalized_de <= 1.25:
            debt_score = 0.05

        elif normalized_de <= 2.00:
            debt_score = -0.40

        else:
            debt_score = -0.80

        weight = 0.04

        total += _add_factor(
            factors,
            "leverage",
            debt_score,
            weight,
            (
                f"Debt/equity raw={debt_to_equity:.2f}, "
                f"normalized={normalized_de:.2f}."
            ),
        )

        total_weight += weight

    # =========================================================================
    # VALUATION
    # =========================================================================

    if valuation_score != 0.0:

        # Less emphasis for early-stage thematic companies where P/E-type
        # metrics are often poor or meaningless.
        if fundamental_profile in {
            "quantum_computing",
            "biotech",
        }:
            weight = 0.04

        elif fundamental_profile == "crypto":
            weight = 0.05

        else:
            weight = 0.07

        total += _add_factor(
            factors,
            "valuation",
            valuation_score,
            weight,
            (
                f"Profile-aware valuation context for "
                f"'{fundamental_profile}'."
            ),
        )

        total_weight += weight

    # =========================================================================
    # EARNINGS REVISIONS
    # =========================================================================

    if earnings_revision_score != 0.0:

        weight = 0.06

        total += _add_factor(
            factors,
            "earnings_revisions",
            earnings_revision_score,
            weight,
            "Direction of earnings/revision proxy.",
        )

        total_weight += weight

    # =========================================================================
    # LONG-TERM TECHNICAL TREND
    # =========================================================================

    if (
        sma50 is not None
        and sma200 is not None
    ):

        trend_score = 0.0

        trend_score += (
            0.5
            if sma50 > sma200
            else -0.5
        )

        trend_score += (
            0.5
            if price > sma200
            else -0.5
        )

        weight = 0.05

        total += _add_factor(
            factors,
            "long_term_trend",
            trend_score,
            weight,
            (
                "Price/SMA200 and SMA50/SMA200 "
                "long-term trend structure."
            ),
        )

        total_weight += weight

    # =========================================================================
    # MARKET / SECTOR / MACRO ENVIRONMENT
    # =========================================================================

    environment_score = (
        sector_score * 0.45
        + market_score * 0.25
        + macro_score * 0.30
    )

    weight = 0.07

    total += _add_factor(
        factors,
        "environment",
        environment_score,
        weight,
        (
            f"Sector={sector_score:+.2f}, "
            f"market={market_score:+.2f}, "
            f"macro={macro_score:+.2f}."
        ),
    )

    total_weight += weight

    # =========================================================================
    # NEWS
    #
    # Long-term news carries much less weight than Day Trading news.
    # =========================================================================

    weight = 0.03

    total += _add_factor(
        factors,
        "news",
        news_score,
        weight,
        "Recent company news and material catalysts.",
    )

    total_weight += weight

    # =========================================================================
    # SPECIAL PROFILE ADJUSTMENTS
    # =========================================================================

    profile_adjustment = 0.0
    profile_reason = None

    # -------------------------------------------------------------------------
    # QUANTUM COMPUTING
    # -------------------------------------------------------------------------

    if fundamental_profile == "quantum_computing":

        # Balance-sheet survival matters especially strongly.
        profile_adjustment += (
            balance_sheet_score
            * 0.10
        )

        profile_reason = (
            "Quantum profile emphasizes cash runway, "
            "balance sheet and dilution risk."
        )

    # -------------------------------------------------------------------------
    # CRYPTO-RELATED EQUITIES
    # -------------------------------------------------------------------------

    elif fundamental_profile == "crypto":

        # Company fundamentals matter, but market regime can dominate.
        profile_adjustment += (
            market_score * 0.04
            + sector_score * 0.06
        )

        profile_reason = (
            "Crypto-related equity profile increases sensitivity "
            "to market/theme regime."
        )

    # -------------------------------------------------------------------------
    # BANKS
    # -------------------------------------------------------------------------

    elif fundamental_profile == "banks":

        profile_adjustment += (
            business_quality_score * 0.04
            + balance_sheet_score * 0.06
        )

        profile_reason = (
            "Bank profile emphasizes profitability "
            "and balance-sheet quality."
        )

    # -------------------------------------------------------------------------
    # SEMICONDUCTORS
    # -------------------------------------------------------------------------

    elif fundamental_profile == "semiconductors":

        profile_adjustment += (
            growth_score * 0.04
            + earnings_revision_score * 0.04
        )

        profile_reason = (
            "Semiconductor profile emphasizes growth "
            "and earnings-cycle revisions."
        )

    # -------------------------------------------------------------------------
    # FUELS / ENERGY
    # -------------------------------------------------------------------------

    elif fundamental_profile == "fuels_energy":

        profile_adjustment += (
            business_quality_score * 0.03
            + balance_sheet_score * 0.03
            + valuation_score * 0.03
        )

        profile_reason = (
            "Energy profile emphasizes profitability, "
            "cash generation, leverage and valuation."
        )

    # -------------------------------------------------------------------------
    # FASHION
    # -------------------------------------------------------------------------

    elif fundamental_profile == "fashion":

        profile_adjustment += (
            business_quality_score * 0.05
            + growth_score * 0.02
        )

        profile_reason = (
            "Fashion profile emphasizes margins, brand economics "
            "and sustainable growth."
        )

    # -------------------------------------------------------------------------
    # COSMETICS
    # -------------------------------------------------------------------------

    elif fundamental_profile == "cosmetics":

        profile_adjustment += (
            business_quality_score * 0.05
            + growth_score * 0.02
        )

        profile_reason = (
            "Cosmetics profile emphasizes pricing power, "
            "margins and repeat-demand economics."
        )

    # -------------------------------------------------------------------------
    # ENGINEERING
    # -------------------------------------------------------------------------

    elif fundamental_profile == "engineering":

        profile_adjustment += (
            balance_sheet_score * 0.03
            + business_quality_score * 0.04
        )

        profile_reason = (
            "Engineering profile emphasizes contract quality, "
            "cash conversion and balance-sheet resilience."
        )

    # -------------------------------------------------------------------------
    # FOOD
    # -------------------------------------------------------------------------

    elif fundamental_profile == "food":

        profile_adjustment += (
            business_quality_score * 0.05
            + balance_sheet_score * 0.03
        )

        profile_reason = (
            "Food profile emphasizes durable margins, "
            "cash flow and balance-sheet stability."
        )

    if profile_reason is not None:

        profile_adjustment = _clamp(
            profile_adjustment,
            -0.15,
            0.15,
        )

        # Add as an explicit factor so Orion can explain it.
        weight = 0.04

        total += _add_factor(
         factors,
          "profile_specific_adjustment",
          _clamp(
             profile_adjustment / 0.15
             if 0.15 != 0
             else 0.0,
             -1.0,
             1.0,
    ),
    weight,
    profile_reason,
)

        total_weight += weight

    # =========================================================================
    # FINAL SCORE
    # =========================================================================

    signed_score = (
        total / total_weight
        if total_weight
        else 0.0
    )

    signed_score = _clamp(
        signed_score,
        -1.0,
        1.0,
    )

    bias = _final_bias(
        signed_score,
        bullish_threshold=0.20,
        bearish_threshold=-0.20,
    )

    quality = (
        _quality_from_signed_score(
            signed_score
        )
    )

    bull, bear = _direction_scores(
        signed_score
    )

    # =========================================================================
    # ENTRY / INVALIDATION / TARGETS
    #
    # These are analytical reference levels, not price forecasts.
    # =========================================================================

    entry_low = None
    entry_high = None
    stop = None
    target1 = None
    target2 = None

    if bias != Bias.NEUTRAL:

        if bias == Bias.BULLISH:

            if atr and atr > 0:
                entry_low = round(
                    price - atr * 0.75,
                    4,
                )
            else:
                entry_low = round(
                    price * 0.97,
                    4,
                )

            entry_high = round(
                price * 1.01,
                4,
            )

            if (
                support
                and support < price
            ):
                stop = round(
                    support * 0.97,
                    4,
                )

            elif atr and atr > 0:
                stop = round(
                    price - atr * 3.0,
                    4,
                )

            else:
                stop = round(
                    price * 0.88,
                    4,
                )

            risk = (
                price - stop
            )

            target1 = round(
                price + risk * 2.0,
                4,
            )

            target2 = round(
                price + risk * 3.5,
                4,
            )

        else:

            # Long-term bearish means mainly:
            # avoid / reduce / wait for thesis improvement.
            #
            # Levels are kept for journal compatibility.

            entry_low = round(
                price * 0.99,
                4,
            )

            entry_high = round(
                price * 1.03,
                4,
            )

            if atr and atr > 0:
                stop = round(
                    price + atr * 3.0,
                    4,
                )

            else:
                stop = round(
                    price * 1.12,
                    4,
                )

            risk = (
                stop - price
            )

            target1 = round(
                price - risk * 2.0,
                4,
            )

            target2 = round(
                price - risk * 3.0,
                4,
            )

    # =========================================================================
    # STRATEGY LABEL
    # =========================================================================

    strategy = {
        Bias.BULLISH: (
            "long_term_accumulate"
        ),

        Bias.BEARISH: (
            "long_term_avoid_or_reduce"
        ),

        Bias.NEUTRAL: (
            "long_term_watch"
        ),
    }[bias]

    # Add profile to strategy metadata through warnings/factors rather than
    # changing existing StrategyResult schema.
    warnings.append(
        f"Fundamental profile: {fundamental_profile}."
    )

    return StrategyResult(
        horizon=(
            TradingHorizon.LONG_TERM.value
        ),

        bias=bias.value,

        quality_score=quality,

        bullish_score=bull,

        bearish_score=bear,

        strategy=strategy,

        entry_low=entry_low,
        entry_high=entry_high,

        stop_loss=stop,

        target_1=target1,
        target_2=target2,

        risk_reward_1=_rr_ratio(
            price,
            stop,
            target1,
        ),

        risk_reward_2=_rr_ratio(
            price,
            stop,
            target2,
        ),

        factors=[
            asdict(item)
            for item
            in factors
        ],

        warnings=warnings,
    )

# ---------------------------------------------------------------------------
# Unified public API
# ---------------------------------------------------------------------------

def analyze_strategy(
    horizon: str | TradingHorizon,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Unified entry point used by scanner/API.

    Example:

        result = analyze_strategy(
            "day",
            {
                "price": 182.50,
                "vwap": 180.90,
                "ema_9": 181.80,
                ...
            }
        )
    """

    if isinstance(horizon, TradingHorizon):
        horizon_value = horizon.value
    else:
        horizon_value = str(horizon).lower().strip()

    if horizon_value == TradingHorizon.DAY.value:
        result = analyze_day_strategy(data)

    elif horizon_value == TradingHorizon.SWING.value:
        result = analyze_swing_strategy(data)

    elif horizon_value in {
        TradingHorizon.LONG_TERM.value,
        "long-term",
        "longterm",
        "investing",
    }:
        result = analyze_long_term_strategy(data)

    else:
        raise ValueError(
            f"Unsupported horizon: {horizon}. "
            f"Expected day, swing, or long_term."
        )

    return result.to_dict()