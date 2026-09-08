
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np

from app.services.intraday_probability_engine import (
    HORIZONS,
    estimate_intraday_probabilities,
)
from app.services.intraday_probability_statistical_engine import (
    estimate_intraday_probabilities_v2,
)

SEMANTICS = (
    "V3 ensemble estimate of P(up)/P(down). It combines OrionTrader V1 analog "
    "probability and V2 horizon-specific statistical probability. Agreement "
    "raises usable confidence; disagreement pulls the result toward 50%. "
    "The output is separate from Orion Score and is not a guarantee."
)

# Conservative starting weights. These are NOT fitted to one ticker.
# V1 gets slightly more weight on short horizons because the multi-ticker
# walk-forward tests showed V2 was not consistently superior.
BASE_WEIGHTS = {
    "30m": {"v1": 0.60, "v2": 0.40},
    "1h":  {"v1": 0.50, "v2": 0.50},
    "3h":  {"v1": 0.50, "v2": 0.50},
    "5h":  {"v1": 0.65, "v2": 0.35},
}

# Confidence caps keep V3 from becoming overconfident before broader calibration.
MAX_DISTANCE_FROM_50 = {
    "30m": 15.0,   # max 65/35
    "1h":  17.5,   # max 67.5/32.5
    "3h":  17.5,
    "5h":  15.0,
}


def _safe_probability(horizon_result: Optional[Dict[str, Any]]) -> Optional[float]:
    if not horizon_result or not horizon_result.get("available"):
        return None
    try:
        value = float(horizon_result.get("probability_up"))
    except (TypeError, ValueError, OverflowError):
        return None
    if not np.isfinite(value):
        return None
    return float(np.clip(value, 0.0, 100.0))


def _direction(probability_up: float) -> str:
    if probability_up >= 55.0:
        return "bullish"
    if probability_up <= 45.0:
        return "bearish"
    return "neutral"


def combine_probabilities(
    horizon: str,
    v1_probability_up: Optional[float],
    v2_probability_up: Optional[float],
    *,
    v1_evidence_quality: Optional[float] = None,
    v2_training_samples: Optional[int] = None,
) -> Dict[str, Any]:
    """Combine V1 and V2 conservatively.

    Principles:
    - If only one model is available, use it but shrink toward 50%.
    - If both agree directionally, preserve more of the signal.
    - If they disagree, strongly shrink toward 50%.
    - Never let the ensemble become more extreme than the configured horizon cap.
    """

    if horizon not in HORIZONS:
        raise ValueError(f"Unsupported horizon: {horizon}")

    p1 = None if v1_probability_up is None else float(v1_probability_up)
    p2 = None if v2_probability_up is None else float(v2_probability_up)

    if p1 is None and p2 is None:
        return {
            "available": False,
            "horizon": horizon,
            "reason": "Neither V1 nor V2 probability is available.",
        }

    base = BASE_WEIGHTS[horizon].copy()

    # Reliability modifiers are deliberately mild.
    # V1 evidence_quality is expected on a 0-100 scale when available.
    if v1_evidence_quality is not None:
        q = float(np.clip(v1_evidence_quality, 0.0, 100.0))
        base["v1"] *= 0.75 + 0.50 * (q / 100.0)

    # V2 gets full reliability near ~1200+ resolved rows; smaller samples are reduced.
    if v2_training_samples is not None:
        n = max(0, int(v2_training_samples))
        sample_factor = min(1.0, n / 1200.0)
        base["v2"] *= 0.70 + 0.30 * sample_factor

    if p1 is None:
        raw = 50.0 + (p2 - 50.0) * 0.70
        agreement = "v2_only"
        w1, w2 = 0.0, 1.0
    elif p2 is None:
        raw = 50.0 + (p1 - 50.0) * 0.70
        agreement = "v1_only"
        w1, w2 = 1.0, 0.0
    else:
        total = base["v1"] + base["v2"]
        w1 = base["v1"] / total
        w2 = base["v2"] / total
        weighted = w1 * p1 + w2 * p2

        d1 = _direction(p1)
        d2 = _direction(p2)

        if d1 == d2 and d1 != "neutral":
            # Agreement: keep 95% of the distance from 50.
            raw = 50.0 + (weighted - 50.0) * 0.95
            agreement = "directional_agreement"
        elif d1 == "neutral" and d2 == "neutral":
            raw = 50.0 + (weighted - 50.0) * 0.70
            agreement = "neutral_agreement"
        elif d1 == "neutral" or d2 == "neutral":
            raw = 50.0 + (weighted - 50.0) * 0.65
            agreement = "partial_agreement"
        else:
            # Opposing directional calls: confidence must fall sharply.
            raw = 50.0 + (weighted - 50.0) * 0.35
            agreement = "directional_disagreement"

    cap = MAX_DISTANCE_FROM_50[horizon]
    final_p = float(np.clip(raw, 50.0 - cap, 50.0 + cap))

    p_up = round(final_p, 1)
    p_down = round(100.0 - p_up, 1)

    return {
        "available": True,
        "horizon": horizon,
        "probability_up": p_up,
        "probability_down": p_down,
        "direction": _direction(p_up),
        "directional_confidence": round(abs(p_up - 50.0) * 2.0, 1),
        "agreement": agreement,
        "v1_probability_up": None if p1 is None else round(p1, 2),
        "v2_probability_up": None if p2 is None else round(p2, 2),
        "v1_weight": round(w1, 3),
        "v2_weight": round(w2, 3),
        "confidence_cap_distance_from_50": cap,
        "method": "conservative_v1_v2_ensemble",
    }


def estimate_intraday_probabilities_v3(
    symbol: str,
) -> Dict[str, Any]:
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        raise ValueError("symbol is required")

    v1 = estimate_intraday_probabilities(ticker)
    v2 = estimate_intraday_probabilities_v2(ticker)

    v1_horizons = v1.get("horizons", {}) if isinstance(v1, dict) else {}
    v2_horizons = v2.get("horizons", {}) if isinstance(v2, dict) else {}

    results: Dict[str, Dict[str, Any]] = {}

    for horizon in HORIZONS:
        v1_row = v1_horizons.get(horizon, {})
        v2_row = v2_horizons.get(horizon, {})

        p1 = _safe_probability(v1_row)
        p2 = _safe_probability(v2_row)

        v1_quality = v1_row.get("evidence_quality")
        v2_samples = v2_row.get("training_samples")

        combined = combine_probabilities(
            horizon,
            p1,
            p2,
            v1_evidence_quality=v1_quality,
            v2_training_samples=v2_samples,
        )

        if not combined.get("available"):
            reasons = []
            if v1_row and not v1_row.get("available"):
                reasons.append(f"V1: {v1_row.get('reason', 'unavailable')}")
            if v2_row and not v2_row.get("available"):
                reasons.append(f"V2: {v2_row.get('reason', 'unavailable')}")
            combined["reason"] = " | ".join(reasons) or combined.get("reason")

        results[horizon] = combined

    available = [r for r in results.values() if r.get("available")]
    bullish = sum(r.get("direction") == "bullish" for r in available)
    bearish = sum(r.get("direction") == "bearish" for r in available)

    consensus = (
        "bullish" if bullish > bearish
        else "bearish" if bearish > bullish
        else "mixed_or_neutral"
    )

    return {
        "symbol": ticker,
        "available": bool(available),
        "horizons": results,
        "cross_horizon_consensus": consensus,
        "source_models": {
            "v1_available": bool(v1.get("available")) if isinstance(v1, dict) else False,
            "v2_available": bool(v2.get("available")) if isinstance(v2, dict) else False,
        },
        "warnings": [
            "V3 remains experimental until multi-symbol walk-forward calibration is completed.",
            "High probability values are intentionally capped to reduce overconfidence.",
        ],
        "semantics": SEMANTICS,
    }


def _self_test() -> Dict[str, Any]:
    examples = {
        "agreement": combine_probabilities(
            "1h", 61.0, 64.0, v1_evidence_quality=80.0, v2_training_samples=1500
        ),
        "disagreement": combine_probabilities(
            "1h", 63.0, 42.0, v1_evidence_quality=80.0, v2_training_samples=1500
        ),
        "v1_only": combine_probabilities(
            "30m", 62.0, None, v1_evidence_quality=75.0
        ),
        "v2_only": combine_probabilities(
            "3h", None, 60.0, v2_training_samples=1000
        ),
    }
    return {
        "self_test": True,
        "examples": examples,
        "semantics": SEMANTICS,
    }


if __name__ == "__main__":
    import json
    import sys

    if "--self-test" in sys.argv:
        output = _self_test()
    else:
        ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "NVDA"
        output = estimate_intraday_probabilities_v3(ticker)

    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
