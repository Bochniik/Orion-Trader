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


@pytest.mark.parametrize("bridge_status,reason,expected", [
    ("disabled", None, "bridge_disabled"),
    ("unavailable", "upstream_timeout", "upstream_timeout"),
    ("unavailable", "upstream_connection_failure", "upstream_connection_failure"),
    ("unavailable", "upstream_http_failure", "upstream_http_failure"),
    ("unavailable", "invalid_upstream_evidence", "invalid_upstream_evidence"),
    ("unavailable", "unrecognized_internal_error", "no_verified_evidence"),
    ("unavailable", ["unhashable"], "no_verified_evidence"),
])
def test_unavailable_bridge_reason_is_bounded_and_never_a_model_score(bridge_status, reason, expected):
    raw = {"status": bridge_status, "source": "ourai_local_forward_bridge"}
    if reason is not None:
        raw["unavailable_reason"] = reason
    result = research_briefing("NVDA", raw)
    assert result["magnitude"] is None
    assert result["magnitude_status"] == "unavailable"
    assert result["magnitude_unavailable_reason"] == expected
    assert result["p_up"] is None and result["p_down"] is None
    assert result["signed_return_percent"] is None


def test_zero_observations_are_not_presented_as_verified_forward_metrics():
    raw = evidence()
    raw["symbols"]["NVDA"] = {
        "predictions": 0, "resolved": 0, "pending": 0, "champion_mae_bps": None,
    }
    raw["latest_by_symbol"] = {}
    result = research_briefing("NVDA", raw)
    assert result["magnitude_status"] == "unavailable"
    assert result["magnitude_unavailable_reason"] == "no_symbol_observations"
    assert result["magnitude"] is None


def test_verified_observations_have_no_outage_reason():
    result = research_briefing("NVDA", evidence())
    assert result["magnitude_status"] == "verified_forward"
    assert result["magnitude_unavailable_reason"] is None


def test_malformed_directional_header_is_not_misdiagnosed_as_missing_observations():
    raw = evidence()
    raw["direction_available"] = True
    result = research_briefing("NVDA", raw)
    assert result["magnitude"] is None
    assert result["magnitude_unavailable_reason"] == "no_verified_evidence"


@pytest.mark.parametrize("bad_magnitude", [
    None, -1, float("nan"), float("inf"), True, "14.5", [], {},
    10 ** 1000,
])
def test_malformed_latest_magnitude_is_not_verified(bad_magnitude):
    raw = evidence()
    raw["latest_by_symbol"]["NVDA"]["expected_magnitude_bps"] = bad_magnitude
    result = research_briefing("NVDA", raw)
    assert result["magnitude_status"] == "unavailable"
    assert result["magnitude_unavailable_reason"] == "no_verified_evidence"
    assert result["magnitude"] is None
    assert result["p_up"] is result["p_down"] is result["signed_return_percent"] is None


@pytest.mark.parametrize("counts", [
    {"predictions": 3, "resolved": 4, "pending": 0},
    {"predictions": 3, "resolved": 2, "pending": 0},
    {"predictions": 3, "resolved": True, "pending": 2},
    {"predictions": 3, "resolved": 2, "pending": -1},
])
def test_inconsistent_symbol_counts_do_not_become_verified(counts):
    raw = evidence()
    raw["symbols"]["NVDA"].update(counts)
    result = research_briefing("NVDA", raw)
    assert result["magnitude_status"] == "unavailable"
    assert result["magnitude_unavailable_reason"] == "no_verified_evidence"
    assert result["magnitude"] is None


@pytest.mark.parametrize("bad_mae", [None, -1, float("nan"), float("inf"), True, "10.2"])
def test_invalid_resolved_mae_does_not_become_verified(bad_mae):
    raw = evidence()
    raw["symbols"]["NVDA"]["champion_mae_bps"] = bad_mae
    result = research_briefing("NVDA", raw)
    assert result["magnitude_status"] == "unavailable"
    assert result["magnitude"] is None


def test_pending_only_symbol_may_show_magnitude_without_inventing_mae():
    raw = evidence()
    raw["symbols"]["NVDA"] = {
        "predictions": 1, "resolved": 0, "pending": 1,
        "champion_mae_bps": None,
    }
    result = research_briefing("NVDA", raw)
    assert result["magnitude_status"] == "verified_forward"
    assert result["magnitude"]["latest_expected_magnitude_bps"] == 14.5
    assert result["magnitude"]["champion_mae_bps"] is None
    assert result["p_up"] is result["p_down"] is None
