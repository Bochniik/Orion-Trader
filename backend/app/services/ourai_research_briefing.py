"""Read-only research presentation contract combining verified magnitude and news commentary.

This is deliberately a pure adapter, NOT a model, article fetcher, signal
generator or runtime route. Callers must supply independently obtained news
commentary; forward evidence is only from the validated loopback consumer.
"""
from __future__ import annotations

from typing import Any

_ALLOWED = frozenset({"NVDA", "AAPL", "TSLA", "JPM", "AMD", "META", "MSFT"})


def research_briefing(symbol: str, evidence: dict[str, Any], news: dict[str, Any] | None = None) -> dict:
    """Produce a bounded, provenance-labelled informational view; never trade."""
    if not isinstance(symbol, str) or symbol not in _ALLOWED:
        raise ValueError("unsupported symbol")
    if not isinstance(evidence, dict):
        raise ValueError("invalid evidence")

    verified = (
        evidence.get("status") == "available"
        and evidence.get("source") == "ourai_verified_forward_journal"
        and evidence.get("experiment") == "frozen_v3_magnitude_15m"
        and evidence.get("mode") == "RESEARCH_SHADOW_ONLY"
        and evidence.get("direction_available") is False
        and evidence.get("trading_enabled") is False
    )
    # Never silently promote arbitrary dicts to trusted forward evidence.
    if verified:
        expected = evidence.get("symbols")
        latest = evidence.get("latest_by_symbol")
        if not isinstance(expected, dict) or not isinstance(latest, dict):
            verified = False
        elif symbol not in expected:
            verified = False
        else:
            row = expected[symbol]
            if not isinstance(row, dict):
                verified = False

    magnitude = None
    if verified:
        row = evidence["symbols"][symbol]
        latest = evidence["latest_by_symbol"].get(symbol)
        if not isinstance(latest, dict):
            latest = None
        magnitude = {
            "source": "ourai_verified_forward_journal",
            "kind": "absolute_magnitude_only",
            "horizon_minutes": 15,
            "as_of": evidence.get("as_of"),
            "predictions": row.get("predictions"),
            "resolved": row.get("resolved"),
            "pending": row.get("pending"),
            "champion_mae_bps": row.get("champion_mae_bps"),
            "latest_expected_magnitude_bps": (
                latest.get("expected_magnitude_bps") if latest else None
            ),
            "direction_available": False,
        }

    # Supplied news commentary is a distinct qualitative layer. Do not infer
    # impact, assign probabilities, or manufacture a forecast from sentiment.
    news_view = {
        "status": "unavailable",
        "source": "separate_news_commentary",
        "insights": [],
        "disclaimer": "No article-grounded commentary supplied.",
    }
    if news is not None:
        if not isinstance(news, dict) or news.get("symbol") != symbol:
            raise ValueError("news symbol mismatch")
        rows = news.get("insights")
        if not isinstance(rows, list) or len(rows) > 8:
            raise ValueError("invalid news commentary rows")
        clean = []
        for item in rows:
            if (not isinstance(item, dict)
                    or not isinstance(item.get("article_id"), str)
                    or not item["article_id"]
                    or item.get("sentiment") not in {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL"}
                    or not isinstance(item.get("summary"), str)
                    or not isinstance(item.get("why_it_matters"), str)):
                raise ValueError("invalid news commentary")
            clean.append({
                "article_id": item["article_id"][:80],
                "sentiment": item["sentiment"],
                "summary": item["summary"][:700],
                "why_it_matters": item["why_it_matters"][:500],
            })
        news_view = {
            "status": "commentary_only" if clean else "unavailable",
            "source": "separate_news_commentary",
            "insights": clean,
            "disclaimer": "Qualitative interpretation is not a verified price prediction.",
        }

    return {
        "symbol": symbol,
        "mode": "RESEARCH_SHADOW_ONLY",
        "trading_enabled": False,
        "decision": None,
        "p_up": None,
        "p_down": None,
        "signed_return_percent": None,
        "magnitude": magnitude,
        "magnitude_status": "verified_forward" if magnitude else "unavailable",
        "news": news_view,
        "disclaimer": (
            "Independent news interpretation does not validate direction or "
            "signed returns. Forward evidence is magnitude-only."
        ),
    }
