from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.fundamental_data_engine import (
    get_fundamental_strategy_data,
)

from app.services.fundamental_profile_engine import (
    calculate_profile_adjusted_score,
    PROFILES,
)

from app.services.strategy_context_engine import (
    analyze_strategy_with_context,
    build_orion_ai_strategy_context,
)

from app.services.technical_data_engine import (
    get_technical_strategy_data,
)

from app.services.thematic_regime_engine import (
    get_strategy_thematic_context,
)

from app.services.orion_score_engine import (
    calculate_orion_score,
)

from app.services.probability_calibration_engine import (
    calibrated_probability,
)

from app.services.market_integrity_service import (
    analyze_ticker_market_integrity,
)

from app.services.orion_integrity_adjustment_engine import (
    apply_integrity_adjustment,
)

from app.services.intraday_probability_engine import (
    estimate_intraday_probabilities,
)

# =============================================================================
# THEMATIC OVERRIDES
# =============================================================================

# Some companies cannot be reliably classified from Yahoo's broad
# sector/industry names alone.
#
# Example:
#   Coinbase may be classified under Financial Services / Capital Markets,
#   but for Orion's analytical purposes its economic exposure is strongly
#   crypto-related.
#
# These overrides affect the FUNDAMENTAL PROFILE, not the factual sector
# returned by the data provider.

THEMATIC_PROFILE_OVERRIDES: Dict[str, str] = {

    # -------------------------------------------------------------------------
    # CRYPTO
    # -------------------------------------------------------------------------

    "COIN": "crypto",
    "MARA": "crypto",
    "RIOT": "crypto",
    "CLSK": "crypto",
    "HUT": "crypto",
    "IREN": "crypto",
    "CIFR": "crypto",
    "BTDR": "crypto",
    "WULF": "crypto",

    # -------------------------------------------------------------------------
    # QUANTUM COMPUTING
    # -------------------------------------------------------------------------

    "IONQ": "quantum_computing",
    "RGTI": "quantum_computing",
    "QBTS": "quantum_computing",
    "QUBT": "quantum_computing",
}


# =============================================================================
# SECTOR -> ETF
# =============================================================================

SECTOR_TO_ETF: Dict[str, str] = {
    "technology": "XLK",
    "information technology": "XLK",

    "financial services": "XLF",
    "financials": "XLF",
    "financial": "XLF",

    "healthcare": "XLV",
    "health care": "XLV",

    "energy": "XLE",

    "industrials": "XLI",
    "industrial": "XLI",

    "consumer cyclical": "XLY",
    "consumer discretionary": "XLY",

    "consumer defensive": "XLP",
    "consumer staples": "XLP",

    "utilities": "XLU",

    "basic materials": "XLB",
    "materials": "XLB",

    "real estate": "XLRE",

    "communication services": "XLC",
}


# =============================================================================
# THEMATIC BENCHMARKS
# =============================================================================

# These are context benchmarks.
# They do not replace the broader SPY / QQQ / sector analysis.

THEMATIC_BENCHMARKS: Dict[str, Dict[str, str]] = {

    "crypto": {
        "benchmark": "IBIT",
        "label": "Bitcoin / Crypto Proxy",
    },

    "quantum_computing": {
        # QTUM contains quantum / advanced computing exposure.
        "benchmark": "QTUM",
        "label": "Quantum / Advanced Computing",
    },

    "fuels_energy": {
        "benchmark": "XLE",
        "label": "Energy",
    },

    "fashion": {
        "benchmark": "XLY",
        "label": "Consumer Discretionary",
    },

    "cosmetics": {
        "benchmark": "XLP",
        "label": "Consumer / Staples Proxy",
    },

    "engineering": {
        "benchmark": "XLI",
        "label": "Industrials",
    },

    "food": {
        "benchmark": "XLP",
        "label": "Consumer Staples",
    },

    "semiconductors": {
        "benchmark": "SMH",
        "label": "Semiconductors",
    },

    "banks": {
        "benchmark": "XLF",
        "label": "Financials",
    },

    "biotech": {
        "benchmark": "XBI",
        "label": "Biotechnology",
    },
}


# =============================================================================
# HELPERS
# =============================================================================

def _utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _normalize_horizon(
    horizon: str,
) -> str:

    value = str(
        horizon
    ).strip().lower()

    aliases = {
        "intraday": "day",
        "daytrade": "day",
        "day_trade": "day",
        "day-trading": "day",
        "day trading": "day",

        "swingtrade": "swing",
        "swing_trade": "swing",
        "swing-trading": "swing",
        "swing trading": "swing",

        "longterm": "long_term",
        "long-term": "long_term",
        "long term": "long_term",
        "investment": "long_term",
        "investing": "long_term",
    }

    return aliases.get(
        value,
        value,
    )


def _normalize_text(
    value: Optional[str],
) -> str:

    if not value:
        return ""

    return (
        str(value)
        .strip()
        .lower()
    )


def _safe_dict(
    value: Any,
) -> Dict[str, Any]:

    if isinstance(
        value,
        dict,
    ):
        return dict(value)

    return {}


def _resolve_sector_etf(
    sector: Optional[str],
) -> Optional[str]:

    normalized = _normalize_text(
        sector
    )

    return SECTOR_TO_ETF.get(
        normalized
    )


# =============================================================================
# PROFILE OVERRIDE
# =============================================================================

def apply_thematic_profile_override(
    symbol: str,
    fundamentals: Dict[str, Any],
) -> Dict[str, Any]:

    symbol = symbol.upper().strip()

    override = (
        THEMATIC_PROFILE_OVERRIDES.get(
            symbol
        )
    )

    if not override:
        return fundamentals

    profile = PROFILES.get(
        override
    )

    if profile is None:
        return fundamentals

    result = dict(
        fundamentals
    )

    result[
        "fundamental_profile"
    ] = profile.profile

    result[
        "fundamental_profile_label"
    ] = profile.label

    result[
        "fundamental_profile_weights"
    ] = {
        "growth": (
            profile.growth_weight
        ),

        "quality": (
            profile.quality_weight
        ),

        "balance_sheet": (
            profile.balance_sheet_weight
        ),

        "valuation": (
            profile.valuation_weight
        ),

        "profitability": (
            profile.profitability_weight
        ),

        "earnings_revision": (
            profile.earnings_revision_weight
        ),
    }

    result[
        "preferred_metrics"
    ] = list(
        profile.preferred_metrics
    )

    result[
        "reduced_metrics"
    ] = list(
        profile.reduced_metrics
    )

    result[
        "ignored_metrics"
    ] = list(
        profile.ignored_metrics
    )

    result[
        "profile_notes"
    ] = list(
        profile.notes
    )

    result[
        "profile_override"
    ] = True

    return result


# =============================================================================
# FUNDAMENTALS
# =============================================================================

def load_fundamental_context(
    symbol: str,
) -> Dict[str, Any]:

    warnings = []

    try:
        raw = (
            get_fundamental_strategy_data(
                symbol
            )
        )

    except Exception as exc:

        return {
            "available": False,

            "symbol": symbol,

            "sector": None,
            "industry": None,

            "fundamental_profile": (
                THEMATIC_PROFILE_OVERRIDES.get(
                    symbol.upper()
                )
            ),

            "profile_adjusted_fundamental_score": 0.0,

            "warnings": [
                f"Fundamental data unavailable: {exc}"
            ],
        }

    try:
        profiled = (
            calculate_profile_adjusted_score(
                raw
            )
        )

    except Exception as exc:

        profiled = dict(
            raw
        )

        profiled[
            "profile_adjusted_fundamental_score"
        ] = 0.0

        warnings.append(
            f"Fundamental profile calculation failed: {exc}"
        )

    # Apply explicit thematic classifications.
    profiled = (
        apply_thematic_profile_override(
            symbol,
            profiled,
        )
    )

    # If an override changed the profile,
    # recalculate its weighted score.
    if profiled.get(
        "profile_override"
    ):

        weights = profiled.get(
            "fundamental_profile_weights",
            {},
        )

        growth = float(
            profiled.get(
                "growth_score",
                0.0,
            )
            or 0.0
        )

        quality = float(
            profiled.get(
                "business_quality_score",
                0.0,
            )
            or 0.0
        )

        balance = float(
            profiled.get(
                "balance_sheet_score",
                0.0,
            )
            or 0.0
        )

        valuation = float(
            profiled.get(
                "valuation_score",
                0.0,
            )
            or 0.0
        )

        revisions = float(
            profiled.get(
                "earnings_revision_score",
                0.0,
            )
            or 0.0
        )

        profitability = quality

        weighted_sum = (
            growth
            * float(
                weights.get(
                    "growth",
                    0.0,
                )
            )

            + quality
            * float(
                weights.get(
                    "quality",
                    0.0,
                )
            )

            + balance
            * float(
                weights.get(
                    "balance_sheet",
                    0.0,
                )
            )

            + valuation
            * float(
                weights.get(
                    "valuation",
                    0.0,
                )
            )

            + profitability
            * float(
                weights.get(
                    "profitability",
                    0.0,
                )
            )

            + revisions
            * float(
                weights.get(
                    "earnings_revision",
                    0.0,
                )
            )
        )

        total_weight = sum(
            float(value)
            for value
            in weights.values()
        )

        if total_weight > 0:

            final_score = (
                weighted_sum
                / total_weight
            )

        else:
            final_score = 0.0

        final_score = max(
            -1.0,
            min(
                1.0,
                final_score,
            ),
        )

        profiled[
            "profile_adjusted_fundamental_score"
        ] = round(
            final_score,
            4,
        )

    profiled[
        "available"
    ] = True

    existing_warnings = (
        profiled.get(
            "warnings",
            []
        )
    )

    profiled[
        "warnings"
    ] = (
        existing_warnings
        + warnings
    )

    return profiled


# =============================================================================
# PREPARE LONG-TERM STRATEGY INPUT
# =============================================================================

def merge_long_term_data(
    technical: Dict[str, Any],
    fundamentals: Dict[str, Any],
) -> Dict[str, Any]:

    result = dict(
        technical
    )

    # -------------------------------------------------------------------------
    # Raw fundamental values expected by strategy_engine
    # -------------------------------------------------------------------------

    fields = [
        "revenue_growth",
        "eps_growth",
        "free_cash_flow_growth",

        "roic",
        "roe",

        "debt_to_equity",

        "valuation_score",
        "earnings_revision_score",
        "balance_sheet_score",
        "business_quality_score",
        "growth_score",

        "profile_adjusted_fundamental_score",

        "gross_margin",
        "operating_margin",
        "profit_margin",

        "free_cash_flow",
        "free_cash_flow_yield",

        "trailing_pe",
        "forward_pe",
        "peg_ratio",
        "price_to_sales",
        "price_to_book",
    ]

    for field in fields:

        if field in fundamentals:

            result[
                field
            ] = fundamentals.get(
                field
            )

    result[
        "fundamental_profile"
    ] = fundamentals.get(
        "fundamental_profile"
    )

    result[
        "fundamental_profile_label"
    ] = fundamentals.get(
        "fundamental_profile_label"
    )

    result[
        "fundamental_profile_weights"
    ] = fundamentals.get(
        "fundamental_profile_weights",
        {},
    )

    return result


# =============================================================================
# THEMATIC CONTEXT
# =============================================================================

def get_thematic_context(
    profile: Optional[str],
) -> Dict[str, Any]:

    if not profile:

        return {
            "profile": None,
            "benchmark": None,
            "label": None,
        }

    theme = (
        THEMATIC_BENCHMARKS.get(
            profile
        )
    )

    if not theme:

        return {
            "profile": profile,
            "benchmark": None,
            "label": None,
        }

    return {
        "profile": profile,

        "benchmark": theme.get(
            "benchmark"
        ),

        "label": theme.get(
            "label"
        ),
    }


# =============================================================================
# MAIN PUBLIC API
# =============================================================================

def analyze_stock(
    symbol: str,
    horizon: str,
    *,
    sector: Optional[str] = None,
    sector_etf: Optional[str] = None,
    include_articles: bool = True,
    include_market_components: bool = True,
    include_fundamentals: bool = True,
) -> Dict[str, Any]:
    """
    Unified OrionTrader analytical pipeline.

    Pipeline:
        technical data
            +
        company / fundamental profile
            +
        news / catalysts
            +
        broad market regime
            +
        sector regime
            +
        thematic regime
            ↓
        deterministic strategy engine
            ↓
        historical calibration, when enough resolved samples exist
            ↓
        Orion Score (0-100 decision score; NOT probability)
            ↓
        structured Orion AI context

    The function does not execute trades.
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError(
            "Symbol cannot be empty."
        )

    horizon = _normalize_horizon(
        horizon
    )

    if horizon not in {
        "day",
        "swing",
        "long_term",
    }:
        raise ValueError(
            f"Unsupported horizon: {horizon}"
        )

    pipeline_warnings = []

    # =========================================================================
    # 1. TECHNICAL DATA
    # =========================================================================

    technical = (
        get_technical_strategy_data(
            symbol,
            horizon,
        )
    )

    # =========================================================================
    # 2. FUNDAMENTAL / COMPANY CONTEXT
    #
    # Fundamentals are loaded for every horizon because they also provide
    # company name, sector, industry and the fundamental profile.
    #
    # Day/Swing strategy weighting remains controlled by strategy_engine and
    # orion_score_engine; loading the data here does not make fundamentals a
    # dominant Day input.
    # =========================================================================

    fundamentals = (
        load_fundamental_context(
            symbol
        )
    )

    resolved_sector = (
        sector
        or fundamentals.get(
            "sector"
        )
    )

    resolved_sector_etf = (
        sector_etf
        or _resolve_sector_etf(
            resolved_sector
        )
    )

    if (
        resolved_sector
        and resolved_sector_etf is None
    ):
        pipeline_warnings.append(
            f"No automatic ETF mapping "
            f"for sector '{resolved_sector}'."
        )

    # =========================================================================
    # 3. BUILD STRATEGY INPUT
    # =========================================================================

    if horizon == "long_term":
        strategy_data = (
            merge_long_term_data(
                technical,
                fundamentals,
            )
        )

    else:
        strategy_data = dict(
            technical
        )

    # =========================================================================
    # 4. NEWS + MARKET + SECTOR + DETERMINISTIC STRATEGY
    # =========================================================================

    combined = (
        analyze_strategy_with_context(
            symbol,
            horizon,
            strategy_data,

            sector=resolved_sector,

            sector_etf=(
                resolved_sector_etf
            ),

            include_articles=(
                include_articles
            ),

            include_market_components=(
                include_market_components
            ),
        )
    )

    # =========================================================================
    # 5. THEMATIC CONTEXT
    # =========================================================================

    profile = fundamentals.get(
        "fundamental_profile"
    )

    # Older benchmark metadata is kept for compatibility with existing callers.
    thematic = get_thematic_context(
        profile
    )

    # New live thematic regime uses multiple market proxies where relevant:
    # AI, semiconductors, crypto, quantum, biotech, energy, etc.
    try:
        thematic_regime = (
            get_strategy_thematic_context(
                symbol,
                fundamental_profile=profile,
            )
        )

    except Exception as exc:
        thematic_regime = {
            "thematic_score": 0.0,
            "primary_theme": None,
            "primary_theme_score": 0.0,
            "primary_theme_regime": "neutral",
            "thematic_components": [],
            "thematic_warnings": [
                f"Thematic regime unavailable: {exc}"
            ],
        }

    # =========================================================================
    # 6. ADD COMPANY / DATA SOURCE METADATA
    # =========================================================================

    combined[
        "company"
    ] = {
        "name": (
            fundamentals.get(
                "company_name"
            )
        ),

        "sector": (
            resolved_sector
        ),

        "industry": (
            fundamentals.get(
                "industry"
            )
        ),

        "fundamental_profile": (
            profile
        ),

        "fundamental_profile_label": (
            fundamentals.get(
                "fundamental_profile_label"
            )
        ),

        "profile_override": (
            fundamentals.get(
                "profile_override",
                False,
            )
        ),
    }

    combined[
        "thematic_context"
    ] = thematic

    combined[
        "thematic_regime"
    ] = thematic_regime

    combined[
        "technical"
    ] = technical

    if include_fundamentals:
        combined[
            "fundamentals"
        ] = fundamentals

    else:
        # Compact/scanner calls still need the profile-adjusted score for
        # Orion Score, but do not need the full fundamental payload.
        combined[
            "fundamentals"
        ] = {
            "available": (
                fundamentals.get(
                    "available",
                    False,
                )
            ),

            "fundamental_profile": (
                profile
            ),

            "fundamental_profile_label": (
                fundamentals.get(
                    "fundamental_profile_label"
                )
            ),

            "profile_adjusted_fundamental_score": (
                fundamentals.get(
                    "profile_adjusted_fundamental_score"
                )
            ),
        }

    # =========================================================================
    # 7. DATA QUALITY
    # =========================================================================

    news = _safe_dict(
        combined.get(
            "news"
        )
    )

    market = _safe_dict(
        combined.get(
            "market"
        )
    )

    data_quality_flags = {
        "technical_available": bool(
            technical
        ),

        "news_available": bool(
            news.get(
                "available",
                False,
            )
        ),

        "market_available": bool(
            market.get(
                "available",
                False,
            )
        ),

        "fundamentals_available": bool(
            fundamentals.get(
                "available",
                False,
            )
        ),

        "sector_known": bool(
            resolved_sector
        ),

        "sector_etf_known": bool(
            resolved_sector_etf
        ),
    }

    available_count = sum(
        1
        for value
        in data_quality_flags.values()
        if value
    )

    total_count = len(
        data_quality_flags
    )

    data_completeness = (
        available_count
        / total_count
        * 100.0
        if total_count > 0
        else 0.0
    )

    combined[
        "data_quality"
    ] = {
        **data_quality_flags,

        # Thematic context is optional because not every company belongs to
        # one of Orion's explicitly modelled themes.
        "thematic_available": bool(
            thematic_regime.get(
                "primary_theme"
            )
        ),

        "completeness_pct": round(
            data_completeness,
            1,
        ),
    }

    # =========================================================================
    # 8. HISTORICAL CALIBRATION
    # =========================================================================

    analysis_block = _safe_dict(
        combined.get(
            "analysis"
        )
    )

    context_block = _safe_dict(
        combined.get(
            "context"
        )
    )

    quality_score = (
        analysis_block.get(
            "quality_score"
        )
    )

    bias = str(
        analysis_block.get(
            "bias",
            "neutral",
        )
        or "neutral"
    ).strip().lower()

    strategy_name = (
        analysis_block.get(
            "strategy"
        )
    )

    market_regime_name = (
        context_block.get(
            "market_regime"
        )
    )

    calibration = {
        "available": False,
        "probability": None,
        "probability_pct": None,
        "sample_size": 0,
        "warning": (
            "Historical calibration is not available "
            "for this setup yet."
        ),
    }

    if (
        quality_score is not None
        and bias in {
            "bullish",
            "bearish",
        }
    ):
        try:
            calibration = (
                calibrated_probability(
                    quality_score=float(
                        quality_score
                    ),

                    horizon=horizon,

                    direction=bias,

                    strategy=(
                        strategy_name
                    ),

                    market_regime=(
                        market_regime_name
                    ),
                )
            )

        except Exception as exc:
            calibration = {
                "available": False,
                "probability": None,
                "probability_pct": None,
                "sample_size": 0,
                "warning": (
                    f"Historical calibration failed: {exc}"
                ),
            }

    combined[
        "historical_calibration"
    ] = calibration

    # =========================================================================
    # 9. FINAL ORION SCORE
    #
    # This is the single user-facing decision score.
    # It is intentionally NOT labelled as a probability.
    # =========================================================================

    try:
        orion_score = (
            calculate_orion_score(
                combined,

                thematic_context=(
                    thematic_regime
                ),

                calibration=(
                    calibration
                ),
            )
        )

    except Exception as exc:
        orion_score = {
            "horizon": horizon,
            "score": 50.0,
            "label": "neutral",
            "bias": bias,
            "calibration_used": False,
            "calibration_weight": 0.0,
            "reasons": {},
            "warnings": [
                f"Orion Score failed: {exc}"
            ],
        }

    combined[
        "orion_score"
    ] = orion_score

    # =========================================================================
    # 9B. MARKET INTEGRITY / "MANIPULATION RISK" ADJUSTMENT
    #
    # Important semantics:
    # - market_integrity_risk is NOT probability that illegal manipulation
    #   occurred.
    # - raw Orion Score remains preserved.
    # - adjusted Orion Score is the raw suitability score after a transparent,
    #   horizon-aware penalty for anomalous / low-integrity price discovery.
    # =========================================================================

    try:
        market_integrity = analyze_ticker_market_integrity(
            symbol,
            news_score=(
                _safe_dict(
                    combined.get(
                        "context"
                    )
                ).get(
                    "news_score"
                )
            ),
        )

    except Exception as exc:
        market_integrity = {
            "ticker": symbol,
            "available": False,
            "market_integrity_risk": None,
            "market_integrity_score": None,
            "directional_distortion": None,
            "distortion_direction": None,
            "state": "UNAVAILABLE",
            "reasons": [],
            "warnings": [
                f"Market-integrity analysis failed: {type(exc).__name__}"
            ],
        }

    combined[
        "market_integrity"
    ] = market_integrity

    integrity_adjustment = apply_integrity_adjustment(
        orion_score.get(
            "score"
        ),
        market_integrity,
        horizon=horizon,
        bias=bias,
    )

    combined[
        "orion_integrity_adjustment"
    ] = integrity_adjustment

    combined[
        "raw_orion_score_value"
    ] = integrity_adjustment.get(
        "raw_orion_score"
    )

    combined[
        "manipulation_risk"
    ] = integrity_adjustment.get(
        "manipulation_risk"
    )

    combined[
        "manipulation_impact"
    ] = integrity_adjustment.get(
        "manipulation_impact"
    )

    combined[
        "adjusted_orion_score_value"
    ] = integrity_adjustment.get(
        "adjusted_orion_score"
    )

    combined[
        "adjusted_orion_label"
    ] = integrity_adjustment.get(
        "adjusted_label"
    )

    # =========================================================================
    # 9C. INTRADAY DIRECTIONAL PROBABILITIES
    # =========================================================================

    if horizon == "day":
        try:
            intraday_probability = estimate_intraday_probabilities(
                symbol
            )
        except Exception as exc:
            intraday_probability = {
                "symbol": symbol,
                "available": False,
                "horizons": {},
                "warnings": [
                    f"Intraday probability analysis failed: {type(exc).__name__}"
                ],
            }
    else:
        intraday_probability = {
            "symbol": symbol,
            "available": False,
            "horizons": {},
            "warnings": [],
        }

    combined[
        "intraday_probability"
    ] = intraday_probability

    # Convenience fields for API/front-end callers that only need the final
    # decision score without unpacking the detailed object.
    combined[
        "orion_score_value"
    ] = orion_score.get(
        "score"
    )

    combined[
        "orion_label"
    ] = orion_score.get(
        "label"
    )

    # =========================================================================
    # 10. WARNINGS
    # =========================================================================

    all_warnings = list(
        pipeline_warnings
    )

    all_warnings.extend(
        fundamentals.get(
            "warnings",
            [],
        )
    )

    all_warnings.extend(
        news.get(
            "warnings",
            [],
        )
    )

    all_warnings.extend(
        market.get(
            "warnings",
            [],
        )
    )

    # A missing optional theme mapping is not a pipeline failure. We only
    # surface thematic warnings when a theme exists or the thematic engine
    # itself failed.
    thematic_warnings = list(
        thematic_regime.get(
            "thematic_warnings",
            [],
        )
        or []
    )

    if (
        thematic_regime.get(
            "primary_theme"
        )
        or any(
            str(item).startswith(
                "Thematic regime unavailable:"
            )
            for item
            in thematic_warnings
        )
    ):
        all_warnings.extend(
            thematic_warnings
        )

    # Insufficient calibration data is expected during the data-collection
    # phase, so it is stored in historical_calibration but not promoted to a
    # general pipeline warning. Actual calibration failures are promoted.
    calibration_warning = (
        calibration.get(
            "warning"
        )
    )

    if (
        calibration_warning
        and str(
            calibration_warning
        ).startswith(
            "Historical calibration failed:"
        )
    ):
        all_warnings.append(
            calibration_warning
        )

    all_warnings.extend(
        orion_score.get(
            "warnings",
            [],
        )
        if isinstance(
            orion_score,
            dict,
        )
        else []
    )

    all_warnings.extend(
        market_integrity.get(
            "warnings",
            [],
        )
        if isinstance(
            market_integrity,
            dict,
        )
        else []
    )

    all_warnings.extend(
        intraday_probability.get(
            "warnings",
            [],
        )
        if isinstance(
            intraday_probability,
            dict,
        )
        else []
    )

    combined[
        "pipeline_warnings"
    ] = list(
        dict.fromkeys(
            str(warning)
            for warning
            in all_warnings
            if warning
        )
    )

    # =========================================================================
    # 11. ORION AI CONTEXT
    # =========================================================================

    try:
        orion_context = (
            build_orion_ai_strategy_context(
                combined
            )
        )

        orion_context[
            "company"
        ] = combined[
            "company"
        ]

        orion_context[
            "fundamental_context"
        ] = {
            "profile": (
                fundamentals.get(
                    "fundamental_profile"
                )
            ),

            "profile_label": (
                fundamentals.get(
                    "fundamental_profile_label"
                )
            ),

            "profile_adjusted_score": (
                fundamentals.get(
                    "profile_adjusted_fundamental_score"
                )
            ),

            "growth_score": (
                fundamentals.get(
                    "growth_score"
                )
            ),

            "quality_score": (
                fundamentals.get(
                    "business_quality_score"
                )
            ),

            "balance_sheet_score": (
                fundamentals.get(
                    "balance_sheet_score"
                )
            ),

            "valuation_score": (
                fundamentals.get(
                    "valuation_score"
                )
            ),

            "earnings_revision_score": (
                fundamentals.get(
                    "earnings_revision_score"
                )
            ),
        }

        # Keep both old benchmark metadata and the new computed regime.
        orion_context[
            "thematic_context"
        ] = thematic

        orion_context[
            "thematic_regime"
        ] = {
            "score": (
                thematic_regime.get(
                    "thematic_score"
                )
            ),

            "primary_theme": (
                thematic_regime.get(
                    "primary_theme"
                )
            ),

            "primary_theme_score": (
                thematic_regime.get(
                    "primary_theme_score"
                )
            ),

            "primary_theme_regime": (
                thematic_regime.get(
                    "primary_theme_regime"
                )
            ),

            "components": (
                thematic_regime.get(
                    "thematic_components",
                    [],
                )
            ),
        }

        orion_context[
            "orion_score"
        ] = {
            "score": (
                orion_score.get(
                    "score"
                )
            ),

            "label": (
                orion_score.get(
                    "label"
                )
            ),

            "bias": (
                orion_score.get(
                    "bias"
                )
            ),

            "meaning": (
                "Composite Orion decision score from 0 to 100. "
                "It is the primary user-facing suitability score "
                "for this horizon and is NOT a probability of "
                "future price movement or profit."
            ),
        }

        orion_context[
            "historical_calibration"
        ] = {
            "available": (
                calibration.get(
                    "available",
                    False,
                )
            ),

            "probability_pct": (
                calibration.get(
                    "probability_pct"
                )
                if calibration.get(
                    "available",
                    False,
                )
                else None
            ),

            "sample_size": (
                calibration.get(
                    "sample_size",
                    0,
                )
            ),

            "cohort_level": (
                calibration.get(
                    "cohort_level"
                )
            ),

            "definition": (
                calibration.get(
                    "definition"
                )
            ),
        }

        orion_context[
            "additional_rules"
        ] = [
            (
                "Use Orion Score as the primary user-facing "
                "decision score."
            ),

            (
                "Never describe Orion Score, deterministic quality "
                "score, market score, sector score, thematic score "
                "or news score as a probability."
            ),

            (
                "Historical probability may only be mentioned when "
                "historical_calibration.available is true."
            ),

            (
                "Do not manufacture fundamentals that are null "
                "or unavailable."
            ),

            (
                "For long-term analysis, explain valuation, growth, "
                "quality and balance-sheet signals separately."
            ),

            (
                "For Day analysis, prioritize intraday technicals, "
                "news catalysts, liquidity, market, sector and "
                "relevant thematic regime."
            ),

            (
                "For Swing analysis, prioritize multi-day trend, "
                "relative strength, breakout structure, market, "
                "sector and relevant thematic regime."
            ),

            (
                "For crypto-related equities, explicitly mention "
                "that underlying crypto-market exposure can dominate "
                "company-specific fundamentals."
            ),

            (
                "For quantum-computing equities, explicitly mention "
                "cash runway, dilution risk and technological or "
                "commercial milestones when the supplied data permits."
            ),

            (
                "For AI-related equities, distinguish broad AI theme "
                "strength from company-specific evidence. A bullish "
                "AI theme alone is not sufficient reason to buy."
            ),
        ]

        combined[
            "orion_ai_context"
        ] = orion_context

    except Exception as exc:
        combined[
            "orion_ai_context"
        ] = {}

        combined[
            "pipeline_warnings"
        ].append(
            f"Could not build Orion AI context: {exc}"
        )

        combined[
            "pipeline_warnings"
        ] = list(
            dict.fromkeys(
                combined[
                    "pipeline_warnings"
                ]
            )
        )

    # =========================================================================
    # 12. FINAL METADATA
    # =========================================================================

    generated_at = _utc_now_iso()

    combined[
        "generated_at"
    ] = generated_at

    combined[
        "pipeline"
    ] = {
        "engine": (
            "OrionTrader Unified Stock Analysis Engine"
        ),

        "version": "1.1",

        "generated_at": (
            generated_at
        ),

        "horizon": horizon,

        "automated_execution": False,

        "quality_scores_are_probabilities": False,

        "orion_score_is_probability": False,

        "historical_probability_requires_calibration": True,

        "thematic_regime_enabled": True,
    }

    return combined


# =============================================================================
# COMPACT RESULT
# =============================================================================

def analyze_stock_compact(
    symbol: str,
    horizon: str,
) -> Dict[str, Any]:
    """
    Smaller output useful for scanner / Orion Picks.

    The primary user-facing decision metric is `orion_score`.
    Detailed component scores are still retained by analyze_stock().
    """

    normalized_horizon = _normalize_horizon(
        horizon
    )

    result = analyze_stock(
        symbol,
        normalized_horizon,

        include_articles=False,
        include_market_components=False,
        # Fundamentals are already loaded by analyze_stock for company/profile
        # context. Keep them in the transient result so this compact facade can
        # select a few display fields without triggering a second provider call.
        include_fundamentals=True,
    )

    analysis = _safe_dict(
        result.get(
            "analysis"
        )
    )

    context = _safe_dict(
        result.get(
            "context"
        )
    )

    company = _safe_dict(
        result.get(
            "company"
        )
    )

    technical = _safe_dict(
        result.get(
            "technical"
        )
    )

    fundamentals = _safe_dict(
        result.get(
            "fundamentals"
        )
    )

    data_quality = _safe_dict(
        result.get(
            "data_quality"
        )
    )

    orion = _safe_dict(
        result.get(
            "orion_score"
        )
    )

    market_integrity = _safe_dict(
        result.get(
            "market_integrity"
        )
    )

    integrity_adjustment = _safe_dict(
        result.get(
            "orion_integrity_adjustment"
        )
    )

    intraday_probability = _safe_dict(
        result.get(
            "intraday_probability"
        )
    )

    probability_horizons = _safe_dict(
        intraday_probability.get(
            "horizons"
        )
    )

    thematic_regime = _safe_dict(
        result.get(
            "thematic_regime"
        )
    )

    calibration = _safe_dict(
        result.get(
            "historical_calibration"
        )
    )

    return {
        "symbol": symbol.upper(),

        "company_name": (
            company.get(
                "name"
            )
        ),

        "sector": (
            company.get(
                "sector"
            )
        ),

        "industry": (
            company.get(
                "industry"
            )
        ),

        "price": (
            technical.get(
                "price"
            )
        ),

        # Curated display contexts for the Analysis workspace. Keeping these
        # small avoids exposing raw history arrays or relabelling rule scores.
        "technical_context": {
            key: technical.get(key)
            for key in (
                "price", "vwap", "ema_9", "ema_20", "ema_50",
                "ema_200", "sma_50", "sma_200", "rsi", "atr",
                "atr_pct", "relative_volume", "support", "resistance",
                "momentum_5m_pct", "momentum_15m_pct",
                "momentum_5d_pct", "momentum_20d_pct",
            )
        },

        "fundamental_context": {
            key: fundamentals.get(key)
            for key in (
                "available", "market_cap", "fundamental_profile",
                "fundamental_profile_label", "growth_score",
                "business_quality_score", "balance_sheet_score",
                "valuation_score", "earnings_revision_score",
            )
        },

        "horizon": (
            normalized_horizon
        ),

        # ---------------------------------------------------------------------
        # PRIMARY USER-FACING DECISION
        # ---------------------------------------------------------------------

        # Raw/original Orion suitability score.
        "orion_score": (
            orion.get(
                "score"
            )
        ),

        # Explicit alias so the UI can clearly distinguish raw vs adjusted.
        "raw_orion_score": (
            integrity_adjustment.get(
                "raw_orion_score",
                orion.get(
                    "score"
                ),
            )
        ),

        # User-facing "manipulation" number. This is anomaly/integrity risk,
        # NOT probability that illegal manipulation occurred.
        "manipulation_risk": (
            integrity_adjustment.get(
                "manipulation_risk"
            )
        ),

        # Number of Orion Score points removed because of integrity risk.
        "manipulation_impact": (
            integrity_adjustment.get(
                "manipulation_impact"
            )
        ),

        "adjusted_orion_score": (
            integrity_adjustment.get(
                "adjusted_orion_score",
                orion.get(
                    "score"
                ),
            )
        ),

        "adjusted_orion_label": (
            integrity_adjustment.get(
                "adjusted_label"
            )
        ),

        "market_integrity_state": (
            market_integrity.get(
                "state"
            )
        ),

        "distortion_direction": (
            market_integrity.get(
                "distortion_direction"
            )
        ),

        "probability_30m": (
            probability_horizons.get(
                "30m"
            )
        ),

        "probability_1h": (
            probability_horizons.get(
                "1h"
            )
        ),

        "probability_3h": (
            probability_horizons.get(
                "3h"
            )
        ),

        "probability_5h": (
            probability_horizons.get(
                "5h"
            )
        ),

        "probability_consensus": (
            intraday_probability.get(
                "cross_horizon_consensus"
            )
        ),

        "orion_label": (
            orion.get(
                "label"
            )
        ),

        "bias": (
            analysis.get(
                "bias"
            )
        ),

        # ---------------------------------------------------------------------
        # EXISTING DETERMINISTIC STRATEGY OUTPUT
        # ---------------------------------------------------------------------

        "quality_score": (
            analysis.get(
                "quality_score"
            )
        ),

        "strategy": (
            analysis.get(
                "strategy"
            )
        ),

        "entry_low": (
            analysis.get(
                "entry_low"
            )
        ),

        "entry_high": (
            analysis.get(
                "entry_high"
            )
        ),

        "stop_loss": (
            analysis.get(
                "stop_loss"
            )
        ),

        "target_1": (
            analysis.get(
                "target_1"
            )
        ),

        "target_2": (
            analysis.get(
                "target_2"
            )
        ),

        "risk_reward_1": (
            analysis.get(
                "risk_reward_1"
            )
        ),

        "risk_reward_2": (
            analysis.get(
                "risk_reward_2"
            )
        ),

        # ---------------------------------------------------------------------
        # THEMATIC CONTEXT
        # ---------------------------------------------------------------------

        "primary_theme": (
            thematic_regime.get(
                "primary_theme"
            )
        ),

        "thematic_score": (
            thematic_regime.get(
                "thematic_score"
            )
        ),

        "thematic_regime": (
            thematic_regime.get(
                "primary_theme_regime"
            )
        ),

        # ---------------------------------------------------------------------
        # INTERNAL CONTEXT
        # ---------------------------------------------------------------------

        "news_score": (
            context.get(
                "news_score"
            )
        ),

        "market_score": (
            context.get(
                "market_score"
            )
        ),

        "sector_score": (
            context.get(
                "sector_score"
            )
        ),

        "market_regime": (
            context.get(
                "market_regime"
            )
        ),

        "risk_environment": (
            context.get(
                "risk_environment"
            )
        ),

        # ---------------------------------------------------------------------
        # HISTORICAL CALIBRATION
        #
        # Exposed for diagnostics/backtesting but should not become a second
        # primary number in the normal UI.
        # ---------------------------------------------------------------------

        "calibrated_probability_pct": (
            calibration.get(
                "probability_pct"
            )
            if calibration.get(
                "available",
                False,
            )
            else None
        ),

        "calibration_sample_size": (
            calibration.get(
                "sample_size",
                0,
            )
        ),

        "calibration_available": (
            calibration.get(
                "available",
                False,
            )
        ),

        # ---------------------------------------------------------------------
        # DATA QUALITY / META
        # ---------------------------------------------------------------------

        "data_completeness_pct": (
            data_quality.get(
                "completeness_pct"
            )
        ),

        "warnings": (
            result.get(
                "pipeline_warnings",
                []
            )
        ),

        "generated_at": (
            result.get(
                "generated_at"
            )
        ),
    }


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":

    ticker = (
        sys.argv[1].upper()
        if len(sys.argv) > 1
        else "NVDA"
    )

    horizon = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "day"
    )

    compact = (
        "--compact"
        in sys.argv
    )

    if compact:

        output = (
            analyze_stock_compact(
                ticker,
                horizon,
            )
        )

    else:

        output = analyze_stock(
            ticker,
            horizon,
        )

    print(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        )
    )
