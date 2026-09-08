from __future__ import annotations

from math import isfinite
from typing import Any, Dict, Optional


VERDICT_MEANING = (
    "Deterministic premarket entry-suitability decision support. "
    "It is not probability of profit, not an order, and not a guarantee."
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


def evaluate_premarket_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    """Classify whether a LONG premarket entry is worth considering.

    Output verdicts:
      PREMARKET_BUY_CANDIDATE
      WAIT
      AVOID

    This is intentionally conservative.

    A BUY_CANDIDATE requires:
      - full real minute-history analysis
      - bullish direction
      - eligible setup
      - sufficiently strong setup score
      - adequate data quality
      - price not below premarket VWAP
      - price not materially faded from the premarket high
      - adequate observed premarket dollar volume

    Missing data never becomes positive evidence.
    """

    analysis_status = str(item.get("analysis_status") or "")
    direction = str(item.get("direction") or "").lower()
    eligible = item.get("eligible") is True
    delayed = item.get("delayed") is True

    setup_score = _finite(item.get("premarket_score"))
    vwap_position_pct = _finite(item.get("vwap_position_pct"))
    distance_high_pct = _finite(item.get("distance_from_premarket_high_pct"))
    pm_dollar_volume = _finite(item.get("premarket_dollar_volume"))

    analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
    data_quality = _finite(
        item.get("data_quality_component")
        if item.get("data_quality_component") is not None
        else analysis.get("data_quality_component")
    )

    reasons = []
    blockers = []

    if analysis_status != "full_premarket_analysis":
        return {
            "verdict": "WAIT",
            "entry_score": None,
            "eligible_for_premarket_buy": False,
            "reasons": [
                "Full premarket minute-history analysis is not available."
            ],
            "blockers": [
                "Premarket buy-candidate status is never produced from a point snapshot."
            ],
            "confirmation_required": True,
            "setup_state": "WAIT_FOR_OPEN_CONFIRMATION",
            "semantics": VERDICT_MEANING,
        }

    if not eligible:
        blockers.append("Premarket analysis marked the setup ineligible.")

    if direction != "bullish":
        blockers.append(
            "Premarket direction is not bullish; long premarket entry is not supported."
        )

    if setup_score is None:
        blockers.append("Premarket setup score is unavailable.")

    if data_quality is None:
        blockers.append("Premarket data-quality score is unavailable.")

    # Core score components. Missing values are not neutralized into positives.
    score_parts = []

    if setup_score is not None:
        score_parts.append((_clamp(setup_score), 0.45))

    if data_quality is not None:
        score_parts.append((_clamp(data_quality), 0.20))

    if vwap_position_pct is not None:
        # +1.5% above VWAP is already full credit.
        vwap_score = _clamp(50.0 + (vwap_position_pct / 1.5) * 50.0)
        score_parts.append((vwap_score, 0.15))

    if distance_high_pct is not None:
        # 0% = at PM high. -2% or worse = poor location.
        high_location_score = _clamp(100.0 + (distance_high_pct / 2.0) * 100.0)
        score_parts.append((high_location_score, 0.10))

    if pm_dollar_volume is not None:
        if pm_dollar_volume >= 100_000_000:
            liquidity_score = 100.0
        elif pm_dollar_volume >= 50_000_000:
            liquidity_score = 90.0
        elif pm_dollar_volume >= 25_000_000:
            liquidity_score = 80.0
        elif pm_dollar_volume >= 10_000_000:
            liquidity_score = 65.0
        elif pm_dollar_volume >= 5_000_000:
            liquidity_score = 50.0
        elif pm_dollar_volume >= 1_000_000:
            liquidity_score = 30.0
        else:
            liquidity_score = 10.0

        score_parts.append((liquidity_score, 0.10))

    active_weight = sum(weight for _, weight in score_parts)
    entry_score = (
        sum(value * weight for value, weight in score_parts) / active_weight
        if active_weight > 0
        else None
    )

    if setup_score is not None:
        reasons.append(f"Premarket setup score: {setup_score:.1f}/100.")

    if data_quality is not None:
        reasons.append(f"Premarket data quality: {data_quality:.1f}/100.")

    if vwap_position_pct is not None:
        reasons.append(
            f"Price is {vwap_position_pct:+.2f}% versus premarket VWAP."
        )

    if distance_high_pct is not None:
        reasons.append(
            f"Price is {distance_high_pct:+.2f}% versus the premarket high."
        )

    if pm_dollar_volume is not None:
        reasons.append(
            f"Observed premarket dollar volume: ${pm_dollar_volume:,.0f}."
        )

    # Hard safety gates for PREMARKET_BUY_CANDIDATE.
    hard_buy_conditions = [
        eligible,
        direction == "bullish",
        setup_score is not None and setup_score >= 70.0,
        data_quality is not None and data_quality >= 70.0,
        vwap_position_pct is not None and vwap_position_pct >= 0.0,
        distance_high_pct is not None and distance_high_pct >= -1.5,
        pm_dollar_volume is not None and pm_dollar_volume >= 5_000_000,
        entry_score is not None and entry_score >= 70.0,
    ]

    if all(hard_buy_conditions):
        verdict = "PREMARKET_BUY_CANDIDATE"
        eligible_for_buy = True
        reasons.append(
            "Bullish full-data premarket setup passed all conservative long-entry gates."
        )
    else:
        eligible_for_buy = False

        # Explicit AVOID conditions for long premarket buying.
        avoid_conditions = [
            direction == "bearish",
            setup_score is not None and setup_score < 45.0,
            vwap_position_pct is not None and vwap_position_pct <= -0.75,
            distance_high_pct is not None and distance_high_pct <= -2.5,
        ]

        if any(avoid_conditions):
            verdict = "AVOID"
        else:
            verdict = "WAIT"

        if setup_score is not None and setup_score < 70.0:
            blockers.append("Premarket setup score is below the 70/100 buy-candidate gate.")

        if data_quality is not None and data_quality < 70.0:
            blockers.append("Data quality is below the 70/100 buy-candidate gate.")

        if vwap_position_pct is None:
            blockers.append("Premarket VWAP position is unavailable.")
        elif vwap_position_pct < 0.0:
            blockers.append("Price is below premarket VWAP.")

        if distance_high_pct is None:
            blockers.append("Distance from premarket high is unavailable.")
        elif distance_high_pct < -1.5:
            blockers.append("Price has faded too far from the premarket high.")

        if pm_dollar_volume is None:
            blockers.append("Premarket dollar volume is unavailable.")
        elif pm_dollar_volume < 5_000_000:
            blockers.append("Observed premarket dollar volume is below the minimum gate.")

    return {
        "verdict": verdict,
        "entry_score": round(entry_score, 1) if entry_score is not None else None,
        "eligible_for_premarket_buy": eligible_for_buy,
        "reasons": reasons,
        "blockers": list(dict.fromkeys(blockers)),
        "confirmation_required": True,
        "setup_state": "WAIT_FOR_OPEN_CONFIRMATION",
        "delayed_data": delayed,
        "semantics": VERDICT_MEANING,
    }


if __name__ == "__main__":
    import json

    demo = {
        "analysis_status": "full_premarket_analysis",
        "direction": "bullish",
        "eligible": True,
        "delayed": True,
        "premarket_score": 82.0,
        "vwap_position_pct": 0.55,
        "distance_from_premarket_high_pct": -0.45,
        "premarket_dollar_volume": 85_000_000,
        "analysis": {
            "data_quality_component": 88.0,
        },
    }

    print(json.dumps(
        evaluate_premarket_entry(demo),
        indent=2,
        ensure_ascii=False,
    ))
