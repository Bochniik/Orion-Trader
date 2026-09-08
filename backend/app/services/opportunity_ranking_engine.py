
from __future__ import annotations

from typing import Any, Dict, Optional


HORIZONS = ("30m", "1h", "3h", "5h")


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if number != number or number in (float("inf"), float("-inf")):
        return None

    return number


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _probability_rows(full: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        horizon: (
            full.get(f"probability_{horizon}")
            if isinstance(full.get(f"probability_{horizon}"), dict)
            else {}
        )
        for horizon in HORIZONS
    }


def _select_probability_evidence(
    full: Dict[str, Any],
    bias: str,
) -> Dict[str, Any]:
    """
    Select the strongest usable V3.1 horizon by reliability.

    The selection score is not a market forecast. It only decides which already
    computed V3.1 horizon is the most defensible one to use for opportunity
    ranking.
    """

    candidates = []

    for horizon, row in _probability_rows(full).items():
        if not row.get("available"):
            continue

        if row.get("suppressed") is True:
            continue

        probability_up = _finite(row.get("probability_up"))
        probability_down = _finite(row.get("probability_down"))
        reliability = _finite(row.get("reliability_score"))

        if (
            probability_up is None
            or probability_down is None
            or reliability is None
        ):
            continue

        policy = str(row.get("display_policy") or "")
        if policy == "suppress_directional_probability":
            continue

        # Prefer higher historical reliability first. Strength is only a
        # secondary tie-breaker.
        strength = abs(probability_up - 50.0)

        candidates.append(
            (
                reliability,
                strength,
                horizon,
                row,
            )
        )

    if not candidates:
        return {
            "available": False,
            "horizon": None,
            "aligned_probability": None,
            "probability_up": None,
            "probability_down": None,
            "direction": None,
            "reliability_score": None,
            "reliability_label": None,
            "display_policy": None,
            "agreement": None,
        }

    _, _, horizon, row = max(
        candidates,
        key=lambda item: (
            item[0],
            item[1],
        ),
    )

    probability_up = float(row["probability_up"])
    probability_down = float(row["probability_down"])

    if bias == "bearish":
        aligned_probability = probability_down
    elif bias == "bullish":
        aligned_probability = probability_up
    else:
        aligned_probability = max(
            probability_up,
            probability_down,
        )

    return {
        "available": True,
        "horizon": horizon,
        "aligned_probability": round(aligned_probability, 1),
        "probability_up": round(probability_up, 1),
        "probability_down": round(probability_down, 1),
        "direction": row.get("direction"),
        "reliability_score": _finite(row.get("reliability_score")),
        "reliability_label": row.get("reliability_label"),
        "display_policy": row.get("display_policy"),
        "agreement": row.get("agreement"),
        "profile_validated_for_symbol": row.get(
            "profile_validated_for_symbol",
            full.get(
                "probability_profile_validated_for_symbol",
                False,
            ),
        ),
    }


def build_opportunity_ranking(
    full: Dict[str, Any],
    *,
    scanner_row: Optional[Dict[str, Any]] = None,
    minimum_pick_score: float = 70.0,
) -> Dict[str, Any]:
    """
    Convert the unified Orion analysis into a scanner ranking result.

    Important semantics:
    - opportunity_rank_score is a deterministic ranking score, NOT probability.
    - adjusted Orion Score is the primary base.
    - Market Integrity is not penalized twice: its effect is already included in
      adjusted Orion Score.
    - V3.1 can modestly reorder Day candidates when usable evidence exists.
    - An unvalidated generic V3.1 profile may penalize conflicting evidence but
      cannot positively boost a candidate.
    """

    scanner_row = scanner_row or {}

    raw_score = _finite(
        full.get(
            "raw_orion_score",
            full.get("orion_score"),
        )
    )

    adjusted_score = _finite(
        full.get(
            "adjusted_orion_score",
            raw_score,
        )
    )

    if adjusted_score is None:
        adjusted_score = raw_score

    if adjusted_score is None:
        adjusted_score = 0.0

    raw_score = adjusted_score if raw_score is None else raw_score

    horizon = str(
        full.get(
            "horizon",
            scanner_row.get("horizon", ""),
        )
        or ""
    ).lower()

    bias = str(
        full.get(
            "bias",
            scanner_row.get("direction", "neutral"),
        )
        or "neutral"
    ).lower()

    probability = _select_probability_evidence(
        full,
        bias,
    )

    probability_adjustment = 0.0
    agreement_adjustment = 0.0
    reasons = []

    if horizon == "day" and probability["available"]:
        reliability = float(
            probability["reliability_score"]
            or 0.0
        )

        aligned = float(
            probability["aligned_probability"]
        )

        # The V3.1 value is already shrunk toward 50. We only let it move the
        # ranking a few points so Orion Score remains the dominant signal.
        edge = aligned - 50.0
        reliability_factor = _clip(
            reliability / 100.0,
            0.0,
            1.0,
        )

        probability_adjustment = _clip(
            edge * 0.60 * reliability_factor,
            -6.0,
            6.0,
        )

        validated = bool(
            probability.get(
                "profile_validated_for_symbol"
            )
        )

        # Generic priors must never manufacture a positive ranking advantage.
        if not validated and probability_adjustment > 0:
            probability_adjustment = 0.0

        agreement = str(
            probability.get("agreement")
            or ""
        )

        if agreement == "directional_agreement":
            agreement_adjustment = 1.0 if validated else 0.0

        elif agreement == "directional_disagreement":
            agreement_adjustment = -1.5

        elif agreement in {
            "neutral_agreement",
            "partial_agreement",
        }:
            agreement_adjustment = -0.5

        reasons.append(
            (
                f"V3.1 {probability['horizon']} aligned probability "
                f"{aligned:.1f}% with reliability "
                f"{reliability:.1f}/100."
            )
        )

        if not validated:
            reasons.append(
                "Ticker-specific V3.1 reliability is not validated; "
                "positive probability boost disabled."
            )

    # Do not subtract manipulation/integrity risk again. The adjusted Orion
    # Score already contains the transparent horizon-aware integrity penalty.
    rank_score = _clip(
        adjusted_score
        + probability_adjustment
        + agreement_adjustment,
        0.0,
        100.0,
    )

    manipulation_risk = _finite(
        full.get("manipulation_risk")
    )

    eligible = (
        adjusted_score >= float(minimum_pick_score)
    )

    # Deterministic state for the UI. It does not execute an order.
    state = "AVOID"

    if eligible:
        if horizon == "day":
            if not probability["available"]:
                state = "WATCH"

            else:
                reliability = float(
                    probability["reliability_score"]
                    or 0.0
                )
                aligned = float(
                    probability["aligned_probability"]
                )

                if reliability < 40.0:
                    state = "WATCH"

                elif aligned >= 55.0 and reliability >= 55.0:
                    state = "ACTIONABLE"

                elif aligned <= 45.0 and reliability >= 55.0:
                    state = "WAIT_FOR_CONFIRMATION"

                else:
                    state = "WATCH"

        else:
            state = "ACTIONABLE"

    elif adjusted_score >= 56.0:
        state = "WATCH"

    elif adjusted_score >= 45.0:
        state = "NEUTRAL"

    reasons.insert(
        0,
        (
            f"Adjusted Orion Score {adjusted_score:.1f}/100 "
            f"(raw {raw_score:.1f}/100)."
        ),
    )

    if manipulation_risk is not None:
        reasons.append(
            (
                f"Market-integrity risk {manipulation_risk:.1f}/100 is already "
                "reflected in adjusted Orion Score and is not double-counted."
            )
        )

    return {
        "available": True,
        "opportunity_rank_score": round(
            rank_score,
            1,
        ),
        "opportunity_state": state,
        "eligible": eligible,
        "minimum_pick_score": float(
            minimum_pick_score
        ),
        "raw_orion_score": round(
            raw_score,
            1,
        ),
        "adjusted_orion_score": round(
            adjusted_score,
            1,
        ),
        "probability_adjustment": round(
            probability_adjustment,
            2,
        ),
        "agreement_adjustment": round(
            agreement_adjustment,
            2,
        ),
        "selected_probability": probability,
        "manipulation_risk": manipulation_risk,
        "reasons": reasons,
        "semantics": (
            "Opportunity Rank Score is a deterministic scanner ordering score. "
            "It is NOT probability of profit or future price movement. "
            "Adjusted Orion Score remains the dominant input; usable V3.1 "
            "evidence can only make a small ranking adjustment."
        ),
    }


def _self_test() -> Dict[str, Any]:
    bullish = {
        "symbol": "TEST",
        "horizon": "day",
        "orion_score": 76.0,
        "raw_orion_score": 76.0,
        "adjusted_orion_score": 74.0,
        "manipulation_risk": 18.0,
        "bias": "bullish",
        "probability_profile_validated_for_symbol": True,
        "probability_1h": {
            "available": True,
            "probability_up": 61.0,
            "probability_down": 39.0,
            "direction": "bullish",
            "reliability_score": 72.0,
            "reliability_label": "trusted",
            "display_policy": "show_probability",
            "agreement": "directional_agreement",
            "profile_validated_for_symbol": True,
        },
    }

    generic = {
        **bullish,
        "symbol": "UNKNOWN",
        "probability_profile_validated_for_symbol": False,
        "probability_1h": {
            **bullish["probability_1h"],
            "profile_validated_for_symbol": False,
        },
    }

    return {
        "validated": build_opportunity_ranking(
            bullish
        ),
        "generic": build_opportunity_ranking(
            generic
        ),
    }


if __name__ == "__main__":
    import json

    print(
        json.dumps(
            _self_test(),
            indent=2,
            ensure_ascii=False,
        )
    )
