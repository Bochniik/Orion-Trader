"""Regress research-only news/magnitude separation without contacting providers."""
import pytest

from app.services.ourai_research_briefing import research_briefing


def evidence():
    return {
        "status": "available",
        "source": "ourai_verified_forward_journal",
        "experiment": "frozen_v3_magnitude_15m",
        "mode": "RESEARCH_SHADOW_ONLY",
        "direction_available": False,
        "trading_enabled": False,
        "as_of": "2026-10-26T15:00:00Z",
        "symbols": {
            "NVDA": {
                "predictions": 3, "resolved": 2, "pending": 1,
                "champion_mae_bps": 10.2,
            }
        },
        "latest_by_symbol": {
            "NVDA": {"expected_magnitude_bps": 14.5}
        },
    }


def news():
    return {
        "symbol": "NVDA",
        "overall_context": "research only",
        "insights": [{
            "article_id": "publisher-article-1",
            "sentiment": "POSITIVE",
            "summary": "Illustrative headline context.",
            "why_it_matters": "May influence volatility.",
        }],
    }


def test_present_both_without_direction_or_trade_recommendations():
    result = research_briefing("NVDA", evidence(), news())
    assert result["magnitude_status"] == "verified_forward"
    assert result["magnitude"]["latest_expected_magnitude_bps"] == 14.5
    assert result["news"]["status"] == "commentary_only"
    assert result["news"]["insights"][0]["article_id"] == "publisher-article-1"
    assert result["p_up"] is None
    assert result["p_down"] is None
    assert result["signed_return_percent"] is None
    assert result["decision"] is None
    assert result["trading_enabled"] is False
    assert "magnitude-only" in result["disclaimer"]


@pytest.mark.parametrize("override", [
    {"status": "unavailable"},
    {"status": "disabled"},
    {"source": "unknown"},
    {"direction_available": True},
    {"trading_enabled": True},
    {"experiment": "unvalidated_directional_model"},
])
def test_unavailable_or_directional_evidence_never_exposed_as_verified(override):
    raw = evidence()
    raw.update(override)
    result = research_briefing("NVDA", raw, news())
    assert result["magnitude"] is None
    assert result["magnitude_status"] == "unavailable"
    assert result["news"]["status"] == "commentary_only"


def test_missing_symbol_does_not_invent_per_symbol_results():
    result = research_briefing("AAPL", evidence(), None)
    assert result["magnitude"] is None
    assert result["news"]["status"] == "unavailable"


@pytest.mark.parametrize("symbol", ["", "NVDA;DROP", "SPY", "nvda"])
def test_reject_unknown_symbol(symbol):
    with pytest.raises(ValueError):
        research_briefing(symbol, evidence())


def test_reject_news_for_another_symbol():
    with pytest.raises(ValueError):
        research_briefing("NVDA", evidence(), {"symbol": "AAPL", "insights": []})


@pytest.mark.parametrize("row", [
    {"article_id": "x", "sentiment": "BULLISH", "summary": "x", "why_it_matters": "x"},
    {"article_id": "", "sentiment": "POSITIVE", "summary": "x", "why_it_matters": "x"},
    {"article_id": "x", "sentiment": "POSITIVE", "summary": None, "why_it_matters": "x"},
])
def test_invalid_news_never_gets_presented_as_interpretation(row):
    with pytest.raises(ValueError):
        research_briefing("NVDA", evidence(), {"symbol": "NVDA", "insights": [row]})


def test_ignores_untrusted_directional_fields_even_if_present():
    raw = evidence()
    raw.update({"p_up": 0.99, "p_down": 0.01, "signed_return_percent": 8.0})
    result = research_briefing("NVDA", raw, news())
    assert result["p_up"] is result["p_down"] is result["signed_return_percent"] is None
