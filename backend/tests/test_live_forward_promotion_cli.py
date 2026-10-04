from __future__ import annotations

from app.services.live_forward_promotion_cli import main, promotion_status_line, run_evaluation
from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.model_registry import OrionModelRegistry
from app.services.predictive_store import PredictiveIntelligenceStore


def _artifact():
    return {
        "scope": SIMULATED_FORWARD,
        "automatic_live_promotion": False,
        "live_forward_mutated": False,
        "horizons": {
            "5m": {
                "status": "evaluated",
                "model_version": "model-a",
                "sample_count": 100,
                "train_sample_count": 70,
                "validation_sample_count": 30,
                "purged_training_sample_count": 0,
                "promotion_recommended": True,
                "validation": {
                    "raw_brier": 0.22,
                    "calibrated_brier": 0.18,
                    "brier_improvement": 0.04,
                    "raw_directional_accuracy": 0.56,
                    "calibrated_directional_accuracy": 0.60,
                    "trade_coverage": 0.50,
                    "trade_directional_accuracy": 0.64,
                },
            }
        },
    }


def _seed_one_settled_prediction(path):
    store = PredictiveIntelligenceStore(path)
    prediction_id = store.save_prediction({
        "timestamp": "2026-10-01T14:00:00+00:00",
        "due_at": "2026-10-01T14:05:00+00:00",
        "ticker": "AAPL",
        "price": 100.0,
        "horizon": "5m",
        "P_UP": 0.8,
        "P_DOWN": 0.2,
        "P_NEUTRAL": 0.0,
        "raw_probabilities": {"P_UP": 0.8, "P_DOWN": 0.2, "P_NEUTRAL": 0.0},
        "feature_snapshot": {"features": {"realized_volatility": 0.01}},
        "model_version": "model-a",
        "model_direction": "UP",
        "decision": "BUY",
        "directional_confidence": 0.8,
    })
    store.save_outcome({
        "prediction_id": prediction_id,
        "ticker": "AAPL",
        "horizon": "5m",
        "prediction_timestamp": "2026-10-01T14:00:00+00:00",
        "target_timestamp": "2026-10-01T14:05:00+00:00",
        "actual_market_timestamp": "2026-10-01T14:05:00+00:00",
        "reference_price": 100.0,
        "timestamp_deviation_seconds": 0.0,
        "future_price": 101.0,
        "realized_return": 0.01,
        "actual_direction": "UP",
        "predicted_model_direction": "UP",
        "direction_correct": 1,
        "settled_at": "2026-10-01T14:05:10+00:00",
        "provider": "fixture",
        "data_quality_json": "{}",
        "status": "settled",
        "reason": None,
    })


def test_run_evaluation_reports_live_sample_progress_without_auto_promotion(tmp_path):
    database = tmp_path / "predictive.db"
    registry_path = tmp_path / "registry.json"
    _seed_one_settled_prediction(database)
    OrionModelRegistry(registry_path).register_learning_artifact(_artifact())
    before = database.read_bytes()

    result = run_evaluation(
        live_database_path=database,
        registry_path=registry_path,
        horizon="5m",
        model_version="model-a",
    )

    assert result["status_line"] == "REPLAY PASSED -> LIVE 1/30 samples -> NOT ELIGIBLE YET"
    assert result["automatic_live_promotion"] is False
    assert result["explicit_approval_required"] is True
    assert result["live_forward_mutated"] is False
    assert result["evaluation"]["eligible_for_promotion"] is False
    assert database.read_bytes() == before
    assert OrionModelRegistry(registry_path).snapshot()["champions"] == {}


def test_status_line_distinguishes_passed_and_failed_live_gates():
    passed = {
        "eligible_for_promotion": True,
        "blockers": [],
        "live_evidence": {"settled_sample_count": 40},
        "gates": {"min_live_settled_samples": 30},
    }
    failed = {
        "eligible_for_promotion": False,
        "blockers": ["live_brier_above_gate"],
        "live_evidence": {"settled_sample_count": 40},
        "gates": {"min_live_settled_samples": 30},
    }

    assert promotion_status_line(passed) == "REPLAY PASSED -> LIVE GATES PASSED -> AWAITING EXPLICIT PROMOTION"
    assert promotion_status_line(failed) == "REPLAY PASSED -> LIVE GATES FAILED -> live_brier_above_gate"


def test_cli_prints_operator_status_line(tmp_path, capsys):
    database = tmp_path / "predictive.db"
    registry_path = tmp_path / "registry.json"
    _seed_one_settled_prediction(database)
    OrionModelRegistry(registry_path).register_learning_artifact(_artifact())

    code = main([
        "--live-db", str(database),
        "--registry", str(registry_path),
        "--horizon", "5m",
        "--model-version", "model-a",
    ])

    assert code == 0
    assert capsys.readouterr().out.strip() == "REPLAY PASSED -> LIVE 1/30 samples -> NOT ELIGIBLE YET"
