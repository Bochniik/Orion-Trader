from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from app.services.stock_analysis_engine import analyze_stock_compact


def _safe_number(value: Any):
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def build_premarket_context(
    ticker: str,
    *,
    horizon: str = "day",
) -> Dict[str, Any]:
    """Reuse Orion's existing compact analysis pipeline only for context fields.

    The returned context is research metadata for premarket ranking. Technical
    quality, Orion Score, entries and trade decisions from the compact analysis
    are deliberately ignored here.
    """
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise ValueError("ticker is required")

    try:
        result = analyze_stock_compact(symbol, horizon)
    except Exception as exc:
        return {
            "ticker": symbol,
            "available": False,
            "news_score": None,
            "market_score": None,
            "sector_score": None,
            "thematic_score": None,
            "primary_theme": None,
            "warnings": [
                f"Premarket context unavailable: {type(exc).__name__}"
            ],
        }

    return {
        "ticker": symbol,
        "available": True,
        "news_score": _safe_number(result.get("news_score")),
        "market_score": _safe_number(result.get("market_score")),
        "sector_score": _safe_number(result.get("sector_score")),
        "thematic_score": _safe_number(result.get("thematic_score")),
        "primary_theme": result.get("primary_theme"),
        "market_regime": result.get("market_regime"),
        "risk_environment": result.get("risk_environment"),
        "warnings": list(result.get("warnings") or []),
        "source": "Orion unified compact analysis context fields",
        "semantics": (
            "Context-only reuse. Technical quality, Orion Score, entries and "
            "regular-session trade decisions from compact analysis are not used "
            "as premarket confirmation."
        ),
    }


def build_premarket_context_map(
    tickers: Iterable[str],
    *,
    horizon: str = "day",
) -> Dict[str, Dict[str, Any]]:
    context = {}

    for ticker in tickers:
        symbol = str(ticker or "").strip().upper()
        if not symbol or symbol in context:
            continue
        context[symbol] = build_premarket_context(
            symbol,
            horizon=horizon,
        )

    return context


if __name__ == "__main__":
    import json
    demo = build_premarket_context_map([])
    print(json.dumps(demo, indent=2))
