import json

import pytest
import pandas as pd

from app.services.predictive_store import PredictiveIntelligenceStore


def test_liquidity_history_lists_summaries_and_loads_full_detail(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    result = {
        "version": "orion-liquidity-v1",
        "phase": 1,
        "summary": {"ranked_securities": 1},
        "discovery": {"universe_source": "alpaca_paper_us_equity"},
        "rankings": [{"symbol": "AAPL", "liquidity_score": 92}],
    }

    saved = store.save_liquidity_ranking(
        result, {"candidate_count": 60, "history_period": "3mo"}
    )
    listed = store.list_liquidity_rankings()
    loaded = store.get_liquidity_ranking(saved["history_id"])

    assert listed[0]["summary"]["ranked_securities"] == 1
    assert listed[0]["parameters"]["candidate_count"] == 60
    assert "rankings" not in listed[0]
    assert loaded["rankings"][0]["symbol"] == "AAPL"
    assert store.delete_liquidity_rankings() == 1
    with pytest.raises(ValueError, match="not found"):
        store.get_liquidity_ranking(saved["history_id"])


def test_empty_liquidity_ranking_is_not_persisted(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")

    with pytest.raises(ValueError, match="non-empty"):
        store.save_liquidity_ranking({"rankings": []}, {})


def test_models_predictions_and_outcomes_are_isolated_and_auditable(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    artifact = {
        "name": "Baseline",
        "horizons": {
            "5m": {
                "status": "experimental_baseline", "sample_count": 900,
                "reliable": False, "holdout": {"accuracy": 0.49},
            }
        },
        "reliable_horizons": [],
    }
    saved_model = store.save_model(artifact, {"sample_count": 900})
    prediction = {
        "timestamp": "2026-08-26T10:00:00+00:00",
        "due_at": "2026-08-26T10:05:00+00:00",
        "ticker": "AAPL", "price": 100, "horizon": "5m",
        "P_UP": 0.6, "P_DOWN": 0.2, "P_NEUTRAL": 0.2,
        "direction": "UP", "model_direction": "UP",
        "liquidity_tier": "A", "liquidity_score": 90,
        "market_regime": {"regime": "bullish_trend"},
        "confidence": "experimental_unvalidated",
        "feature_snapshot": {"features": {"return_5m": 0.01}},
        "opportunity_score": {"score": 72},
        "expected_value": {"predicted_return": 0.004, "EV_LONG": 0.003, "execution_cost": 0.001},
    }
    prediction_id = store.save_prediction(prediction, saved_model["model_id"])

    assert store.latest_model()["model_id"] == saved_model["model_id"]
    assert store.pending_predictions(now=pd.Timestamp("2026-08-26T10:06:00Z").to_pydatetime())[0]["prediction_id"] == prediction_id

    settled = store.settle_prediction(
        prediction_id, 101, "2026-08-26T10:05:00+00:00"
    )
    analytics = store.prediction_analytics()
    learning = store.learning_memory("AAPL", "5m")

    assert settled["actual_direction"] == "UP"
    assert settled["actual_return"] == pytest.approx(0.01)
    assert analytics["overall"]["accuracy"] == 1
    assert analytics["status"] == "collecting_outcomes"
    assert learning["outcome_events"] == 1
    assert learning["ticker_horizon_profile"]["good_decisions"] == 1
    assert learning["probabilities_modified"] is False
    assert store.delete_predictions() == 1


def test_learning_memory_records_bad_decisions_and_clear_is_not_backfilled(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    prediction = {
        "timestamp": "2026-08-26T10:00:00+00:00",
        "due_at": "2026-08-26T10:05:00+00:00",
        "ticker": "AAPL", "price": 100, "horizon": "5m",
        "P_UP": 0.7, "P_DOWN": 0.2, "P_NEUTRAL": 0.1,
        "direction": "UP", "decision": "BUY", "model_direction": "UP",
        "liquidity_tier": "A", "liquidity_score": 95,
        "market_regime": {"regime": "bullish_trend"},
        "feature_snapshot": {"features": {}},
        "opportunity_score": {"score": 80},
        "expected_value": {"execution_cost": 0.001},
        "strategy_consensus": {"strategies": [
            {"id": "ema_trend", "state": "LONG", "strength": 80, "effective_weight": 1},
        ]},
    }
    prediction_id = store.save_prediction(prediction)
    store.settle_prediction(prediction_id, 98, "2026-08-26T10:05:00+00:00")

    learned = store.learning_memory("AAPL", "5m")
    assert learned["decision_profile"]["bad_decisions"] == 1
    assert learned["strategy_profiles"]["ema_trend"]["accuracy"] == 0

    assert store.delete_learning_memory() == 1
    assert store.learning_memory("AAPL", "5m")["outcome_events"] == 0


def _evaluation_prediction(timestamp="2026-08-26T10:00:00+00:00", horizon="1m", direction="UP"):
    return {
        "timestamp": timestamp, "market_data_timestamp": timestamp,
        "due_at": "2026-08-26T10:01:00+00:00", "ticker": "AAPL", "price": 100,
        "horizon": horizon, "model_version": "orion-predictive-model-v2:test",
        "data_provider": "test", "data_freshness": "fresh",
        "data_quality": {"bars": "fresh"},
        "P_UP": 0.72, "P_DOWN": 0.18, "P_NEUTRAL": 0.10,
        "raw_probabilities": {"P_UP": 0.68, "P_DOWN": 0.20, "P_NEUTRAL": 0.12},
        "calibration_temperature": 1.15,
        "model_direction": direction, "directional_confidence": 72,
        "direction": "NO_TRADE", "decision": "HOLD",
        "feature_snapshot": {"features": {"return_1m": 0.01}, "timestamp": timestamp},
        "expected_value": {"execution_cost": 0.001},
    }


def test_evaluation_record_preserves_raw_calibrated_features_version_and_duplicate_policy(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    result = _evaluation_prediction()
    first = store.save_prediction(result)
    duplicate = store.save_prediction(result)
    later = store.save_prediction(_evaluation_prediction("2026-08-26T10:00:05+00:00"))
    other_horizon = store.save_prediction(_evaluation_prediction(horizon="5m"))

    assert first == duplicate
    assert len({first, later, other_horizon}) == 3
    with store._connect() as connection:
        row = connection.execute("SELECT * FROM live_predictions WHERE id=?", (first,)).fetchone()
    assert row["evaluation_eligible"] == 1
    assert row["raw_p_up"] == 0.68
    assert row["p_up"] == 0.72
    assert row["calibration_temperature"] == 1.15
    assert row["model_version"] == "orion-predictive-model-v2:test"
    assert json.loads(row["feature_json"])["features"]["return_1m"] == 0.01
    assert row["final_decision"] == "HOLD"
    assert len(row["prediction_fingerprint"]) == 64
    assert all(character in "0123456789abcdef" for character in row["prediction_fingerprint"])


def test_conflicting_duplicate_evaluation_prediction_is_rejected_without_overwrite(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    original = _evaluation_prediction()
    prediction_id = store.save_prediction(original)

    conflicting = _evaluation_prediction()
    conflicting["P_UP"] = 0.70
    conflicting["P_NEUTRAL"] = 0.12
    with pytest.raises(ValueError, match="immutable evaluation prediction"):
        store.save_prediction(conflicting)

    with store._connect() as connection:
        rows = connection.execute(
            "SELECT id, p_up, p_neutral, result_json, prediction_fingerprint "
            "FROM live_predictions"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == prediction_id
    assert rows[0]["p_up"] == 0.72
    assert rows[0]["p_neutral"] == 0.10
    assert json.loads(rows[0]["result_json"])["P_UP"] == 0.72
    assert len(rows[0]["prediction_fingerprint"]) == 64


def test_prediction_registry_audit_is_read_only_and_separates_unverifiable_from_corrupt(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    verified_id = store.save_prediction(_evaluation_prediction())
    legacy_id = store.save_prediction(
        _evaluation_prediction("2026-08-26T10:00:05+00:00")
    )
    corrupt_id = store.save_prediction(
        _evaluation_prediction("2026-08-26T10:00:10+00:00")
    )
    assert store.audit_prediction_registry()["status"] == "verified"

    with store._connect() as connection:
        connection.execute(
            "UPDATE live_predictions SET prediction_fingerprint=NULL WHERE id=?",
            (legacy_id,),
        )
        connection.execute(
            "UPDATE live_predictions SET result_json=? WHERE id=?",
            ('{"tampered":true}', corrupt_id),
        )
        before = connection.execute(
            "SELECT id, prediction_fingerprint, result_json "
            "FROM live_predictions ORDER BY id"
        ).fetchall()

    audit = store.audit_prediction_registry()

    with store._connect() as connection:
        after = connection.execute(
            "SELECT id, prediction_fingerprint, result_json "
            "FROM live_predictions ORDER BY id"
        ).fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert audit == {
        "status": "failed",
        "evaluation_prediction_count": 3,
        "verified_count": 1,
        "corrupted_count": 1,
        "unverifiable_count": 1,
        "corrupted_prediction_ids": [corrupt_id],
        "unverifiable_prediction_ids": [legacy_id],
        "policy": "read_only_no_backfill",
    }
    assert verified_id not in audit["corrupted_prediction_ids"]


def test_prediction_snapshot_persists_only_explicit_liquidity_tier_without_mutating_input(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    result = _evaluation_prediction()
    result["liquidity_tier"] = "b"
    original_snapshot = json.loads(json.dumps(result["feature_snapshot"]))

    prediction_id = store.save_prediction(result)

    with store._connect() as connection:
        row = connection.execute(
            "SELECT feature_json FROM live_predictions WHERE id=?", (prediction_id,)
        ).fetchone()
    persisted = json.loads(row["feature_json"])
    assert persisted["liquidity_tier"] == "B"
    assert result["feature_snapshot"] == original_snapshot
    assert "liquidity_tier" not in result["feature_snapshot"]


def test_prediction_snapshot_does_not_infer_invalid_tier_and_rejects_conflict(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    invalid = _evaluation_prediction()
    invalid["liquidity_tier"] = "high"
    invalid_id = store.save_prediction(invalid)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT feature_json FROM live_predictions WHERE id=?", (invalid_id,)
        ).fetchone()
    assert "liquidity_tier" not in json.loads(row["feature_json"])

    conflicting = _evaluation_prediction("2026-08-26T10:00:05+00:00")
    conflicting["liquidity_tier"] = "A"
    conflicting["feature_snapshot"]["liquidity_tier"] = "D"
    with pytest.raises(ValueError, match="Conflicting liquidity tiers"):
        store.save_prediction(conflicting)


def test_incomplete_output_is_stored_only_as_non_evaluable_legacy_record(tmp_path):
    store = PredictiveIntelligenceStore(tmp_path / "orion.db")
    result = _evaluation_prediction()
    result.pop("raw_probabilities")
    prediction_id = store.save_prediction(result)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT evaluation_eligible, prediction_fingerprint "
            "FROM live_predictions WHERE id=?", (prediction_id,)
        ).fetchone()
    assert row["evaluation_eligible"] == 0
    assert row["prediction_fingerprint"] is None

    PredictiveIntelligenceStore(tmp_path / "orion.db")
    with store._connect() as connection:
        after_restart = connection.execute(
            "SELECT prediction_fingerprint FROM live_predictions WHERE id=?",
            (prediction_id,),
        ).fetchone()
    assert after_restart["prediction_fingerprint"] is None
