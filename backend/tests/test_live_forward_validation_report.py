from __future__ import annotations

import pytest

from app.services.live_forward_promotion import LiveForwardPromotionService
from app.services.live_forward_validation_report import LiveForwardValidationReportBuilder
from app.services.market_replay_engine import LIVE_FORWARD, SIMULATED_FORWARD
from app.services.model_registry import OrionModelRegistry, PromotionConfig
from app.services.predictive_store import PredictiveIntelligenceStore


def _prediction(index: int, *, model_version="model-a", horizon="5m", p_up=0.8, decision="BUY", model_direction="UP"):
    return {
        "timestamp": f"2026-10-01T14:{index:02d}:00+00:00",
        "due_at": f"2026-10-01T14:{index + 5:02d}:00+00:00",
        "ticker": "AAPL",
        "price": 100.0,
        "horizon": horizon,
        "P_UP": p_up,
        "P_DOWN": 1.0 - p_up,
        "P_NEUTRAL": 0.0,
        "raw_probabilities": {"P_UP": p_up, "P_DOWN": 1.0 - p_up, "P_NEUTRAL": 0.0},
        "feature_snapshot": {"features": {"realized_volatility": 0.01}},
        "model_version": model_version,
        "model_direction": model_direction,
        "decision": decision,
        "directional_confidence": max(p_up, 1.0 - p_up),
    }


def _settle(store, prediction_id, *, index, actual_direction, correct, status="settled"):
    store.save_outcome({
        "prediction_id": prediction_id,
        "ticker": "AAPL",
        "horizon": "5m",
        "prediction_timestamp": f"2026-10-01T14:{index:02d}:00+00:00",
        "target_timestamp": f"2026-10-01T14:{index + 5:02d}:00+00:00",
        "actual_market_timestamp": f"2026-10-01T14:{index + 5:02d}:00+00:00",
        "reference_price": 100.0,
        "timestamp_deviation_seconds": 0.0,
        "future_price": 101.0 if actual_direction == "UP" else 99.0,
        "realized_return": 0.01 if actual_direction == "UP" else -0.01,
        "actual_direction": actual_direction,
        "predicted_model_direction": "UP" if correct else "DOWN",
        "direction_correct": int(correct),
        "settled_at": f"2026-10-01T14:{index + 5:02d}:10+00:00",
        "provider": "fixture",
        "data_quality_json": "{}",
        "status": status,
        "reason": None,
    })


def _seed_live_database(path):
    store = PredictiveIntelligenceStore(path)
    first = store.save_prediction(_prediction(0, p_up=0.8, decision="BUY", model_direction="UP"))
    second = store.save_prediction(_prediction(1, p_up=0.2, decision="NO_TRADE", model_direction="DOWN"))
    third = store.save_prediction(_prediction(2, p_up=0.4, decision="SELL", model_direction="DOWN"))
    _settle(store, first, index=0, actual_direction="UP", correct=True)
    _settle(store, second, index=1, actual_direction="DOWN", correct=True)
    _settle(store, third, index=2, actual_direction="UP", correct=False)

    other_model = store.save_prediction(_prediction(3, model_version="model-b", p_up=0.9))
    _settle(store, other_model, index=3, actual_direction="UP", correct=True)

    pending = store.save_prediction(_prediction(4, p_up=0.9))
    store.save_outcome({
        "prediction_id": pending,
        "ticker": "AAPL", "horizon": "5m",
        "prediction_timestamp": "2026-10-01T14:04:00+00:00",
        "target_timestamp": "2026-10-01T14:09:00+00:00",
        "actual_market_timestamp": None, "reference_price": 100.0,
        "future_price": None, "realized_return": None, "actual_direction": None,
        "predicted_model_direction": "UP", "direction_correct": None,
        "settled_at": "2026-10-01T14:10:00+00:00", "provider": "fixture",
        "data_quality_json": "{}", "status": "unresolved", "reason": "fixture",
    })
    return store


def _artifact():
    return {
        "scope": SIMULATED_FORWARD,
        "automatic_live_promotion": False,
        "live_forward_mutated": False,
        "horizons": {
            "5m": {
                "status": "evaluated", "model_version": "model-a",
                "sample_count": 100, "train_sample_count": 70,
                "validation_sample_count": 30, "purged_training_sample_count": 0,
                "promotion_recommended": True,
                "validation": {
                    "raw_brier": 0.22, "calibrated_brier": 0.18,
                    "brier_improvement": 0.04,
                    "raw_directional_accuracy": 0.56,
                    "calibrated_directional_accuracy": 0.60,
                    "trade_coverage": 0.50, "trade_directional_accuracy": 0.64,
                },
            }
        },
    }


def test_builder_reads_only_matching_settled_live_evidence(tmp_path):
    database = tmp_path / "predictive.db"
    _seed_live_database(database)
    before = database.read_bytes()

    report = LiveForwardValidationReportBuilder(database).build(
        model_version="model-a", horizon="5m"
    )
    after = database.read_bytes()

    assert report["scope"] == LIVE_FORWARD
    assert report["read_only"] is True
    assert report["model_version"] == "model-a"
    assert report["horizon"] == "5m"
    assert report["evaluation_prediction_count"] == 4
    assert report["settled_sample_count"] == 3
    assert report["unsettled_sample_count"] == 1
    assert report["directional_accuracy"] == pytest.approx(2 / 3)
    assert report["mean_brier_up"] == pytest.approx((0.04 + 0.04 + 0.36) / 3)
    assert report["trade_count"] == 2
    assert report["trade_coverage"] == pytest.approx(2 / 3)
    assert report["simulated_forward_included"] is False
    assert report["live_forward_mutated"] is False
    assert before == after


def test_builder_returns_empty_metrics_without_settled_matches(tmp_path):
    database = tmp_path / "predictive.db"
    _seed_live_database(database)

    report = LiveForwardValidationReportBuilder(database).build(
        model_version="missing-model", horizon="5m"
    )

    assert report["settled_sample_count"] == 0
    assert report["directional_accuracy"] is None
    assert report["mean_brier_up"] is None
    assert report["trade_coverage"] == 0.0


def test_promotion_service_feeds_real_store_report_into_registry_gate(tmp_path):
    database = tmp_path / "predictive.db"
    _seed_live_database(database)
    registry = OrionModelRegistry(
        tmp_path / "registry.json",
        config=PromotionConfig(
            min_simulated_validation_samples=20,
            min_live_settled_samples=3,
            min_live_directional_accuracy=0.60,
            max_live_brier=0.20,
            min_live_trade_coverage=0.50,
        ),
    )
    registry.register_learning_artifact(_artifact())
    service = LiveForwardPromotionService(registry=registry, live_database_path=database)

    evaluation = service.evaluate(horizon="5m", model_version="model-a")
    awaiting = service.promote(horizon="5m", model_version="model-a", explicit_approval=False)

    assert evaluation["eligible_for_promotion"] is True
    assert evaluation["live_evidence"]["report_id"] == "live-forward-validation-report-v1"
    assert evaluation["live_evidence"]["scope"] == LIVE_FORWARD
    assert awaiting["promotion_status"] == "awaiting_explicit_approval"
    assert registry.snapshot()["champions"] == {}
