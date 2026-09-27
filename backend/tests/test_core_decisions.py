from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from app import main
from app.api import core_routes as api
from app.services.auth_store import AuthStore
from app.services.decision_engine import decision_from_prediction, decisions_from_board, technical_decision, today_from_board

NOW = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)


def prediction(ticker="AAPL", direction="UP", now=NOW, **changes):
    observed = (now - timedelta(seconds=20)).isoformat()
    result = {
        "ticker": ticker, "company_name": "Example Company", "timestamp": observed,
        "due_at": (now + timedelta(minutes=5)).isoformat(), "price": 100,
        "horizon": "5m", "direction": direction, "confidence": "validated_baseline",
        "P_UP": 0.8 if direction == "UP" else 0.1,
        "P_DOWN": 0.1 if direction == "UP" else 0.8, "P_NEUTRAL": 0.1,
        "liquidity_tier": "A", "liquidity_score": 90, "quote_as_of": observed,
        "feature_snapshot": {"timestamp": observed},
        "levels": {"entry_area": [99, 100], "invalidation_level": 98, "target_area": [104, 105]} if direction == "UP" else {
            "entry_area": [100, 101], "invalidation_level": 102, "target_area": [95, 96]},
        "expected_value": {"EV_LONG_bps": 12, "EV_SHORT_bps": 12, "predicted_return_percent": 0.4},
        "execution_costs": {"round_trip_cost_bps": 4}, "blockers": [],
        "opportunity_score": {"score": 85}, "market_regime": {"label": "Bullish Trend"},
        "short_explanation": "Momentum and model evidence agree.", "prediction_id": 1,
    }
    result.update(changes)
    return result


def board(*rows, **extra):
    return {"highest_statistical_edge": list(rows), "liquidity_candidates_ranked": 80, **extra}


def test_preserves_model_numbers_and_calculates_conservative_rr_without_mutation():
    source = prediction()
    original = deepcopy(source)
    result = decision_from_prediction(source, now=NOW, market_open=True)
    assert result["actionable"] is True
    assert result["direction"] == "LONG" and result["decision"] == "BUY"
    assert result["risk_reward"] == 2
    assert result["confidence"] == 80
    assert result["model_outputs"] == original
    assert result["data_layer_reason_codes"] == []
    assert all(
        item["status"] == "fresh"
        for item in result["data_freshness_diagnostics"].values()
    )
    assert source == original


@pytest.mark.parametrize("changes", [
    {"confidence": "experimental_unvalidated"}, {"direction": "NO_TRADE"},
    {"liquidity_tier": "C"}, {"liquidity_tier": "D"}, {"liquidity_score": None},
    {"timestamp": None}, {"quote_as_of": None}, {"quote_as_of": "2026-09-01T13:00:00Z"},
    {"timestamp": "2026-09-01T13:00:00Z"}, {"timestamp": "2026-09-01T14:01:00Z"},
    {"feature_snapshot": {"timestamp": "2026-09-01T13:00:00Z"}},
    {"feature_snapshot": {"timestamp": "2026-09-01T13:59:50Z", "history_timestamp": "2026-09-01T13:00:00Z"}},
    {"due_at": NOW.isoformat()}, {"P_UP": float("nan")}, {"P_NEUTRAL": 0.5},
    {"execution_costs": {}}, {"expected_value": {"EV_LONG_bps": -1}},
    {"levels": {}}, {"levels": {"entry_area": [100, 99], "invalidation_level": 98, "target_area": [105]}},
    {"levels": {"entry_area": [99, 100], "invalidation_level": 98, "target_area": [101]}},
    {"blockers": ["Upstream veto"]},
    {"price": None}, {"price": 0}, {"price": 110},
    {"levels": {"entry_area": [99, 100], "invalidation_level": 98, "target_area": [102.998]}},
])
def test_missing_stale_conflicting_and_unsafe_inputs_fail_closed(changes):
    result = decision_from_prediction(prediction(**changes), now=NOW, market_open=True)
    assert result["actionable"] is False
    assert result["direction"] == "WAIT"
    assert result["confidence"] is None
    assert result["entry_zone"] is None and result["targets"] == []
    assert result["warnings"]


@pytest.mark.parametrize(("observed", "reason_code"), [
    ("2026-09-01T13:00:00+00:00", "stale_observation_timestamp"),
    ("2026-09-01T14:01:00+00:00", "future_observation_timestamp"),
])
def test_valid_but_out_of_window_observation_time_has_exact_reason_code(
    observed, reason_code
):
    result = decision_from_prediction(
        prediction(timestamp=observed),
        now=NOW,
        market_open=True,
    )

    assert result["actionable"] is False
    assert result["decision"] == "WAIT"
    assert result["no_trade_reason_codes"] == [reason_code]
    diagnostics = result["directional_diagnostics"]["decision_evidence"]
    assert diagnostics["freshness_status"] == "outside_live_window"
    assert diagnostics["window_reason_codes"] == [reason_code]


def test_data_freshness_diagnostics_identify_each_blocking_layer():
    stale = "2026-09-01T13:00:00+00:00"
    result = decision_from_prediction(
        prediction(
            timestamp=stale,
            feature_snapshot={"timestamp": stale},
            quote_as_of=None,
        ),
        now=NOW,
        market_open=True,
    )

    assert result["actionable"] is False
    assert result["data_layer_reason_codes"] == [
        "stale_prediction_timestamp",
        "stale_feature_bars_timestamp",
        "missing_quote_timestamp",
    ]
    diagnostics = result["data_freshness_diagnostics"]
    assert diagnostics["prediction"]["status"] == "stale"
    assert diagnostics["feature_bars"]["status"] == "stale"
    assert diagnostics["quote"]["status"] == "missing"
    assert (
        result["directional_diagnostics"]["data_layer_reason_codes"]
        == result["data_layer_reason_codes"]
    )


def test_closed_market_and_short_risk_geometry():
    assert not decision_from_prediction(prediction(), now=NOW)["actionable"]
    result = decision_from_prediction(prediction(direction="DOWN"), now=NOW, market_open=True)
    assert result["direction"] == "SHORT" and result["decision"] == "AVOID"
    assert result["risk_reward"] == 2


def test_blocked_prediction_preserves_directional_model_confidence():
    result = decision_from_prediction(
        prediction(
            direction="NO_TRADE", model_direction="UP", blockers=["Model gate"],
            P_UP=0.8, P_DOWN=0.1, P_NEUTRAL=0.1,
        ),
        now=NOW,
        market_open=True,
    )

    assert result["actionable"] is False
    assert result["confidence"] is None
    assert result["model_direction"] == "UP"
    assert result["probability_up"] == 0.8
    assert result["probability_down"] == 0.1
    assert result["directional_confidence"] == 80
    assert result["confidence_kind"] == "calibrated_directional_probability"
    assert result["expected_horizon"] == "5m"
    assert result["directional_result"]["status"] == "available"
    assert result["directional_result"]["direction"] == "UP"


def test_observation_time_reason_code_reaches_no_trade_decision():
    result = decision_from_prediction(
        prediction(
            direction="NO_TRADE",
            model_direction="UP",
            blockers=[],
            observation_time_diagnostics={
                "status": "unavailable",
                "source": None,
                "timestamp": None,
                "reason_code": "missing_observation_timestamp",
                "missing_inputs": [
                    "timezone-aware point-in-time observation timestamp"
                ],
                "policy": "missing_or_invalid_observation_time_forces_no_trade",
            },
        ),
        now=NOW,
        market_open=True,
    )

    assert result["actionable"] is False
    assert result["decision"] == "WAIT"
    assert result["no_trade_reason_codes"] == ["missing_observation_timestamp"]
    assert (
        result["directional_diagnostics"]["decision_evidence"]["reason_code"]
        == "missing_observation_timestamp"
    )
    assert result["directional_result"]["diagnostics"]["no_trade_reason_codes"] == [
        "missing_observation_timestamp"
    ]


def test_technical_fallback_returns_exact_directional_diagnostics():
    result = technical_decision(
        "AAPL",
        {"strategy_analysis": {"data_quality": {"sufficient": False}}},
    )

    assert result["directional_confidence"] is None
    assert result["probability_up"] is None
    assert result["directional_result"]["status"] == "unavailable"
    missing = result["directional_diagnostics"]["missing_inputs"]
    assert "sufficient point-in-time feature history" in missing
    assert "validated calibrated directional model" in missing
    assert "complete calibrated probability vector (P_UP, P_DOWN, P_NEUTRAL)" in missing
    assert result["confidence_unavailable_reasons"] == missing


def test_today_deduplicates_caps_five_and_never_fills_with_low_liquidity():
    rows = [prediction(f"STOCK{i}", liquidity_score=90-i) for i in range(8)]
    rows += [prediction("STOCK0"), prediction("ILLIQUID", liquidity_tier="C", liquidity_score=99)]
    rows += [prediction("TIERB", liquidity_tier="B", liquidity_score=99)]
    result = today_from_board(board(*rows), now=NOW, market_open=True)
    assert [r["ticker"] for r in result["opportunities"]] == [f"STOCK{i}" for i in range(5)]
    assert len({r["ticker"] for r in result["opportunities"]}) == 5


def test_conflicting_validated_horizons_veto_the_ticker():
    result = decisions_from_board(board(prediction(), prediction(direction="DOWN", horizon="15m")), now=NOW, market_open=True)
    assert all(not row["actionable"] for row in result)
    assert all("disagree" in row["warnings"][-1] for row in result)


def test_empty_and_partial_scans_are_not_conflated():
    assert today_from_board(board(), now=NOW)["message"] == "No high-quality setups detected right now."
    partial = today_from_board(board(partial_failure=True, errors=["No data"]), now=NOW)
    assert partial["status"] == "partial"
    assert "unavailable" in partial["message"]


def test_missing_horizon_cannot_be_hidden_by_a_successful_horizon():
    result = today_from_board(board(prediction(), unavailable_predictions=[{"ticker": "AAPL", "horizon": "15m"}]), now=NOW, market_open=True)
    assert result["opportunities"] == []


def test_technical_scores_do_not_become_probability_or_trade_levels():
    result = technical_decision("AAPL", {"strategy_analysis": {
        "data_quality": {"sufficient": True}, "top_setup": {"score": 100, "summary": "Strong technical rules"}}})
    assert result["setup_quality"] == 100
    assert result["decision"] == "WAIT"
    assert result["confidence"] is None and result["targets"] == []


@pytest.fixture
def core_client(monkeypatch):
    monkeypatch.setattr(api, "model_readiness", lambda _model: {"ready": True, "horizons": ["5m"]})
    monkeypatch.setattr(api.legacy, "predictive_intelligence_status", lambda _request: {
        "alpaca_research_data_connected": True, "active_model": {"reliable_horizons": ["5m"], "model_id": 1}})
    monkeypatch.setattr(api, "_market_open", lambda _request: True)
    monkeypatch.setattr(api.legacy, "get_strategy_research", lambda *_args, **_kwargs: {
        "strategy_analysis": {"data_quality": {"sufficient": True}}})
    monkeypatch.setattr(api.legacy.context_cache, "load", lambda *_args: ([], {}))
    monkeypatch.setattr(api.legacy, "scan_live_edge", lambda *_args: board(prediction(now=datetime.now(timezone.utc))))
    with TestClient(main.app) as client:
        yield client


def test_core_routes_use_existing_service_and_selected_ticker(core_client, monkeypatch):
    selected = []
    def scan(config, _request):
        selected.extend(config.symbols)
        return board(prediction(now=datetime.now(timezone.utc)))
    monkeypatch.setattr(api.legacy, "scan_live_edge", scan)
    result = core_client.post("/core/analyze/aapl").json()
    assert selected == ["AAPL"]
    assert result["decision"] == "BUY"
    assert core_client.post("/core/today").json()["opportunities"][0]["ticker"] == "AAPL"


def test_missing_model_does_not_launch_training_or_fake_an_opportunity(core_client, monkeypatch):
    monkeypatch.setattr(api, "model_readiness", lambda _model: {"ready": False, "horizons": []})
    monkeypatch.setattr(api.legacy, "predictive_intelligence_status", lambda _request: {"alpaca_research_data_connected": True, "active_model": None})
    monkeypatch.setattr(api.legacy, "scan_live_edge", lambda *_: pytest.fail("Should not scan without a model"))
    monkeypatch.setattr(api.legacy, "train_predictive_baseline", lambda *_: pytest.fail("No implicit training in milestone 1"))
    assert core_client.post("/core/today").json()["status"] == "unavailable"
    result = core_client.post("/core/analyze/AAPL").json()
    assert result["status"] == "research_only" and result["decision"] == "WAIT"
    assert result["directional_result"]["status"] == "unavailable"
    assert "validated calibrated directional model" in result["directional_diagnostics"]["missing_inputs"]


def test_core_provider_failure_is_not_a_successful_empty_scan(core_client, monkeypatch):
    def fail(*_args):
        raise ValueError("upstream failure")
    monkeypatch.setattr(api.legacy, "scan_live_edge", fail)
    assert core_client.post("/core/today").status_code == 503
    assert core_client.post("/core/analyze/AAPL").json()["decision"] == "WAIT"
    assert core_client.post("/core/analyze/bad%20ticker").status_code == 400


def test_partial_selected_analysis_withholds_plan(core_client, monkeypatch):
    monkeypatch.setattr(api.legacy, "scan_live_edge", lambda *_: board(prediction(now=datetime.now(timezone.utc)), partial_failure=True))
    assert core_client.post("/core/analyze/AAPL").json()["decision"] == "WAIT"


def test_market_status_failure_is_not_reported_as_confirmed_closed(core_client, monkeypatch):
    monkeypatch.setattr(api, "_market_open", lambda _: None)
    assert core_client.post("/core/today").json()["status"] == "unavailable"
    monkeypatch.setattr(api, "_market_open", lambda _: False)
    assert core_client.post("/core/today").json()["status"] == "market_closed"


def test_core_routes_inherit_auth_and_csrf(core_client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "auth_store", AuthStore(data_root=tmp_path / "auth"))
    monkeypatch.setenv("ORION_AUTH_DISABLED", "false")
    assert core_client.get("/core/status").status_code == 401
    session = core_client.post("/auth/register", json={"email": "core@example.com", "password": "secure-test-password"}).json()
    assert core_client.get("/core/status").status_code == 200
    assert core_client.post("/core/today").status_code == 403
    assert core_client.post("/core/today", headers={"X-CSRF-Token": session["csrf_token"]}).status_code == 200
