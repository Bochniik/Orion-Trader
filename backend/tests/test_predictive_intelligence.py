import pandas as pd

from app.services import predictive_intelligence as service


def test_market_regime_is_deterministic_and_explicit():
    index = pd.date_range("2026-01-01", periods=80, freq="min", tz="UTC")
    history = pd.DataFrame({"Close": [100 + position * 0.12 for position in range(80)]}, index=index)

    result = service.classify_market_regime(history)

    assert result["regime"] in {
        "bullish_trend", "bearish_trend", "range_chop",
        "high_volatility", "low_volatility",
    }
    assert result["semantics"].endswith("not a forecast.")


def test_expected_value_subtracts_round_trip_execution_costs():
    probabilities = {"P_UP": 0.6, "P_DOWN": 0.25, "P_NEUTRAL": 0.15}
    horizon = {"conditional_return_statistics": {
        "UP": {"mean": 0.01}, "DOWN": {"mean": -0.008}, "NEUTRAL": {"mean": 0},
    }}
    result = service.calculate_expected_value(
        probabilities, horizon, {"round_trip_cost_bps": 20}
    )

    assert result["EV_LONG"] == 0.002
    assert result["execution_cost"] == 0.002
    assert "estimated round-trip" in result["formula"]


def test_live_prediction_returns_no_trade_when_reliability_fails(monkeypatch):
    monkeypatch.setattr(service, "predict_probabilities", lambda *_args: {
        "P_UP": 0.82, "P_DOWN": 0.10, "P_NEUTRAL": 0.08,
        "strongest_logistic_contributors": [
            {"feature": "return_5m", "contribution": 1.0, "direction": "supports"},
        ],
    })
    snapshot = {
        "timestamp": "2026-08-26T14:00:00+00:00", "price": 100,
        "feature_coverage_percent": 90,
        "features": {"spread_percent": 0.0002, "atr_14": 1, "relative_volume": 2},
    }
    liquidity = {
        "liquidity_score": 95, "liquidity_tier": "A", "liquidity_percentile": 99,
        "metrics": {"spread_percent": 0.02},
    }
    horizon = {
        "reliable": False,
        "holdout": {"expected_calibration_error": 0.02},
        "conditional_return_statistics": {
            "UP": {"mean": 0.01}, "DOWN": {"mean": -0.006}, "NEUTRAL": {"mean": 0},
        },
    }
    regime = {"regime": "bullish_trend", "label": "Bullish Trend", "status": "classified"}

    result = service.build_live_prediction("AAPL", "5m", snapshot, liquidity, horizon, regime)

    assert result["verdict"] == "NO TRADE — NO STATISTICAL EDGE"
    assert result["direction"] == "NO_TRADE"
    assert result["levels"]["entry_area"] is None
    assert any("out-of-sample reliability" in blocker for blocker in result["blockers"])
    assert result["safety_boundary"].startswith("Assistant-only research")


def test_trusted_adverse_memory_can_veto_but_never_rewrite_probabilities(monkeypatch):
    monkeypatch.setattr(service, "predict_probabilities", lambda *_args: {
        "P_UP": 0.82, "P_DOWN": 0.10, "P_NEUTRAL": 0.08,
        "strongest_logistic_contributors": [
            {"feature": "return_5m", "contribution": 1.0, "direction": "supports"},
        ],
    })
    snapshot = {
        "timestamp": "2026-08-26T14:00:00+00:00", "price": 100,
        "feature_coverage_percent": 90,
        "features": {"spread_percent": 0.0002, "atr_14": 1, "relative_volume": 2},
    }
    liquidity = {
        "liquidity_score": 95, "liquidity_tier": "A", "liquidity_percentile": 99,
        "metrics": {"spread_percent": 0.02},
    }
    horizon = {
        "reliable": True,
        "holdout": {"expected_calibration_error": 0.02},
        "conditional_return_statistics": {
            "UP": {"mean": 0.02}, "DOWN": {"mean": -0.006}, "NEUTRAL": {"mean": 0},
        },
    }
    regime = {"regime": "bullish_trend", "label": "Bullish Trend", "status": "classified"}
    strategies = {
        "consensus": "LONG", "agreement_score": 82,
        "available_strategies": 12, "strategies": [],
    }
    learning = {
        "memory_state": "learning", "outcome_events": 25,
        "trusted_for_decision_gate": True,
        "decision_influence": "adverse_pattern",
        "strategy_profiles": {}, "probabilities_modified": False,
    }

    result = service.build_live_prediction(
        "AAPL", "5m", snapshot, liquidity, horizon, regime,
        strategies, learning,
    )

    assert result["decision"] == "HOLD"
    assert result["P_UP"] == 0.82
    assert result["learning_memory"]["probabilities_modified"] is False
    assert any("Outcome memory" in blocker for blocker in result["blockers"])

def test_live_prediction_fails_closed_without_point_in_time_timestamp(monkeypatch):
    monkeypatch.setattr(service, "predict_probabilities", lambda *_args: {
        "P_UP": 0.82, "P_DOWN": 0.10, "P_NEUTRAL": 0.08,
        "strongest_logistic_contributors": [
            {"feature": "return_5m", "contribution": 1.0, "direction": "supports"},
        ],
    })
    snapshot = {
        "price": 100,
        "feature_coverage_percent": 90,
        "features": {"spread_percent": 0.0002, "atr_14": 1, "relative_volume": 2},
    }
    liquidity = {
        "liquidity_score": 95, "liquidity_tier": "A", "liquidity_percentile": 99,
        "metrics": {"spread_percent": 0.02},
    }
    horizon = {
        "reliable": True,
        "holdout": {"expected_calibration_error": 0.02},
        "conditional_return_statistics": {
            "UP": {"mean": 0.02}, "DOWN": {"mean": -0.006}, "NEUTRAL": {"mean": 0},
        },
    }
    regime = {"regime": "bullish_trend", "label": "Bullish Trend", "status": "classified"}
    strategies = {
        "consensus": "LONG", "agreement_score": 82,
        "available_strategies": 12, "strategies": [],
    }

    result = service.build_live_prediction(
        "AAPL", "5m", snapshot, liquidity, horizon, regime, strategies
    )

    assert result["direction"] == "NO_TRADE"
    assert result["decision"] == "HOLD"
    assert result["timestamp"] is None
    assert result["due_at"] is None
    assert result["market_data_timestamp"] is None
    assert result["observation_time_diagnostics"] == {
        "status": "unavailable",
        "source": None,
        "timestamp": None,
        "missing_inputs": ["timezone-aware point-in-time observation timestamp"],
        "policy": "missing_or_invalid_observation_time_forces_no_trade",
    }
    assert any("observation timestamp" in blocker for blocker in result["blockers"])

