from __future__ import annotations

from app.services.market_replay_engine import LIVE_FORWARD, SIMULATED_FORWARD
from app.services.model_registry import OrionModelRegistry, PromotionConfig


def _artifact(*, model_version="model-a", horizon="5m", recommended=True, validation_samples=40):
    return {
        "learning_engine_id": "orion-learning-engine-v1",
        "scope": SIMULATED_FORWARD,
        "automatic_live_promotion": False,
        "live_forward_mutated": False,
        "horizons": {
            horizon: {
                "status": "evaluated",
                "model_version": model_version,
                "sample_count": 100,
                "train_sample_count": 60,
                "validation_sample_count": validation_samples,
                "purged_training_sample_count": 0,
                "promotion_recommended": recommended,
                "validation": {
                    "raw_brier": 0.23,
                    "calibrated_brier": 0.20,
                    "brier_improvement": 0.03,
                    "raw_directional_accuracy": 0.55,
                    "calibrated_directional_accuracy": 0.58,
                    "trade_coverage": 0.50,
                    "trade_directional_accuracy": 0.62,
                },
            }
        },
    }


def _live(*, model_version="model-a", horizon="5m", settled=50, accuracy=0.60, brier=0.20, coverage=0.50):
    return {
        "scope": LIVE_FORWARD,
        "model_version": model_version,
        "horizon": horizon,
        "settled_sample_count": settled,
        "directional_accuracy": accuracy,
        "mean_brier_up": brier,
        "trade_coverage": coverage,
    }


def test_registry_registers_simulated_challenger_without_live_mutation(tmp_path):
    path = tmp_path / "registry.json"
    registry = OrionModelRegistry(path)

    result = registry.register_learning_artifact(_artifact())

    assert result["registered"] == ["5m::model-a"]
    assert result["automatic_live_promotion"] is False
    assert result["live_forward_mutated"] is False
    snapshot = registry.snapshot()
    assert snapshot["models"]["5m::model-a"]["status"] == "challenger"
    assert snapshot["champions"] == {}


def test_registry_rejects_non_simulated_learning_artifact(tmp_path):
    registry = OrionModelRegistry(tmp_path / "registry.json")
    artifact = _artifact()
    artifact["scope"] = LIVE_FORWARD

    try:
        registry.register_learning_artifact(artifact)
    except ValueError as exc:
        assert "SIMULATED_FORWARD" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_promotion_is_blocked_without_valid_live_forward_evidence(tmp_path):
    registry = OrionModelRegistry(
        tmp_path / "registry.json",
        config=PromotionConfig(min_live_settled_samples=30),
    )
    registry.register_learning_artifact(_artifact())

    invalid = _live(settled=10, accuracy=0.40, brier=0.40, coverage=0.05)
    result = registry.promote(
        horizon="5m",
        model_version="model-a",
        live_evidence=invalid,
        explicit_approval=True,
    )

    assert result["promoted"] is False
    assert result["promotion_status"] == "blocked"
    assert "insufficient_live_settled_samples" in result["blockers"]
    assert "live_directional_accuracy_below_gate" in result["blockers"]
    assert "live_brier_above_gate" in result["blockers"]
    assert registry.snapshot()["champions"] == {}


def test_promotion_requires_explicit_approval_even_when_all_gates_pass(tmp_path):
    registry = OrionModelRegistry(tmp_path / "registry.json")
    registry.register_learning_artifact(_artifact())

    result = registry.promote(
        horizon="5m",
        model_version="model-a",
        live_evidence=_live(),
        explicit_approval=False,
    )

    assert result["eligible_for_promotion"] is True
    assert result["promoted"] is False
    assert result["promotion_status"] == "awaiting_explicit_approval"
    assert registry.snapshot()["champions"] == {}


def test_explicit_promotion_sets_champion_without_live_store_mutation(tmp_path):
    registry = OrionModelRegistry(tmp_path / "registry.json")
    registry.register_learning_artifact(_artifact())

    result = registry.promote(
        horizon="5m",
        model_version="model-a",
        live_evidence=_live(),
        explicit_approval=True,
    )

    assert result["promoted"] is True
    assert result["champion_key"] == "5m::model-a"
    assert result["automatic_live_promotion"] is False
    assert result["live_forward_mutated"] is False
    snapshot = registry.snapshot()
    assert snapshot["champions"]["5m"] == "5m::model-a"
    assert snapshot["models"]["5m::model-a"]["status"] == "champion"


def test_new_champion_archives_previous_champion(tmp_path):
    registry = OrionModelRegistry(tmp_path / "registry.json")
    registry.register_learning_artifact(_artifact(model_version="model-a"))
    registry.promote(
        horizon="5m",
        model_version="model-a",
        live_evidence=_live(model_version="model-a"),
        explicit_approval=True,
    )

    registry.register_learning_artifact(_artifact(model_version="model-b"))
    result = registry.promote(
        horizon="5m",
        model_version="model-b",
        live_evidence=_live(model_version="model-b"),
        explicit_approval=True,
    )

    assert result["previous_champion"] == "5m::model-a"
    snapshot = registry.snapshot()
    assert snapshot["champions"]["5m"] == "5m::model-b"
    assert snapshot["models"]["5m::model-a"]["status"] == "archived_champion"
    assert snapshot["models"]["5m::model-b"]["status"] == "champion"


def test_model_and_horizon_mismatch_block_promotion(tmp_path):
    registry = OrionModelRegistry(tmp_path / "registry.json")
    registry.register_learning_artifact(_artifact())

    evidence = _live(model_version="model-b", horizon="15m")
    result = registry.evaluate_promotion(
        horizon="5m",
        model_version="model-a",
        live_evidence=evidence,
    )

    assert result["eligible_for_promotion"] is False
    assert "live_evidence_horizon_mismatch" in result["blockers"]
    assert "live_evidence_model_version_mismatch" in result["blockers"]
