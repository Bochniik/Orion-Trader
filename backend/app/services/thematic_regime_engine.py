from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.market_regime_engine import (
    analyze_symbol_regime,
)


# =============================================================================
# THEMATIC DEFINITIONS
# =============================================================================

THEMES: Dict[str, Dict[str, Any]] = {

    # -------------------------------------------------------------------------
    # AI
    # -------------------------------------------------------------------------

    "ai": {
        "label": "Artificial Intelligence",

        "components": {
            # AI infrastructure / semiconductors
            "SMH": 0.40,

            # Broad mega-cap / growth environment
            "QQQ": 0.20,

            # Software
            "IGV": 0.15,

            # Robotics / automation / AI thematic proxy
            "BOTZ": 0.15,

            # Data-center / cloud infrastructure proxy
            "CLOU": 0.10,
        },

        "notes": [
            "AI score combines semiconductor, software, cloud and growth-market context.",
            "It is a thematic regime indicator, not probability of a stock rising.",
        ],
    },

    # -------------------------------------------------------------------------
    # SEMICONDUCTORS
    # -------------------------------------------------------------------------

    "semiconductors": {
        "label": "Semiconductors",

        "components": {
            "SMH": 0.60,
            "SOXX": 0.25,
            "QQQ": 0.15,
        },

        "notes": [
            "Semiconductor cycle can materially affect chip equities.",
        ],
    },

    # -------------------------------------------------------------------------
    # CRYPTO
    # -------------------------------------------------------------------------

    "crypto": {
        "label": "Crypto / Digital Assets",

        "components": {
            # Spot Bitcoin ETF proxy
            "IBIT": 0.50,

            # Crypto equity ecosystem
            "BITQ": 0.25,

            # Growth/risk environment
            "QQQ": 0.15,

            # Small-cap/risk appetite
            "IWM": 0.10,
        },

        "notes": [
            "Crypto-related equities are highly sensitive to underlying digital-asset risk appetite.",
            "The theme score does not represent Bitcoin price probability.",
        ],
    },

    # -------------------------------------------------------------------------
    # QUANTUM COMPUTING
    # -------------------------------------------------------------------------

    "quantum_computing": {
        "label": "Quantum Computing",

        "components": {
            "QTUM": 0.60,
            "QQQ": 0.20,
            "ARKQ": 0.20,
        },

        "notes": [
            "Quantum equities are early-stage and can behave more like speculative growth assets.",
            "Theme regime should not replace cash-runway and dilution analysis.",
        ],
    },

    # -------------------------------------------------------------------------
    # BIOTECH
    # -------------------------------------------------------------------------

    "biotech": {
        "label": "Biotechnology",

        "components": {
            "XBI": 0.60,
            "IBB": 0.30,
            "XLV": 0.10,
        },

        "notes": [
            "Clinical and regulatory catalysts can dominate individual biotech names.",
        ],
    },

    # -------------------------------------------------------------------------
    # ENERGY / FUELS
    # -------------------------------------------------------------------------

    "fuels_energy": {
        "label": "Oil, Gas & Fuels",

        "components": {
            "XLE": 0.50,
            "XOP": 0.25,
            "OIH": 0.15,
            "SPY": 0.10,
        },

        "notes": [
            "Energy theme reflects producers, oil services and broad market context.",
            "Commodity prices should eventually be added directly.",
        ],
    },

    # -------------------------------------------------------------------------
    # FASHION
    # -------------------------------------------------------------------------

    "fashion": {
        "label": "Fashion & Apparel",

        "components": {
            "XLY": 0.55,
            "RTH": 0.25,
            "SPY": 0.20,
        },

        "notes": [
            "Consumer discretionary conditions influence apparel demand.",
        ],
    },

    # -------------------------------------------------------------------------
    # COSMETICS
    # -------------------------------------------------------------------------

    "cosmetics": {
        "label": "Cosmetics & Beauty",

        "components": {
            "XLP": 0.35,
            "XLY": 0.35,
            "RTH": 0.15,
            "SPY": 0.15,
        },

        "notes": [
            "Beauty companies can span staples and discretionary demand.",
        ],
    },

    # -------------------------------------------------------------------------
    # ENGINEERING / INDUSTRIALS
    # -------------------------------------------------------------------------

    "engineering": {
        "label": "Engineering & Industrials",

        "components": {
            "XLI": 0.55,
            "PAVE": 0.25,
            "SPY": 0.20,
        },

        "notes": [
            "Infrastructure spending and industrial cycle are important drivers.",
        ],
    },

    # -------------------------------------------------------------------------
    # FOOD
    # -------------------------------------------------------------------------

    "food": {
        "label": "Food & Consumer Staples",

        "components": {
            "XLP": 0.60,
            "PBJ": 0.25,
            "SPY": 0.15,
        },

        "notes": [
            "Food companies tend to be defensive but remain sensitive to input-cost inflation.",
        ],
    },

    # -------------------------------------------------------------------------
    # BANKS
    # -------------------------------------------------------------------------

    "banks": {
        "label": "Banks",

        "components": {
            "KBE": 0.45,
            "KRE": 0.30,
            "XLF": 0.25,
        },

        "notes": [
            "Bank theme captures regional and diversified financial conditions.",
        ],
    },
}


# =============================================================================
# COMPANY OVERRIDES
# =============================================================================

# These mappings do not redefine factual sector.
# They tell Orion which thematic context is especially relevant.

SYMBOL_THEME_OVERRIDES: Dict[str, List[str]] = {

    # -------------------------------------------------------------------------
    # AI / SEMICONDUCTORS
    # -------------------------------------------------------------------------

    "NVDA": [
        "ai",
        "semiconductors",
    ],

    "AMD": [
        "ai",
        "semiconductors",
    ],

    "AVGO": [
        "ai",
        "semiconductors",
    ],

    "ARM": [
        "ai",
        "semiconductors",
    ],

    "SMCI": [
        "ai",
    ],

    "MU": [
        "ai",
        "semiconductors",
    ],

    "MRVL": [
        "ai",
        "semiconductors",
    ],

    "TSM": [
        "ai",
        "semiconductors",
    ],

    "PLTR": [
        "ai",
    ],

    "AI": [
        "ai",
    ],

    "ORCL": [
        "ai",
    ],

    "MSFT": [
        "ai",
    ],

    "GOOGL": [
        "ai",
    ],

    "GOOG": [
        "ai",
    ],

    "META": [
        "ai",
    ],

    "AMZN": [
        "ai",
    ],

    # -------------------------------------------------------------------------
    # CRYPTO
    # -------------------------------------------------------------------------

    "COIN": [
        "crypto",
    ],

    "MARA": [
        "crypto",
    ],

    "RIOT": [
        "crypto",
    ],

    "CLSK": [
        "crypto",
    ],

    "HUT": [
        "crypto",
    ],

    "IREN": [
        "crypto",
    ],

    "CIFR": [
        "crypto",
    ],

    "BTDR": [
        "crypto",
    ],

    "WULF": [
        "crypto",
    ],

    # -------------------------------------------------------------------------
    # QUANTUM
    # -------------------------------------------------------------------------

    "IONQ": [
        "quantum_computing",
    ],

    "RGTI": [
        "quantum_computing",
    ],

    "QBTS": [
        "quantum_computing",
    ],

    "QUBT": [
        "quantum_computing",
    ],
}


# =============================================================================
# PROFILE -> THEME
# =============================================================================

PROFILE_THEME_MAP: Dict[str, List[str]] = {
    "semiconductors": [
        "semiconductors",
        "ai",
    ],

    "crypto": [
        "crypto",
    ],

    "quantum_computing": [
        "quantum_computing",
    ],

    "biotech": [
        "biotech",
    ],

    "fuels_energy": [
        "fuels_energy",
    ],

    "fashion": [
        "fashion",
    ],

    "cosmetics": [
        "cosmetics",
    ],

    "engineering": [
        "engineering",
    ],

    "food": [
        "food",
    ],

    "banks": [
        "banks",
    ],
}


# =============================================================================
# MODELS
# =============================================================================

@dataclass
class ThemeComponent:
    symbol: str
    weight: float

    regime_score: float
    trend_score: float
    momentum_score: float
    volatility_score: float

    contribution: float

    warning: Optional[str]


@dataclass
class ThemeResult:
    theme: str
    label: str

    score: float
    regime: str

    available_weight: float

    components: List[Dict[str, Any]]
    notes: List[str]
    warnings: List[str]

    generated_at: str

    def to_dict(
        self,
    ) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# HELPERS
# =============================================================================

def _clamp(
    value: float,
    low: float = -1.0,
    high: float = 1.0,
) -> float:

    return max(
        low,
        min(
            high,
            value,
        ),
    )


def _utc_now_iso() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat()


def _regime_label(
    score: float,
) -> str:

    if score >= 0.60:
        return "strong_bullish"

    if score >= 0.20:
        return "bullish"

    if score <= -0.60:
        return "strong_bearish"

    if score <= -0.20:
        return "bearish"

    return "neutral"


def _normalize_theme(
    theme: str,
) -> str:

    value = str(
        theme
    ).strip().lower()

    aliases = {
        "artificial_intelligence": "ai",
        "artificial intelligence": "ai",

        "semiconductor": "semiconductors",

        "quantum": "quantum_computing",
        "quantum computing": "quantum_computing",

        "crypto_market": "crypto",
        "cryptocurrency": "crypto",

        "energy": "fuels_energy",
        "oil_gas": "fuels_energy",

        "beauty": "cosmetics",

        "industrial": "engineering",
        "industrials": "engineering",

        "consumer_food": "food",

        "bank": "banks",
    }

    return aliases.get(
        value,
        value,
    )


# =============================================================================
# THEME RESOLUTION
# =============================================================================

def resolve_themes_for_stock(
    symbol: str,
    *,
    fundamental_profile: Optional[str] = None,
) -> List[str]:

    symbol = symbol.upper().strip()

    resolved: List[str] = []

    # -------------------------------------------------------------------------
    # Explicit company mapping first
    # -------------------------------------------------------------------------

    for theme in SYMBOL_THEME_OVERRIDES.get(
        symbol,
        [],
    ):

        if (
            theme in THEMES
            and theme not in resolved
        ):
            resolved.append(
                theme
            )

    # -------------------------------------------------------------------------
    # Fundamental profile mapping
    # -------------------------------------------------------------------------

    if fundamental_profile:

        profile = str(
            fundamental_profile
        ).strip().lower()

        for theme in PROFILE_THEME_MAP.get(
            profile,
            [],
        ):

            if (
                theme in THEMES
                and theme not in resolved
            ):
                resolved.append(
                    theme
                )

    return resolved


# =============================================================================
# INDIVIDUAL THEME
# =============================================================================

def analyze_theme(
    theme: str,
) -> Dict[str, Any]:

    theme = _normalize_theme(
        theme
    )

    definition = THEMES.get(
        theme
    )

    if definition is None:
        raise ValueError(
            f"Unknown thematic regime: {theme}"
        )

    component_results: List[
        ThemeComponent
    ] = []

    warnings: List[str] = []

    numerator = 0.0
    available_weight = 0.0

    components = definition.get(
        "components",
        {},
    )

    for symbol, raw_weight in components.items():

        weight = float(
            raw_weight
        )

        result = analyze_symbol_regime(
            symbol
        )

        if result.warning:

            warnings.append(
                f"{symbol}: {result.warning}"
            )

            component_results.append(
                ThemeComponent(
                    symbol=symbol,
                    weight=weight,

                    regime_score=0.0,
                    trend_score=0.0,
                    momentum_score=0.0,
                    volatility_score=0.0,

                    contribution=0.0,

                    warning=result.warning,
                )
            )

            continue

        contribution = (
            result.regime_score
            * weight
        )

        numerator += (
            contribution
        )

        available_weight += (
            weight
        )

        component_results.append(
            ThemeComponent(
                symbol=symbol,
                weight=weight,

                regime_score=(
                    result.regime_score
                ),

                trend_score=(
                    result.trend_score
                ),

                momentum_score=(
                    result.momentum_score
                ),

                volatility_score=(
                    result.volatility_score
                ),

                contribution=round(
                    contribution,
                    4,
                ),

                warning=None,
            )
        )

    # =========================================================================
    # IMPORTANT:
    #
    # If one ETF is unavailable we renormalize across the ETFs that actually
    # have data instead of treating missing data as bearish.
    # =========================================================================

    if available_weight > 0:

        score = (
            numerator
            / available_weight
        )

    else:

        score = 0.0

        warnings.append(
            "No thematic component had usable market data."
        )

    score = round(
        _clamp(
            score,
            -1.0,
            1.0,
        ),
        4,
    )

    return ThemeResult(
        theme=theme,

        label=definition[
            "label"
        ],

        score=score,

        regime=_regime_label(
            score
        ),

        available_weight=round(
            available_weight,
            4,
        ),

        components=[
            asdict(
                component
            )
            for component
            in component_results
        ],

        notes=list(
            definition.get(
                "notes",
                [],
            )
        ),

        warnings=warnings,

        generated_at=(
            _utc_now_iso()
        ),
    ).to_dict()


# =============================================================================
# MULTI-THEME STOCK CONTEXT
# =============================================================================

def analyze_stock_themes(
    symbol: str,
    *,
    fundamental_profile: Optional[str] = None,
) -> Dict[str, Any]:

    symbol = symbol.upper().strip()

    themes = resolve_themes_for_stock(
        symbol,
        fundamental_profile=(
            fundamental_profile
        ),
    )

    if not themes:

        return {
            "symbol": symbol,

            "themes": [],

            "primary_theme": None,

            "primary_theme_score": 0.0,

            "primary_theme_regime": "neutral",

            "combined_theme_score": 0.0,

            "generated_at": (
                _utc_now_iso()
            ),

            "warnings": [
                (
                    "No thematic market mapping "
                    f"for {symbol}."
                )
            ],
        }

    results: List[
        Dict[str, Any]
    ] = []

    warnings: List[str] = []

    scores: List[float] = []

    for theme in themes:

        try:

            result = analyze_theme(
                theme
            )

        except Exception as exc:

            warnings.append(
                f"{theme}: {exc}"
            )

            continue

        results.append(
            result
        )

        score = result.get(
            "score"
        )

        if isinstance(
            score,
            (int, float),
        ):
            scores.append(
                float(score)
            )

        warnings.extend(
            result.get(
                "warnings",
                [],
            )
        )

    if results:

        # Primary theme is currently the first resolved mapping.
        #
        # Explicit symbol overrides therefore receive priority.
        primary = results[0]

    else:

        primary = None

    if scores:

        combined_score = (
            sum(scores)
            / len(scores)
        )

    else:

        combined_score = 0.0

    combined_score = round(
        _clamp(
            combined_score,
            -1.0,
            1.0,
        ),
        4,
    )

    return {
        "symbol": symbol,

        "themes": results,

        "primary_theme": (
            primary.get(
                "theme"
            )
            if primary
            else None
        ),

        "primary_theme_score": (
            primary.get(
                "score",
                0.0,
            )
            if primary
            else 0.0
        ),

        "primary_theme_regime": (
            primary.get(
                "regime",
                "neutral",
            )
            if primary
            else "neutral"
        ),

        "combined_theme_score": (
            combined_score
        ),

        "generated_at": (
            _utc_now_iso()
        ),

        "warnings": list(
            dict.fromkeys(
                warnings
            )
        ),
    }


# =============================================================================
# STRATEGY CONTEXT
# =============================================================================

def get_strategy_thematic_context(
    symbol: str,
    *,
    fundamental_profile: Optional[str] = None,
) -> Dict[str, Any]:

    result = analyze_stock_themes(
        symbol,
        fundamental_profile=(
            fundamental_profile
        ),
    )

    return {
        "thematic_score": (
            result.get(
                "combined_theme_score",
                0.0,
            )
        ),

        "primary_theme": (
            result.get(
                "primary_theme"
            )
        ),

        "primary_theme_score": (
            result.get(
                "primary_theme_score",
                0.0,
            )
        ),

        "primary_theme_regime": (
            result.get(
                "primary_theme_regime",
                "neutral",
            )
        ),

        "thematic_components": (
            result.get(
                "themes",
                [],
            )
        ),

        "thematic_warnings": (
            result.get(
                "warnings",
                [],
            )
        ),
    }


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":

    value = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "ai"
    )

    mode = (
        sys.argv[2].lower()
        if len(sys.argv) > 2
        else "theme"
    )

    if mode == "stock":

        profile = (
            sys.argv[3]
            if len(sys.argv) > 3
            else None
        )

        output = analyze_stock_themes(
            value,
            fundamental_profile=profile,
        )

    else:

        output = analyze_theme(
            value
        )

    print(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        )
    )