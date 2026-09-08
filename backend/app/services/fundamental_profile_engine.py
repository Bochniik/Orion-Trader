from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


# =============================================================================
# MODELS
# =============================================================================

@dataclass
class FundamentalProfile:
    profile: str
    label: str

    growth_weight: float
    quality_weight: float
    balance_sheet_weight: float
    valuation_weight: float
    profitability_weight: float
    earnings_revision_weight: float

    preferred_metrics: List[str]
    reduced_metrics: List[str]
    ignored_metrics: List[str]

    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# NORMALIZATION
# =============================================================================

def _normalize(value: Optional[str]) -> str:
    if not value:
        return ""

    return (
        str(value)
        .strip()
        .lower()
        .replace("&", "and")
        .replace("/", " ")
        .replace("-", " ")
    )


def _contains_any(
    text: str,
    terms: List[str],
) -> bool:

    return any(
        term in text
        for term in terms
    )


# =============================================================================
# PROFILES
# =============================================================================

PROFILES: Dict[str, FundamentalProfile] = {

    # -------------------------------------------------------------------------
    # TECHNOLOGY / SOFTWARE
    # -------------------------------------------------------------------------

    "technology": FundamentalProfile(
        profile="technology",
        label="Technology",

        growth_weight=0.24,
        quality_weight=0.20,
        balance_sheet_weight=0.10,
        valuation_weight=0.18,
        profitability_weight=0.16,
        earnings_revision_weight=0.12,

        preferred_metrics=[
            "revenue_growth",
            "eps_growth",
            "free_cash_flow",
            "free_cash_flow_yield",
            "gross_margin",
            "operating_margin",
            "roe",
            "forward_pe",
            "peg_ratio",
        ],

        reduced_metrics=[
            "price_to_book",
            "debt_to_equity",
        ],

        ignored_metrics=[],

        notes=[
            "Growth and operating leverage matter more than book value.",
            "High valuation can be acceptable when supported by durable growth.",
        ],
    ),

    # -------------------------------------------------------------------------
    # SEMICONDUCTORS
    # -------------------------------------------------------------------------

    "semiconductors": FundamentalProfile(
        profile="semiconductors",
        label="Semiconductors",

        growth_weight=0.25,
        quality_weight=0.19,
        balance_sheet_weight=0.10,
        valuation_weight=0.18,
        profitability_weight=0.18,
        earnings_revision_weight=0.10,

        preferred_metrics=[
            "revenue_growth",
            "eps_growth",
            "gross_margin",
            "operating_margin",
            "free_cash_flow",
            "roe",
            "forward_pe",
            "peg_ratio",
        ],

        reduced_metrics=[
            "price_to_book",
        ],

        ignored_metrics=[],

        notes=[
            "Semiconductor earnings are cyclical.",
            "Margin expansion and earnings revisions are particularly important.",
            "Valuation should be interpreted relative to cycle and growth.",
        ],
    ),

    # -------------------------------------------------------------------------
    # BANKS
    # -------------------------------------------------------------------------

    "banks": FundamentalProfile(
        profile="banks",
        label="Banks / Financial Institutions",

        growth_weight=0.12,
        quality_weight=0.18,
        balance_sheet_weight=0.24,
        valuation_weight=0.20,
        profitability_weight=0.18,
        earnings_revision_weight=0.08,

        preferred_metrics=[
            "roe",
            "price_to_book",
            "forward_pe",
            "earnings_growth",
        ],

        reduced_metrics=[
            "revenue_growth",
        ],

        ignored_metrics=[
            "current_ratio",
            "quick_ratio",
            "free_cash_flow_yield",
            "debt_to_equity",
        ],

        notes=[
            "Traditional debt and liquidity ratios are not directly comparable with industrial companies.",
            "ROE and price-to-book are more informative.",
            "Bank-specific capital ratios should be added later when available.",
        ],
    ),

    # -------------------------------------------------------------------------
    # INSURANCE
    # -------------------------------------------------------------------------

    "insurance": FundamentalProfile(
        profile="insurance",
        label="Insurance",

        growth_weight=0.10,
        quality_weight=0.20,
        balance_sheet_weight=0.25,
        valuation_weight=0.20,
        profitability_weight=0.17,
        earnings_revision_weight=0.08,

        preferred_metrics=[
            "roe",
            "price_to_book",
            "forward_pe",
            "earnings_growth",
        ],

        reduced_metrics=[
            "revenue_growth",
        ],

        ignored_metrics=[
            "current_ratio",
            "quick_ratio",
        ],

        notes=[
            "Balance-sheet quality is especially important for insurers.",
        ],
    ),

    # -------------------------------------------------------------------------
    # REIT
    # -------------------------------------------------------------------------

    "reit": FundamentalProfile(
        profile="reit",
        label="REIT / Real Estate",

        growth_weight=0.10,
        quality_weight=0.16,
        balance_sheet_weight=0.22,
        valuation_weight=0.23,
        profitability_weight=0.13,
        earnings_revision_weight=0.08,

        preferred_metrics=[
            "debt_to_equity",
            "forward_pe",
            "price_to_book",
        ],

        reduced_metrics=[
            "eps_growth",
            "profit_margin",
        ],

        ignored_metrics=[
            "free_cash_flow_yield",
        ],

        notes=[
            "FFO/AFFO should eventually replace conventional EPS as a primary metric.",
            "Interest-rate sensitivity should be included in macro context.",
        ],
    ),

    # -------------------------------------------------------------------------
    # HEALTHCARE
    # -------------------------------------------------------------------------

    "healthcare": FundamentalProfile(
        profile="healthcare",
        label="Healthcare",

        growth_weight=0.20,
        quality_weight=0.18,
        balance_sheet_weight=0.13,
        valuation_weight=0.17,
        profitability_weight=0.16,
        earnings_revision_weight=0.16,

        preferred_metrics=[
            "revenue_growth",
            "eps_growth",
            "gross_margin",
            "operating_margin",
            "free_cash_flow",
            "forward_pe",
        ],

        reduced_metrics=[
            "price_to_book",
        ],

        ignored_metrics=[],

        notes=[
            "Regulatory and clinical catalysts can dominate short-term valuation changes.",
        ],
    ),

    # -------------------------------------------------------------------------
    # BIOTECH
    # -------------------------------------------------------------------------

    "biotech": FundamentalProfile(
        profile="biotech",
        label="Biotechnology",

        growth_weight=0.15,
        quality_weight=0.10,
        balance_sheet_weight=0.28,
        valuation_weight=0.08,
        profitability_weight=0.07,
        earnings_revision_weight=0.12,

        preferred_metrics=[
            "total_cash",
            "total_debt",
            "current_ratio",
            "quick_ratio",
        ],

        reduced_metrics=[
            "revenue_growth",
        ],

        ignored_metrics=[
            "trailing_pe",
            "forward_pe",
            "peg_ratio",
            "roe",
        ],

        notes=[
            "Cash runway is more important than conventional P/E for pre-profit biotech.",
            "FDA and clinical trial catalysts should carry very high contextual importance.",
        ],
    ),

    # -------------------------------------------------------------------------
    # ENERGY / FUELS
    # -------------------------------------------------------------------------

    "fuels_energy": FundamentalProfile(
        profile="fuels_energy",
        label="Oil, Gas & Fuels",

        growth_weight=0.12,
        quality_weight=0.16,
        balance_sheet_weight=0.18,
        valuation_weight=0.22,
        profitability_weight=0.20,
        earnings_revision_weight=0.12,

        preferred_metrics=[
            "free_cash_flow",
            "free_cash_flow_yield",
            "operating_margin",
            "profit_margin",
            "debt_to_equity",
            "forward_pe",
        ],

        reduced_metrics=[
            "revenue_growth",
            "price_to_sales",
        ],

        ignored_metrics=[],

        notes=[
            "Commodity-price cycle heavily influences earnings.",
            "Free cash flow and balance-sheet resilience matter more than raw revenue growth.",
            "Oil/gas price regime should eventually be added as macro input.",
        ],
    ),

    # -------------------------------------------------------------------------
    # CRYPTO-RELATED EQUITIES
    # -------------------------------------------------------------------------

    "crypto": FundamentalProfile(
        profile="crypto",
        label="Crypto-Related Equities",

        growth_weight=0.20,
        quality_weight=0.12,
        balance_sheet_weight=0.18,
        valuation_weight=0.12,
        profitability_weight=0.12,
        earnings_revision_weight=0.08,

        preferred_metrics=[
            "revenue_growth",
            "total_cash",
            "total_debt",
            "free_cash_flow",
            "operating_margin",
        ],

        reduced_metrics=[
            "forward_pe",
            "trailing_pe",
            "peg_ratio",
        ],

        ignored_metrics=[],

        notes=[
            "Underlying crypto market regime can dominate company fundamentals.",
            "Bitcoin and broader crypto trend should later be included as external market context.",
            "Mining companies require special attention to energy costs and hash economics.",
        ],
    ),

    # -------------------------------------------------------------------------
    # QUANTUM COMPUTING
    # -------------------------------------------------------------------------

    "quantum_computing": FundamentalProfile(
        profile="quantum_computing",
        label="Quantum Computing",

        growth_weight=0.23,
        quality_weight=0.10,
        balance_sheet_weight=0.25,
        valuation_weight=0.08,
        profitability_weight=0.07,
        earnings_revision_weight=0.07,

        preferred_metrics=[
            "revenue_growth",
            "total_cash",
            "total_debt",
            "current_ratio",
            "quick_ratio",
        ],

        reduced_metrics=[
            "forward_pe",
            "trailing_pe",
            "price_to_book",
        ],

        ignored_metrics=[
            "peg_ratio",
        ],

        notes=[
            "Many quantum-computing companies are early-stage and pre-profit.",
            "Cash runway, dilution risk, commercial partnerships and technological milestones matter heavily.",
            "Conventional P/E metrics may be meaningless.",
        ],
    ),

    # -------------------------------------------------------------------------
    # FASHION
    # -------------------------------------------------------------------------

    "fashion": FundamentalProfile(
        profile="fashion",
        label="Fashion & Apparel",

        growth_weight=0.17,
        quality_weight=0.19,
        balance_sheet_weight=0.13,
        valuation_weight=0.18,
        profitability_weight=0.21,
        earnings_revision_weight=0.12,

        preferred_metrics=[
            "revenue_growth",
            "gross_margin",
            "operating_margin",
            "profit_margin",
            "free_cash_flow",
            "forward_pe",
        ],

        reduced_metrics=[
            "price_to_book",
        ],

        ignored_metrics=[],

        notes=[
            "Gross margin and brand pricing power are important.",
            "Inventory quality and consumer demand should eventually be included.",
            "Luxury companies may justify structurally higher margins and valuation.",
        ],
    ),

    # -------------------------------------------------------------------------
    # COSMETICS / BEAUTY
    # -------------------------------------------------------------------------

    "cosmetics": FundamentalProfile(
        profile="cosmetics",
        label="Cosmetics & Beauty",

        growth_weight=0.18,
        quality_weight=0.20,
        balance_sheet_weight=0.12,
        valuation_weight=0.18,
        profitability_weight=0.21,
        earnings_revision_weight=0.11,

        preferred_metrics=[
            "revenue_growth",
            "gross_margin",
            "operating_margin",
            "profit_margin",
            "free_cash_flow",
            "roe",
            "forward_pe",
        ],

        reduced_metrics=[
            "price_to_book",
        ],

        ignored_metrics=[],

        notes=[
            "Brand strength, gross margins and repeat demand are important.",
            "International growth can materially affect long-term quality.",
        ],
    ),

    # -------------------------------------------------------------------------
    # ENGINEERING
    # -------------------------------------------------------------------------

    "engineering": FundamentalProfile(
        profile="engineering",
        label="Engineering & Industrial Services",

        growth_weight=0.15,
        quality_weight=0.19,
        balance_sheet_weight=0.16,
        valuation_weight=0.17,
        profitability_weight=0.20,
        earnings_revision_weight=0.13,

        preferred_metrics=[
            "revenue_growth",
            "operating_margin",
            "free_cash_flow",
            "debt_to_equity",
            "roe",
            "forward_pe",
        ],

        reduced_metrics=[
            "gross_margin",
        ],

        ignored_metrics=[],

        notes=[
            "Order backlog, infrastructure cycle and contract quality are important.",
            "Cash conversion can be more important than headline revenue.",
        ],
    ),

    # -------------------------------------------------------------------------
    # FOOD
    # -------------------------------------------------------------------------

    "food": FundamentalProfile(
        profile="food",
        label="Food & Food Products",

        growth_weight=0.11,
        quality_weight=0.20,
        balance_sheet_weight=0.16,
        valuation_weight=0.19,
        profitability_weight=0.22,
        earnings_revision_weight=0.12,

        preferred_metrics=[
            "gross_margin",
            "operating_margin",
            "profit_margin",
            "free_cash_flow",
            "debt_to_equity",
            "forward_pe",
        ],

        reduced_metrics=[
            "revenue_growth",
        ],

        ignored_metrics=[],

        notes=[
            "Stable margins, pricing power and cash flow often matter more than rapid growth.",
            "Commodity input costs can materially affect margins.",
        ],
    ),

    # -------------------------------------------------------------------------
    # UTILITIES
    # -------------------------------------------------------------------------

    "utilities": FundamentalProfile(
        profile="utilities",
        label="Utilities",

        growth_weight=0.08,
        quality_weight=0.17,
        balance_sheet_weight=0.25,
        valuation_weight=0.20,
        profitability_weight=0.18,
        earnings_revision_weight=0.12,

        preferred_metrics=[
            "debt_to_equity",
            "free_cash_flow",
            "roe",
            "forward_pe",
        ],

        reduced_metrics=[
            "revenue_growth",
        ],

        ignored_metrics=[],

        notes=[
            "Debt structure and interest-rate sensitivity are especially important.",
        ],
    ),

    # -------------------------------------------------------------------------
    # CONSUMER STAPLES
    # -------------------------------------------------------------------------

    "consumer_staples": FundamentalProfile(
        profile="consumer_staples",
        label="Consumer Staples",

        growth_weight=0.10,
        quality_weight=0.22,
        balance_sheet_weight=0.16,
        valuation_weight=0.19,
        profitability_weight=0.21,
        earnings_revision_weight=0.12,

        preferred_metrics=[
            "gross_margin",
            "operating_margin",
            "profit_margin",
            "free_cash_flow",
            "roe",
            "forward_pe",
        ],

        reduced_metrics=[
            "revenue_growth",
        ],

        ignored_metrics=[],

        notes=[
            "Pricing power and durable cash generation matter more than aggressive growth.",
        ],
    ),

    # -------------------------------------------------------------------------
    # GENERAL DEFAULT
    # -------------------------------------------------------------------------

    "general": FundamentalProfile(
        profile="general",
        label="General Corporate",

        growth_weight=0.17,
        quality_weight=0.18,
        balance_sheet_weight=0.16,
        valuation_weight=0.18,
        profitability_weight=0.18,
        earnings_revision_weight=0.13,

        preferred_metrics=[
            "revenue_growth",
            "eps_growth",
            "free_cash_flow",
            "roe",
            "operating_margin",
            "debt_to_equity",
            "forward_pe",
        ],

        reduced_metrics=[],
        ignored_metrics=[],

        notes=[
            "Fallback profile used when no more specific industry profile matches.",
        ],
    ),
}


# =============================================================================
# PROFILE RESOLUTION
# =============================================================================

def resolve_fundamental_profile(
    *,
    sector: Optional[str],
    industry: Optional[str],
    symbol: Optional[str] = None,
    company_name: Optional[str] = None,
) -> FundamentalProfile:

    sector_text = _normalize(sector)
    industry_text = _normalize(industry)
    name_text = _normalize(company_name)
    symbol_text = _normalize(symbol)

    combined = " ".join(
        [
            sector_text,
            industry_text,
            name_text,
            symbol_text,
        ]
    )

    # -------------------------------------------------------------------------
    # HIGHLY SPECIFIC THEMATIC GROUPS
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "quantum computing",
            "quantum computer",
            "quantum technology",
            "quantum information",
        ],
    ):
        return PROFILES[
            "quantum_computing"
        ]

    if _contains_any(
        combined,
        [
            "cryptocurrency",
            "crypto",
            "bitcoin",
            "digital asset",
            "blockchain",
            "crypto mining",
            "bitcoin mining",
        ],
    ):
        return PROFILES[
            "crypto"
        ]

    # -------------------------------------------------------------------------
    # BIOTECH BEFORE GENERAL HEALTHCARE
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "biotechnology",
            "biotech",
            "gene therapy",
            "genomics",
        ],
    ):
        return PROFILES[
            "biotech"
        ]

    # -------------------------------------------------------------------------
    # SEMICONDUCTORS BEFORE GENERAL TECH
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "semiconductor",
            "semiconductors",
            "chip",
            "integrated circuit",
        ],
    ):
        return PROFILES[
            "semiconductors"
        ]

    # -------------------------------------------------------------------------
    # FINANCIALS
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "bank",
            "banks diversified",
            "banks regional",
            "banking",
            "financial institution",
        ],
    ):
        return PROFILES[
            "banks"
        ]

    if _contains_any(
        combined,
        [
            "insurance",
            "insurer",
        ],
    ):
        return PROFILES[
            "insurance"
        ]

    # -------------------------------------------------------------------------
    # ENERGY / FUELS
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "oil",
            "gas",
            "petroleum",
            "refining",
            "refinery",
            "fuel",
            "fuels",
            "lng",
            "natural gas",
            "exploration and production",
            "oilfield",
        ],
    ):
        return PROFILES[
            "fuels_energy"
        ]

    # -------------------------------------------------------------------------
    # FASHION
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "apparel",
            "fashion",
            "luxury goods",
            "footwear",
            "clothing",
            "textile",
            "accessories",
        ],
    ):
        return PROFILES[
            "fashion"
        ]

    # -------------------------------------------------------------------------
    # COSMETICS
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "cosmetics",
            "beauty",
            "personal care",
            "skincare",
            "skin care",
            "fragrance",
            "makeup",
        ],
    ):
        return PROFILES[
            "cosmetics"
        ]

    # -------------------------------------------------------------------------
    # ENGINEERING
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "engineering",
            "engineering services",
            "industrial engineering",
            "construction engineering",
            "infrastructure engineering",
            "industrial services",
        ],
    ):
        return PROFILES[
            "engineering"
        ]

    # -------------------------------------------------------------------------
    # FOOD
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "food",
            "packaged foods",
            "food products",
            "food distribution",
            "grocery",
            "meat products",
            "agricultural products",
            "beverages non alcoholic",
        ],
    ):
        return PROFILES[
            "food"
        ]

    # -------------------------------------------------------------------------
    # REIT / REAL ESTATE
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "reit",
            "real estate investment trust",
        ],
    ):
        return PROFILES[
            "reit"
        ]

    # -------------------------------------------------------------------------
    # HEALTHCARE
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "healthcare",
            "health care",
            "medical",
            "pharmaceutical",
            "drug manufacturer",
            "medical devices",
        ],
    ):
        return PROFILES[
            "healthcare"
        ]

    # -------------------------------------------------------------------------
    # UTILITIES
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "utilities",
            "electric utility",
            "regulated electric",
            "water utility",
        ],
    ):
        return PROFILES[
            "utilities"
        ]

    # -------------------------------------------------------------------------
    # CONSUMER STAPLES
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "consumer defensive",
            "consumer staples",
            "household products",
        ],
    ):
        return PROFILES[
            "consumer_staples"
        ]

    # -------------------------------------------------------------------------
    # TECHNOLOGY
    # -------------------------------------------------------------------------

    if _contains_any(
        combined,
        [
            "technology",
            "software",
            "information technology",
            "internet content",
            "cloud computing",
        ],
    ):
        return PROFILES[
            "technology"
        ]

    return PROFILES[
        "general"
    ]


# =============================================================================
# APPLY PROFILE TO FUNDAMENTALS
# =============================================================================

def apply_fundamental_profile(
    fundamentals: Dict[str, Any],
) -> Dict[str, Any]:

    profile = resolve_fundamental_profile(
        sector=fundamentals.get(
            "sector"
        ),
        industry=fundamentals.get(
            "industry"
        ),
        symbol=fundamentals.get(
            "symbol"
        ),
        company_name=fundamentals.get(
            "company_name"
        ),
    )

    return {
        **fundamentals,

        "fundamental_profile": (
            profile.profile
        ),

        "fundamental_profile_label": (
            profile.label
        ),

        "fundamental_profile_weights": {
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
        },

        "preferred_metrics": (
            profile.preferred_metrics
        ),

        "reduced_metrics": (
            profile.reduced_metrics
        ),

        "ignored_metrics": (
            profile.ignored_metrics
        ),

        "profile_notes": (
            profile.notes
        ),
    }


# =============================================================================
# PROFILE-AWARE SCORE
# =============================================================================

def calculate_profile_adjusted_score(
    fundamentals: Dict[str, Any],
) -> Dict[str, Any]:

    enriched = apply_fundamental_profile(
        fundamentals
    )

    weights = enriched[
        "fundamental_profile_weights"
    ]

    growth = float(
        enriched.get(
            "growth_score",
            0.0,
        )
        or 0.0
    )

    quality = float(
        enriched.get(
            "business_quality_score",
            0.0,
        )
        or 0.0
    )

    balance = float(
        enriched.get(
            "balance_sheet_score",
            0.0,
        )
        or 0.0
    )

    valuation = float(
        enriched.get(
            "valuation_score",
            0.0,
        )
        or 0.0
    )

    earnings_revision = float(
        enriched.get(
            "earnings_revision_score",
            0.0,
        )
        or 0.0
    )

    # Profitability is currently approximated from quality metrics.
    # We can separate this later when we compute ROIC and multi-year margins.
    profitability = quality

    weighted_sum = (
        growth
        * weights["growth"]

        + quality
        * weights["quality"]

        + balance
        * weights["balance_sheet"]

        + valuation
        * weights["valuation"]

        + profitability
        * weights["profitability"]

        + earnings_revision
        * weights["earnings_revision"]
    )

    weight_sum = sum(
        weights.values()
    )

    if weight_sum > 0:
        score = (
            weighted_sum
            / weight_sum
        )
    else:
        score = 0.0

    score = max(
        -1.0,
        min(
            1.0,
            score,
        ),
    )

    enriched[
        "profile_adjusted_fundamental_score"
    ] = round(
        score,
        4,
    )

    return enriched


# =============================================================================
# CLI TEST
# =============================================================================

if __name__ == "__main__":

    import json
    import sys

    from app.services.fundamental_data_engine import (
        get_fundamental_strategy_data,
    )

    ticker = (
        sys.argv[1].upper()
        if len(sys.argv) > 1
        else "NVDA"
    )

    fundamentals = (
        get_fundamental_strategy_data(
            ticker
        )
    )

    result = (
        calculate_profile_adjusted_score(
            fundamentals
        )
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )