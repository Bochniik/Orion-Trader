from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.market_regime_engine import get_strategy_market_context
from app.services.news_engine import get_strategy_news_context
from app.services.strategy_engine import analyze_strategy


# =============================================================================
# CONFIG
# =============================================================================

HORIZON_NEWS_CONFIG = {
    "day": {
        "lookback_hours": 48,
        "limit": 30,
    },
    "swing": {
        "lookback_hours": 168,  # 7 days
        "limit": 40,
    },
    "long_term": {
        "lookback_hours": 720,  # 30 days
        "limit": 50,
    },
}


# =============================================================================
# HELPERS
# =============================================================================

def _normalize_horizon(horizon: str) -> str:
    value = str(horizon).strip().lower()

    aliases = {
        "intraday": "day",
        "daytrade": "day",
        "day_trade": "day",
        "day-trading": "day",
        "day_trading": "day",

        "swingtrade": "swing",
        "swing_trade": "swing",
        "swing-trading": "swing",
        "swing_trading": "swing",

        "longterm": "long_term",
        "long-term": "long_term",
        "long term": "long_term",
        "investing": "long_term",
        "investment": "long_term",
    }

    return aliases.get(value, value)


def _safe_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)

    return {}


def _utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


# =============================================================================
# NEWS
# =============================================================================

def load_news_context(
    symbol: str,
    horizon: str,
) -> Dict[str, Any]:

    symbol = symbol.upper().strip()
    horizon = _normalize_horizon(horizon)

    config = HORIZON_NEWS_CONFIG.get(
        horizon,
        HORIZON_NEWS_CONFIG["day"],
    )

    try:
        context = get_strategy_news_context(
            symbol,
            lookback_hours=config["lookback_hours"],
            limit=config["limit"],
        )

        context["news_available"] = not bool(
            context.get("news_warnings")
        )

        context["news_lookback_hours"] = config[
            "lookback_hours"
        ]

        return context

    except Exception as exc:
        return {
            "news_score": 0.0,
            "catalyst_strength": 0.0,
            "news_direction": "neutral",
            "news_freshness": "unavailable",
            "news_article_count": 0,
            "news_relevant_article_count": 0,
            "strongest_catalyst": None,
            "strongest_catalyst_label": None,
            "news_articles": [],
            "news_warnings": [
                f"News context failed: {exc}"
            ],
            "news_available": False,
            "news_lookback_hours": config[
                "lookback_hours"
            ],
        }


# =============================================================================
# MARKET / SECTOR
# =============================================================================

def load_market_context(
    *,
    sector: Optional[str] = None,
    sector_etf: Optional[str] = None,
) -> Dict[str, Any]:

    try:
        context = get_strategy_market_context(
            sector=sector,
            sector_etf=sector_etf,
        )

        context["market_available"] = not bool(
            context.get("market_warnings")
        )

        return context

    except Exception as exc:
        return {
            "market_score": 0.0,
            "sector_score": 0.0,
            "market_regime": "neutral",
            "sector_regime": "neutral",
            "risk_environment": "mixed",
            "sector_etf": sector_etf,
            "market_components": {},
            "market_warnings": [
                f"Market context failed: {exc}"
            ],
            "market_available": False,
        }


# =============================================================================
# ENRICHMENT
# =============================================================================

def enrich_strategy_data(
    symbol: str,
    horizon: str,
    strategy_data: Dict[str, Any],
    *,
    sector: Optional[str] = None,
    sector_etf: Optional[str] = None,
    news_context: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
) -> tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:

    enriched = _safe_dict(
        strategy_data
    )

    if news_context is None:
        news_context = load_news_context(
            symbol,
            horizon,
        )

    if market_context is None:
        market_context = load_market_context(
            sector=sector,
            sector_etf=sector_etf,
        )

    # -------------------------------------------------------------------------
    # NEWS VALUES
    # -------------------------------------------------------------------------

    enriched["news_score"] = (
        news_context.get(
            "news_score",
            0.0,
        )
    )

    enriched["catalyst_strength"] = (
        news_context.get(
            "catalyst_strength",
            0.0,
        )
    )

    # -------------------------------------------------------------------------
    # MARKET VALUES
    # -------------------------------------------------------------------------

    enriched["market_score"] = (
        market_context.get(
            "market_score",
            0.0,
        )
    )

    enriched["sector_score"] = (
        market_context.get(
            "sector_score",
            0.0,
        )
    )

    return (
        enriched,
        news_context,
        market_context,
    )


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def analyze_strategy_with_context(
    symbol: str,
    horizon: str,
    strategy_data: Dict[str, Any],
    *,
    sector: Optional[str] = None,
    sector_etf: Optional[str] = None,
    include_articles: bool = True,
    include_market_components: bool = True,
) -> Dict[str, Any]:

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

    # -------------------------------------------------------------------------
    # LOAD CONTEXT
    # -------------------------------------------------------------------------

    news_context = load_news_context(
        symbol,
        horizon,
    )

    market_context = load_market_context(
        sector=sector,
        sector_etf=sector_etf,
    )

    # -------------------------------------------------------------------------
    # ENRICH STRATEGY INPUT
    # -------------------------------------------------------------------------

    (
        enriched_data,
        news_context,
        market_context,
    ) = enrich_strategy_data(
        symbol,
        horizon,
        strategy_data,
        sector=sector,
        sector_etf=sector_etf,
        news_context=news_context,
        market_context=market_context,
    )

    # -------------------------------------------------------------------------
    # RUN DETERMINISTIC STRATEGY ENGINE
    # -------------------------------------------------------------------------

    strategy_result = analyze_strategy(
        horizon,
        enriched_data,
    )

    # -------------------------------------------------------------------------
    # NEWS OUTPUT
    # -------------------------------------------------------------------------

    articles = news_context.get(
        "news_articles",
        [],
    )

    if not include_articles:
        articles = []

    # -------------------------------------------------------------------------
    # MARKET OUTPUT
    # -------------------------------------------------------------------------

    components = market_context.get(
        "market_components",
        {},
    )

    if not include_market_components:
        components = {}

    # -------------------------------------------------------------------------
    # COMBINED RESULT
    # -------------------------------------------------------------------------

    return {
        "symbol": symbol,
        "horizon": horizon,

        "generated_at": _utc_now_iso(),

        "analysis": strategy_result,

        "context": {
            "news_score": news_context.get(
                "news_score",
                0.0,
            ),

            "catalyst_strength": (
                news_context.get(
                    "catalyst_strength",
                    0.0,
                )
            ),

            "market_score": (
                market_context.get(
                    "market_score",
                    0.0,
                )
            ),

            "sector_score": (
                market_context.get(
                    "sector_score",
                    0.0,
                )
            ),

            "market_regime": (
                market_context.get(
                    "market_regime",
                    "neutral",
                )
            ),

            "sector_regime": (
                market_context.get(
                    "sector_regime",
                    "neutral",
                )
            ),

            "risk_environment": (
                market_context.get(
                    "risk_environment",
                    "mixed",
                )
            ),

            "sector_etf": (
                market_context.get(
                    "sector_etf"
                )
            ),
        },

        "news": {
            "score": news_context.get(
                "news_score",
                0.0,
            ),

            "direction": news_context.get(
                "news_direction",
                "neutral",
            ),

            "catalyst_strength": (
                news_context.get(
                    "catalyst_strength",
                    0.0,
                )
            ),

            "strongest_catalyst": (
                news_context.get(
                    "strongest_catalyst"
                )
            ),

            "strongest_catalyst_label": (
                news_context.get(
                    "strongest_catalyst_label"
                )
            ),

            "freshness": (
                news_context.get(
                    "news_freshness",
                    "unknown",
                )
            ),

            "article_count": (
                news_context.get(
                    "news_article_count",
                    0,
                )
            ),

            "relevant_article_count": (
                news_context.get(
                    "news_relevant_article_count",
                    0,
                )
            ),

            "available": (
                news_context.get(
                    "news_available",
                    False,
                )
            ),

            "lookback_hours": (
                news_context.get(
                    "news_lookback_hours"
                )
            ),

            "articles": articles,

            "warnings": (
                news_context.get(
                    "news_warnings",
                    [],
                )
            ),
        },

        "market": {
            "score": (
                market_context.get(
                    "market_score",
                    0.0,
                )
            ),

            "regime": (
                market_context.get(
                    "market_regime",
                    "neutral",
                )
            ),

            "risk_environment": (
                market_context.get(
                    "risk_environment",
                    "mixed",
                )
            ),

            "available": (
                market_context.get(
                    "market_available",
                    False,
                )
            ),

            "components": components,

            "warnings": (
                market_context.get(
                    "market_warnings",
                    [],
                )
            ),
        },

        "sector": {
            "score": (
                market_context.get(
                    "sector_score",
                    0.0,
                )
            ),

            "regime": (
                market_context.get(
                    "sector_regime",
                    "neutral",
                )
            ),

            "etf": (
                market_context.get(
                    "sector_etf"
                )
            ),
        },
    }


# =============================================================================
# ORION AI CONTEXT
# =============================================================================

def build_orion_ai_strategy_context(
    result: Dict[str, Any],
    *,
    max_news_articles: int = 5,
) -> Dict[str, Any]:

    analysis = _safe_dict(
        result.get("analysis")
    )

    news = _safe_dict(
        result.get("news")
    )

    market = _safe_dict(
        result.get("market")
    )

    sector = _safe_dict(
        result.get("sector")
    )

    articles = news.get(
        "articles",
        [],
    )

    compact_articles = []

    for article in articles[
        :max_news_articles
    ]:

        if not isinstance(
            article,
            dict,
        ):
            continue

        compact_articles.append(
            {
                "headline": article.get(
                    "headline"
                ),

                "direction": article.get(
                    "direction"
                ),

                "catalyst_type": (
                    article.get(
                        "catalyst_type"
                    )
                ),

                "catalyst_label": (
                    article.get(
                        "catalyst_label"
                    )
                ),

                "effective_score": (
                    article.get(
                        "effective_score"
                    )
                ),

                "age_hours": (
                    article.get(
                        "age_hours"
                    )
                ),

                "source": article.get(
                    "source"
                ),
            }
        )

    return {
        "symbol": result.get(
            "symbol"
        ),

        "horizon": result.get(
            "horizon"
        ),

        "generated_at": result.get(
            "generated_at"
        ),

        "strategy": {
            "bias": analysis.get(
                "bias"
            ),

            "quality_score": (
                analysis.get(
                    "quality_score"
                )
            ),

            "bullish_score": (
                analysis.get(
                    "bullish_score"
                )
            ),

            "bearish_score": (
                analysis.get(
                    "bearish_score"
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

            "factors": analysis.get(
                "factors",
                [],
            ),

            "warnings": analysis.get(
                "warnings",
                [],
            ),
        },

        "news": {
            "score": news.get(
                "score"
            ),

            "direction": news.get(
                "direction"
            ),

            "catalyst_strength": (
                news.get(
                    "catalyst_strength"
                )
            ),

            "strongest_catalyst": (
                news.get(
                    "strongest_catalyst"
                )
            ),

            "strongest_catalyst_label": (
                news.get(
                    "strongest_catalyst_label"
                )
            ),

            "freshness": news.get(
                "freshness"
            ),

            "article_count": (
                news.get(
                    "article_count"
                )
            ),

            "important_articles": (
                compact_articles
            ),
        },

        "market": {
            "score": market.get(
                "score"
            ),

            "regime": market.get(
                "regime"
            ),

            "risk_environment": (
                market.get(
                    "risk_environment"
                )
            ),
        },

        "sector": {
            "score": sector.get(
                "score"
            ),

            "regime": sector.get(
                "regime"
            ),

            "etf": sector.get(
                "etf"
            ),
        },

        "interpretation_rules": [
            (
                "quality_score is a deterministic setup-quality "
                "score, not probability of success"
            ),
            (
                "news score is directional context, not probability "
                "of future price movement"
            ),
            (
                "market_score and sector_score are deterministic "
                "regime indicators, not probabilities"
            ),
            (
                "do not invent missing prices, indicators, "
                "probabilities or catalysts"
            ),
            (
                "distinguish calculated facts from interpretation"
            ),
            (
                "explicitly mention conflicting technical, news, "
                "market and sector signals"
            ),
        ],
    }


# =============================================================================
# TEST DATA
# =============================================================================

def _sample_day_data() -> Dict[str, Any]:

    # IMPORTANT:
    #
    # There are NO fake:
    #
    #   market_score
    #   sector_score
    #   news_score
    #
    # values here anymore.
    #
    # Those are loaded automatically.

    return {
        "price": 180.00,

        "vwap": 178.80,

        "ema_9": 179.50,
        "ema_20": 178.50,
        "ema_50": 176.80,

        "rsi": 62.0,
        "macd_hist": 0.28,

        "atr": 3.20,
        "atr_pct": 1.78,

        "relative_volume": 2.10,
        "spread_pct": 0.04,

        "momentum_5m_pct": 0.85,
        "momentum_15m_pct": 1.60,

        "opening_range_high": 179.20,
        "opening_range_low": 176.90,

        "support": 178.20,
        "resistance": 184.00,
    }


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":

    symbol = (
        sys.argv[1].upper()
        if len(sys.argv) > 1
        else "NVDA"
    )

    horizon = (
        _normalize_horizon(
            sys.argv[2]
        )
        if len(sys.argv) > 2
        else "day"
    )

    sector = (
        " ".join(
            sys.argv[3:]
        )
        if len(sys.argv) > 3
        else "technology"
    )

    if horizon != "day":

        print(
            json.dumps(
                {
                    "error": (
                        "CLI smoke test currently contains "
                        "sample technical data only for day horizon."
                    )
                },
                indent=2,
            )
        )

        sys.exit(1)

    result = analyze_strategy_with_context(
        symbol,
        horizon,
        _sample_day_data(),
        sector=sector,
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )