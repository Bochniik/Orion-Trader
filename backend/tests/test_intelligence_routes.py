from types import SimpleNamespace

import pandas as pd

from app.api import intelligence_routes as intelligence


class FakeScanner:
    def __init__(self, state):
        self.state = state
        self.requested_user_ids = []

    def current_state(self, user_id):
        self.requested_user_ids.append(str(user_id))
        return self.state

    def opportunity_state(self, user_id):
        self.requested_user_ids.append(str(user_id))
        return self.state.get("research_opportunities") or {}


def fake_request(scanner, user_id="user-a"):
    return SimpleNamespace(
        state=SimpleNamespace(user={"id": user_id}),
        app=SimpleNamespace(state=SimpleNamespace(scanner_scheduler=scanner)),
    )


def test_closed_market_briefing_uses_last_known_and_labels_next_session():
    scanner = FakeScanner({
        "status": "market_closed",
        "as_of": "2026-09-20T18:00:00+00:00",
        "message": "Regular market closed.",
        "freshness": {"state": "stale"},
        "research_opportunities": {
            "as_of": "2026-09-20T18:00:00+00:00",
            "orion_picks": {"day": [], "swing": [], "long_term": []},
            "last_known": [{
                "ticker": "NVDA",
                "bias": "bullish",
                "confidence": 63,
                "horizon": "day",
                "quality_score": 78,
                "liquidity_score": 96,
                "freshness": "stale",
                "warnings": ["Closed-market evidence."],
                "reasons": ["Strong prior-session setup."],
            }],
            "semantics": "Existing scanner ranking.",
        },
    })

    result = intelligence.briefing(fake_request(scanner))

    assert result["mode"] == "next_session"
    assert result["title"] == "Next Session Briefing"
    assert result["candidate_count"] == 1
    assert result["items"][0]["ticker"] == "NVDA"
    assert result["items"][0]["freshness"] == "stale"


def test_briefing_is_scoped_to_authenticated_user():
    scanner = FakeScanner({
        "status": "ready",
        "research_opportunities": {
            "orion_picks": {"day": [], "swing": [], "long_term": []},
            "last_known": [],
        },
    })

    intelligence.briefing(fake_request(scanner, user_id="user-42"))

    assert scanner.requested_user_ids
    assert scanner.requested_user_ids[0] == "user-42"


def test_runtime_status_keeps_runtime_and_history_semantics_separate():
    assert intelligence._runtime_status({"status": "partial_failure"}) == "DEGRADED"
    assert intelligence._runtime_status({"status": "market_closed"}) == "STANDBY"
    assert intelligence._runtime_status({"status": "ready", "scanner_running": True}) == "ACTIVE"
    assert intelligence._runtime_status({"status": "inactive"}) == "INACTIVE"
    assert intelligence._runtime_status({"status": "starting"}) == "unavailable"


def test_insufficient_evidence_never_returns_a_metric_value():
    result = intelligence._evidence_metric(0.91, 3, minimum=8)
    assert result["status"] == "insufficient_evidence"
    assert result["value"] is None
    assert result["sample_size"] == 3
    assert result["minimum_sample"] == 8


def test_relationship_correlation_requires_minimum_sample():
    short_index = pd.date_range("2026-01-01", periods=12, freq="D", tz="UTC")
    left = pd.DataFrame({"Close": range(100, 112)}, index=short_index)
    right = pd.DataFrame({"Close": range(200, 212)}, index=short_index)

    result = intelligence._history_correlation(left, right)

    assert result["status"] == "insufficient_evidence"
    assert result["value"] is None
    assert result["sample_size"] < 30


def test_decision_pipeline_does_not_fabricate_weights(monkeypatch):
    monkeypatch.setattr(
        intelligence,
        "ticker_context",
        lambda ticker, request: {
            "ticker": ticker,
            "setup": {
                "liquidity_score": 92,
                "market_regime": "risk_on",
                "direction": "UP",
                "confidence": 68,
                "confidence_horizon": "30m",
                "warnings": [],
                "opportunity_state": "candidate",
                "model_output": {"probability_up": 0.68},
            },
        },
    )

    result = intelligence.decision_pipeline(
        "NVDA",
        SimpleNamespace(),
    )

    assert result["weights"] is None
    assert result["weights_status"] == "not_exposed_by_current_pipeline"
    statuses = {row["id"]: row["status"] for row in result["layers"]}
    assert statuses["liquidity"] == "used"
    assert statuses["directional-model"] == "used"
    assert statuses["news-catalyst"] == "unavailable"


def test_briefing_missing_fields_remain_unavailable_not_fabricated():
    item = intelligence._briefing_item({"ticker": "AAPL"})
    assert item["ticker"] == "AAPL"
    assert item["confidence"] is None
    assert item["liquidity_score"] is None
    assert item["catalyst"] is None
    assert item["main_reason"] is None
    assert item["main_risk"] is None


def test_engine_evaluation_hides_metrics_below_minimum_sample():
    summary = intelligence._evaluation_summary({
        "counts": {"outcomes": 3},
        "groups": [{
            "horizon": "30m",
            "probability_engine_version": "v-test",
            "ranking_version": "r-test",
            "outcome_count": 3,
            "directional_accuracy_pct": 100.0,
            "brier_score": 0.01,
            "expected_calibration_error_pct": 1.0,
            "average_realized_return_pct": 2.0,
            "calibration_bins": [{"range": "60-70", "count": 3}],
        }],
        "semantics": "stored evaluation",
    }, minimum_sample=20)

    assert summary["status"] == "insufficient_evidence"
    row = summary["performance_by_horizon"][0]
    assert row["sample_size"] == 3
    assert row["accuracy_percent"] is None
    assert row["brier_score"] is None
    assert row["calibration_error_percent"] is None
    assert row["calibration_bins"] == []


def test_engine_evaluation_exposes_supported_metrics_only_after_sample_gate():
    summary = intelligence._evaluation_summary({
        "counts": {"outcomes": 25},
        "groups": [{
            "horizon": "1h",
            "probability_engine_version": "v-test",
            "ranking_version": "r-test",
            "outcome_count": 25,
            "directional_accuracy_pct": 64.0,
            "brier_score": 0.19,
            "expected_calibration_error_pct": 5.2,
            "average_realized_return_pct": 0.4,
            "calibration_bins": [],
        }],
    }, minimum_sample=20)

    assert summary["status"] == "available"
    row = summary["performance_by_horizon"][0]
    assert row["accuracy_percent"] == 64.0
    assert row["brier_score"] == 0.19
    assert summary["log_loss"] is None
    assert summary["log_loss_status"] == "unavailable_not_stored"
    assert summary["last_evaluation"] is None
