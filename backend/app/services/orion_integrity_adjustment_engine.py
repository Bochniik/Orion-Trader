from __future__ import annotations

from math import isfinite
from typing import Any, Dict, Optional


SEMANTICS = (
    "Manipulation Impact is a deterministic penalty derived from Orion's "
    "market-integrity anomaly risk. It does NOT prove illegal manipulation. "
    "Adjusted Orion Score remains a suitability score, not probability of profit."
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


def _normalize_horizon(horizon: Any) -> str:
    value = str(horizon or "day").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "intraday": "day",
        "daytrade": "day",
        "day_trade": "day",
        "day_trading": "day",
        "swingtrade": "swing",
        "swing_trade": "swing",
        "swing_trading": "swing",
        "longterm": "long_term",
        "investment": "long_term",
    }
    return aliases.get(value, value)


def _score_label(score: float) -> str:
    if score < 25:
        return "strong_avoid"
    if score < 45:
        return "avoid"
    if score <= 55:
        return "neutral_wait"
    if score < 70:
        return "interesting"
    if score < 85:
        return "buy_candidate"
    return "strong_buy_candidate"


def apply_integrity_adjustment(
    raw_orion_score: Any,
    market_integrity: Dict[str, Any],
    *,
    horizon: str = "day",
    bias: Any = None,
) -> Dict[str, Any]:
    """Combine raw Orion Score with anomalous-market-behaviour risk.

    Base penalty:
        max_penalty[horizon] * (risk / 100)^2

    Direction-aware modifier:
      - bullish setup + upward distortion: 1.15x penalty
      - bearish setup + downward distortion: 1.15x penalty
      - setup direction opposite distortion: 0.75x penalty
      - neutral / unavailable direction: 1.00x

    The risk itself is never treated as probability of manipulation.
    """

    raw = _finite(raw_orion_score)
    risk = _finite((market_integrity or {}).get("market_integrity_risk"))

    if raw is None:
        return {
            "available": False,
            "raw_orion_score": None,
            "manipulation_risk": risk,
            "manipulation_impact": None,
            "adjusted_orion_score": None,
            "reason": "Raw Orion Score is unavailable.",
            "semantics": SEMANTICS,
        }

    if risk is None or not (market_integrity or {}).get("available", False):
        return {
            "available": False,
            "raw_orion_score": round(_clamp(raw), 1),
            "manipulation_risk": None,
            "manipulation_impact": 0.0,
            "adjusted_orion_score": round(_clamp(raw), 1),
            "adjusted_label": _score_label(_clamp(raw)),
            "reason": "Market-integrity risk is unavailable; no penalty was applied.",
            "semantics": SEMANTICS,
        }

    normalized_horizon = _normalize_horizon(horizon)

    max_penalty = {
        "day": 35.0,
        "swing": 20.0,
        "long_term": 8.0,
    }.get(normalized_horizon, 20.0)

    risk = _clamp(risk)
    base_penalty = max_penalty * (risk / 100.0) ** 2

    normalized_bias = str(bias or "").strip().lower()
    distortion_direction = str(
        (market_integrity or {}).get("distortion_direction") or "neutral"
    ).strip().lower()

    directional_factor = 1.0
    directional_relationship = "neutral_or_unavailable"

    if normalized_bias in {"bullish", "buy", "long"}:
        if distortion_direction == "upward":
            directional_factor = 1.15
            directional_relationship = "same_direction"
        elif distortion_direction == "downward":
            directional_factor = 0.75
            directional_relationship = "opposite_direction"

    elif normalized_bias in {"bearish", "sell", "short"}:
        if distortion_direction == "downward":
            directional_factor = 1.15
            directional_relationship = "same_direction"
        elif distortion_direction == "upward":
            directional_factor = 0.75
            directional_relationship = "opposite_direction"

    penalty = min(max_penalty, base_penalty * directional_factor)

    adjusted = _clamp(raw - penalty)
    impact = -penalty

    if risk < 25:
        impact_label = "minimal"
    elif risk < 45:
        impact_label = "mild"
    elif risk < 65:
        impact_label = "moderate"
    elif risk < 80:
        impact_label = "high"
    else:
        impact_label = "very_high"

    return {
        "available": True,
        "raw_orion_score": round(_clamp(raw), 1),
        "manipulation_risk": round(risk, 1),
        "manipulation_impact": round(impact, 1),
        "adjusted_orion_score": round(adjusted, 1),
        "adjusted_label": _score_label(adjusted),
        "impact_label": impact_label,
        "horizon": normalized_horizon,
        "max_penalty_for_horizon": max_penalty,
        "directional_factor": round(directional_factor, 2),
        "directional_relationship": directional_relationship,
        "distortion_direction": distortion_direction,
        "formula": "max_penalty * (risk/100)^2 * directional_factor",
        "semantics": SEMANTICS,
    }


if __name__ == "__main__":
    import json

    example = apply_integrity_adjustment(
        84,
        {
            "available": True,
            "market_integrity_risk": 75,
            "distortion_direction": "upward",
        },
        horizon="day",
        bias="bullish",
    )

    print(json.dumps(example, indent=2, ensure_ascii=False))
