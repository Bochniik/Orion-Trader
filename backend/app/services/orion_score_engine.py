from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


# =============================================================================
# MODELS
# =============================================================================

@dataclass
class OrionScoreResult:
    horizon: str

    score: float
    label: str

    bias: str

    technical_component: float
    news_component: float
    market_component: float
    sector_component: float
    thematic_component: float
    fundamental_component: float
    calibration_component: float

    calibration_used: bool
    calibration_weight: float

    reasons: Dict[str, float]
    warnings: list[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# HELPERS
# =============================================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        if value is None:
            return default

        result = float(value)

        if math.isnan(result) or math.isinf(result):
            return default

        return result

    except (TypeError, ValueError):
        return default


def _clamp(
    value: float,
    low: float,
    high: float,
) -> float:
    return max(
        low,
        min(
            high,
            value,
        ),
    )


def _signed_to_0_100(
    value: float,
) -> float:
    """
    Convert signed score -1..+1 into 0..100.

    -1.0 ->   0
     0.0 ->  50
    +1.0 -> 100
    """

    value = _clamp(
        value,
        -1.0,
        1.0,
    )

    return (
        value + 1.0
    ) * 50.0


def _quality_to_signed(
    quality_score: float,
    bias: str,
) -> float:
    """
    Convert deterministic setup quality into signed directional evidence.

    Example:
        quality 80 + bullish -> +0.80
        quality 80 + bearish -> -0.80
        neutral              ->  0.00
    """

    normalized = _clamp(
        quality_score / 100.0,
        0.0,
        1.0,
    )

    bias = str(
        bias or ""
    ).strip().lower()

    if bias == "bullish":
        return normalized

    if bias == "bearish":
        return -normalized

    return 0.0


def _score_label(
    score: float,
) -> str:
    """
    User-facing interpretation of Orion Score.

    Orion Score means suitability for buying the stock
    for the selected horizon.

    It is NOT probability of profit.
    """

    if score >= 85:
        return "strong_buy_candidate"

    if score >= 70:
        return "buy_candidate"

    if score >= 56:
        return "interesting"

    if score >= 45:
        return "neutral"

    if score >= 25:
        return "avoid"

    return "strong_avoid"


# =============================================================================
# CALIBRATION WEIGHT
# =============================================================================

def _calibration_weight(
    calibration: Optional[Dict[str, Any]],
) -> float:
    """
    Historical calibration is allowed to influence Orion Score only after
    enough resolved historical observations exist.

        < 30 samples  -> disabled
        30-99         -> 25% of configured calibration weight
        100-299       -> 60%
        300+          -> full configured weight
    """

    if not calibration:
        return 0.0

    if not calibration.get(
        "available",
        False,
    ):
        return 0.0

    sample_size = int(
        calibration.get(
            "sample_size",
            0,
        )
        or 0
    )

    if sample_size < 30:
        return 0.0

    if sample_size < 100:
        return 0.25

    if sample_size < 300:
        return 0.60

    return 1.0


# =============================================================================
# HORIZON WEIGHTS
# =============================================================================

DAY_WEIGHTS = {
    "technical": 0.36,
    "news": 0.18,
    "market": 0.12,
    "sector": 0.10,
    "thematic": 0.12,
    "fundamental": 0.02,
    "calibration": 0.10,
}


SWING_WEIGHTS = {
    "technical": 0.32,
    "news": 0.10,
    "market": 0.12,
    "sector": 0.12,
    "thematic": 0.15,
    "fundamental": 0.09,
    "calibration": 0.10,
}


LONG_TERM_WEIGHTS = {
    "technical": 0.10,
    "news": 0.04,
    "market": 0.08,
    "sector": 0.08,
    "thematic": 0.08,
    "fundamental": 0.52,
    "calibration": 0.10,
}


# =============================================================================
# BUY-SUITABILITY DIRECTION RULES
# =============================================================================

def _apply_buy_suitability_rules(
    *,
    score: float,
    bias: str,
    quality_score: float,
    horizon: str,
    fundamental_signed: float,
) -> float:
    """
    Convert the raw composite into a score whose meaning is explicitly:

        "How suitable is buying this stock for this horizon?"

    This prevents bullish external context from making a bearish stock look
    like a good buy.

    Rules deliberately remain transparent and deterministic.
    """

    bias = str(
        bias or "neutral"
    ).strip().lower()

    score = _clamp(
        score,
        0.0,
        100.0,
    )

    quality_score = _clamp(
        quality_score,
        0.0,
        100.0,
    )

    # =========================================================================
    # BEARISH
    # =========================================================================
    #
    # A bearish setup cannot be labelled as Interesting / Buy Candidate.
    #
    # Stronger bearish setup quality lowers the maximum allowed buy score.
    # =========================================================================

    if bias == "bearish":

        if quality_score >= 70:
            max_score = 24.0

        elif quality_score >= 50:
            max_score = 32.0

        elif quality_score >= 30:
            max_score = 39.0

        else:
            max_score = 44.0

        score = min(
            score,
            max_score,
        )

    # =========================================================================
    # NEUTRAL
    # =========================================================================
    #
    # External market/theme strength may make a neutral setup interesting,
    # but neutral technical evidence alone cannot become a Buy Candidate.
    # =========================================================================

    elif bias == "neutral":

        score = min(
            score,
            69.0,
        )

        # Weak neutral setup should remain close to WAIT.
        if quality_score < 25:
            score = min(
                score,
                55.0,
            )

    # =========================================================================
    # BULLISH
    # =========================================================================
    #
    # Bullish direction can access the whole range, but a very weak bullish
    # setup should not become Strong Buy solely because the broad market or
    # theme is bullish.
    # =========================================================================

    elif bias == "bullish":

        if quality_score < 20:
            score = min(
                score,
                64.0,
            )

        elif quality_score < 35:
            score = min(
                score,
                74.0,
            )

    # =========================================================================
    # LONG-TERM FUNDAMENTAL GUARDRAIL
    # =========================================================================
    #
    # Even bullish technicals should not create a very strong Long-Term buy
    # rating when profile-adjusted fundamentals are clearly weak.
    # =========================================================================

    if horizon == "long_term":

        if fundamental_signed <= -0.70:
            score = min(
                score,
                35.0,
            )

        elif fundamental_signed <= -0.40:
            score = min(
                score,
                49.0,
            )

        elif fundamental_signed <= -0.20:
            score = min(
                score,
                59.0,
            )

    return _clamp(
        score,
        0.0,
        100.0,
    )


# =============================================================================
# MAIN ENGINE
# =============================================================================

def calculate_orion_score(
    analysis_result: Dict[str, Any],
    *,
    thematic_context: Optional[Dict[str, Any]] = None,
    calibration: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    warnings: list[str] = []

    horizon = str(
        analysis_result.get(
            "horizon",
            ""
        )
    ).strip().lower()

    analysis = analysis_result.get(
        "analysis",
        {}
    )

    if not isinstance(
        analysis,
        dict,
    ):
        analysis = {}

    context = analysis_result.get(
        "context",
        {}
    )

    if not isinstance(
        context,
        dict,
    ):
        context = {}

    fundamentals = analysis_result.get(
        "fundamentals",
        {}
    )

    if not isinstance(
        fundamentals,
        dict,
    ):
        fundamentals = {}

    # =========================================================================
    # HORIZON WEIGHTS
    # =========================================================================

    if horizon == "day":
        weights = dict(
            DAY_WEIGHTS
        )

    elif horizon == "swing":
        weights = dict(
            SWING_WEIGHTS
        )

    elif horizon in {
        "long_term",
        "long-term",
        "longterm",
    }:
        horizon = "long_term"

        weights = dict(
            LONG_TERM_WEIGHTS
        )

    else:
        raise ValueError(
            f"Unsupported horizon: {horizon}"
        )

    # =========================================================================
    # TECHNICAL COMPONENT
    # =========================================================================

    quality_score = _safe_float(
        analysis.get(
            "quality_score"
        ),
        0.0,
    )

    bias = str(
        analysis.get(
            "bias",
            "neutral"
        )
    ).strip().lower()

    technical_signed = _quality_to_signed(
        quality_score,
        bias,
    )

    # =========================================================================
    # NEWS
    # =========================================================================

    news_signed = _clamp(
        _safe_float(
            context.get(
                "news_score"
            ),
            0.0,
        ),
        -1.0,
        1.0,
    )

    # =========================================================================
    # MARKET
    # =========================================================================

    market_signed = _clamp(
        _safe_float(
            context.get(
                "market_score"
            ),
            0.0,
        ),
        -1.0,
        1.0,
    )

    # =========================================================================
    # SECTOR
    # =========================================================================

    sector_signed = _clamp(
        _safe_float(
            context.get(
                "sector_score"
            ),
            0.0,
        ),
        -1.0,
        1.0,
    )

    # =========================================================================
    # THEMATIC
    # =========================================================================

    thematic_signed = 0.0

    if thematic_context:

        thematic_signed = _clamp(
            _safe_float(
                thematic_context.get(
                    "thematic_score",
                    thematic_context.get(
                        "combined_theme_score",
                        0.0,
                    ),
                ),
                0.0,
            ),
            -1.0,
            1.0,
        )

    else:
        warnings.append(
            "Thematic context unavailable; thematic contribution is neutral."
        )

    # =========================================================================
    # FUNDAMENTALS
    # =========================================================================

    fundamental_signed = _clamp(
        _safe_float(
            fundamentals.get(
                "profile_adjusted_fundamental_score"
            ),
            0.0,
        ),
        -1.0,
        1.0,
    )

    if (
        horizon == "long_term"
        and not fundamentals
    ):
        warnings.append(
            "Long-term fundamentals unavailable."
        )

    # =========================================================================
    # HISTORICAL CALIBRATION
    # =========================================================================

    calibration_signed = 0.0

    calibration_multiplier = (
        _calibration_weight(
            calibration
        )
    )

    calibration_used = (
        calibration_multiplier > 0
    )

    if calibration_used:

        probability = _safe_float(
            calibration.get(
                "probability"
            ),
            0.5,
        )

        probability = _clamp(
            probability,
            0.0,
            1.0,
        )

        calibration_signed = (
            probability - 0.5
        ) * 2.0

    # =========================================================================
    # DYNAMIC CALIBRATION WEIGHT
    # =========================================================================

    base_calibration_weight = (
        weights[
            "calibration"
        ]
    )

    effective_calibration_weight = (
        base_calibration_weight
        * calibration_multiplier
    )

    missing_calibration_weight = (
        base_calibration_weight
        - effective_calibration_weight
    )

    if missing_calibration_weight > 0:

        if horizon == "long_term":

            weights[
                "fundamental"
            ] += (
                missing_calibration_weight
                * 0.75
            )

            weights[
                "technical"
            ] += (
                missing_calibration_weight
                * 0.25
            )

        else:

            weights[
                "technical"
            ] += (
                missing_calibration_weight
                * 0.70
            )

            weights[
                "market"
            ] += (
                missing_calibration_weight
                * 0.15
            )

            weights[
                "sector"
            ] += (
                missing_calibration_weight
                * 0.15
            )

    weights[
        "calibration"
    ] = (
        effective_calibration_weight
    )

    # =========================================================================
    # RAW COMPOSITE
    # =========================================================================

    components = {
        "technical": technical_signed,
        "news": news_signed,
        "market": market_signed,
        "sector": sector_signed,
        "thematic": thematic_signed,
        "fundamental": fundamental_signed,
        "calibration": calibration_signed,
    }

    raw_signed_score = 0.0
    total_weight = 0.0

    for name, value in components.items():

        weight = _safe_float(
            weights.get(
                name
            ),
            0.0,
        )

        raw_signed_score += (
            value
            * weight
        )

        total_weight += (
            weight
        )

    if total_weight > 0:

        raw_signed_score /= (
            total_weight
        )

    raw_signed_score = _clamp(
        raw_signed_score,
        -1.0,
        1.0,
    )

    # =========================================================================
    # LONG-TERM FUNDAMENTAL ADJUSTMENTS
    # =========================================================================

    if (
        horizon == "long_term"
        and fundamental_signed <= -0.50
    ):
        raw_signed_score -= (
            0.10
        )

    if (
        horizon == "long_term"
        and fundamental_signed >= 0.70
        and bias != "bearish"
    ):
        raw_signed_score += (
            0.04
        )

    raw_signed_score = _clamp(
        raw_signed_score,
        -1.0,
        1.0,
    )

    # =========================================================================
    # RAW 0-100 SCORE
    # =========================================================================

    raw_score = _signed_to_0_100(
        raw_signed_score
    )

    raw_score = _clamp(
        raw_score,
        0.0,
        100.0,
    )

    # =========================================================================
    # BUY-SUITABILITY RULES
    # =========================================================================

    score = _apply_buy_suitability_rules(
        score=raw_score,

        bias=bias,

        quality_score=(
            quality_score
        ),

        horizon=horizon,

        fundamental_signed=(
            fundamental_signed
        ),
    )

    score = round(
        score,
        1,
    )

    label = _score_label(
        score
    )

    # =========================================================================
    # USER-FACING COMPONENT SCORES
    #
    # Retained for debugging / AI explanation.
    # Normal UI can hide these.
    # =========================================================================

    technical_component = _signed_to_0_100(
        technical_signed
    )

    news_component = _signed_to_0_100(
        news_signed
    )

    market_component = _signed_to_0_100(
        market_signed
    )

    sector_component = _signed_to_0_100(
        sector_signed
    )

    thematic_component = _signed_to_0_100(
        thematic_signed
    )

    fundamental_component = _signed_to_0_100(
        fundamental_signed
    )

    calibration_component = _signed_to_0_100(
        calibration_signed
    )

    return OrionScoreResult(
        horizon=horizon,

        score=score,
        label=label,

        bias=bias,

        technical_component=round(
            technical_component,
            1,
        ),

        news_component=round(
            news_component,
            1,
        ),

        market_component=round(
            market_component,
            1,
        ),

        sector_component=round(
            sector_component,
            1,
        ),

        thematic_component=round(
            thematic_component,
            1,
        ),

        fundamental_component=round(
            fundamental_component,
            1,
        ),

        calibration_component=round(
            calibration_component,
            1,
        ),

        calibration_used=(
            calibration_used
        ),

        calibration_weight=round(
            effective_calibration_weight,
            4,
        ),

        reasons={
            "technical_signed": round(
                technical_signed,
                4,
            ),

            "news_signed": round(
                news_signed,
                4,
            ),

            "market_signed": round(
                market_signed,
                4,
            ),

            "sector_signed": round(
                sector_signed,
                4,
            ),

            "thematic_signed": round(
                thematic_signed,
                4,
            ),

            "fundamental_signed": round(
                fundamental_signed,
                4,
            ),

            "calibration_signed": round(
                calibration_signed,
                4,
            ),

            "raw_composite_signed": round(
                raw_signed_score,
                4,
            ),

            "raw_score_before_buy_rules": round(
                raw_score,
                1,
            ),
        },

        warnings=warnings,
    ).to_dict()


# =============================================================================
# COMPACT USER OUTPUT
# =============================================================================

def compact_orion_score(
    result: Dict[str, Any],
) -> Dict[str, Any]:

    return {
        "orion_score": result.get(
            "score"
        ),

        "orion_label": result.get(
            "label"
        ),

        "bias": result.get(
            "bias"
        ),

        "horizon": result.get(
            "horizon"
        ),
    }


# =============================================================================
# MANUAL TEST
# =============================================================================

if __name__ == "__main__":

    import json

    tests = [
        {
            "name": "Bullish Day",
            "analysis_result": {
                "horizon": "day",

                "analysis": {
                    "bias": "bullish",
                    "quality_score": 76.0,
                },

                "context": {
                    "news_score": 0.20,
                    "market_score": 0.62,
                    "sector_score": 0.59,
                },

                "fundamentals": {
                    "profile_adjusted_fundamental_score": 0.80,
                },
            },

            "theme": {
                "thematic_score": 0.72,
            },
        },

        {
            "name": "Weak Bearish Day",
            "analysis_result": {
                "horizon": "day",

                "analysis": {
                    "bias": "bearish",
                    "quality_score": 22.0,
                },

                "context": {
                    "news_score": 0.14,
                    "market_score": 0.63,
                    "sector_score": 0.60,
                },

                "fundamentals": {
                    "profile_adjusted_fundamental_score": 0.80,
                },
            },

            "theme": {
                "thematic_score": 0.04,
            },
        },

        {
            "name": "Bearish Swing",
            "analysis_result": {
                "horizon": "swing",

                "analysis": {
                    "bias": "bearish",
                    "quality_score": 35.0,
                },

                "context": {
                    "news_score": 0.0,
                    "market_score": 0.63,
                    "sector_score": 0.60,
                },

                "fundamentals": {
                    "profile_adjusted_fundamental_score": 0.10,
                },
            },

            "theme": {
                "thematic_score": 0.14,
            },
        },
    ]

    output = {}

    for test in tests:

        output[
            test[
                "name"
            ]
        ] = calculate_orion_score(
            test[
                "analysis_result"
            ],

            thematic_context=(
                test[
                    "theme"
                ]
            ),

            calibration=None,
        )

    print(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        )
    )