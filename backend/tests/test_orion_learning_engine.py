from __future__ import annotations

import json
import sqlite3

from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.orion_learning_engine import LearningConfig, OrionLearningEngine
from app.services.prediction_arena import SimulatedForwardStore


def _rows(count: int, *, horizon: str = "5m", model_version: str = "model-a"):
    rows = []
    for index in range(count):
        # Deliberately overconfident raw probabilities. Later samples form validation.
        actual_up = (index % 4) in (0, 1)
        if actual_up:
            probability_up = 0.90 if index % 3 else 0.70
            actual_direction = "UP"
        else:
            probability_up = 0.10 if index % 3 else 0.30
            actual_direction = "DOWN"
        rows.append({
            "scope": SIMULATED_FORWARD,
            "symbol": "AAPL",
            "horizon": horizon,
            "prediction_time_utc": f"2026-01-{index // 24 + 1:02d}T{index % 24:02d}:00:00+00:00",
            "target_time_utc": f"2026-01-{index // 24 + 1:02d}T{index % 24:02d}:05:00+00:00",
            "reference_price": 100.0,
            "probability_up": probability_up,
            "probability_down": 1.0 - probability_up,
            "direction": "UP" if probability_up >= 0.5 else "DOWN",
            "model_version": model_version,
            "design_id": "design-test",
            "forward_adapter_id": "adapter-test",
            "training_samples": 100,
            "training_cutoff": "2025-12-31T00:00:00+00:00",
            "max_training_timestamp": "2025-12-31T00:00:00+00:00",
            "status": "settled",
            "settled_at_utc": f"2026-01-{index // 24 + 1:02d}T{index % 24:02d}:05:00+00:00",
            "future_price": 101.0 if actual_up else 99.0,
            "realized_return": 0.01 if actual_up else -0.01,
            "actual_direction": actual_direction,
            "direction_correct": True,
            "brier_up": (probability_up - int(actual_up)) ** 2,
        })
    return rows


def _seed_database(path, rows):
    store = SimulatedForwardStore(path)
    store.start_session(session_id="learning-source", config={"scope": SIMULATED_FORWARD})
    inserted = store.save_predictions("learning-source", rows)
    store.complete_session("learning-source", {
        "scope": SIMULATED_FORWARD,
        "symbol_count": 1,
        "prediction_count": inserted,
        "settled_prediction_count": inserted,
    })
    return inserted


def test_learning_engine_builds_chronological_challenger(tmp_path):
    database = tmp_path / "simulated.db"
    _seed_database(database, _rows(80))

    engine = OrionLearningEngine(
        database,
        config=LearningConfig(min_samples_per_horizon=40, validation_fraction=0.25),
    )
    artifact = engine.build_challenger()

    assert artifact["scope"] == SIMULATED_FORWARD
    assert artifact["learning_engine_id"] == "orion-learning-engine-v1"
    assert artifact["settled_sample_count"] == 80
    assert artifact["automatic_live_promotion"] is False
    assert artifact["live_forward_mutated"] is False

    report = artifact["horizons"]["5m"]
    assert report["status"] == "evaluated"
    assert report["train_sample_count"] == 60
    assert report["validation_sample_count"] == 20
    assert report["train_end_prediction_time_utc"] < report["validation_start_prediction_time_utc"]
    assert 0.50 <= report["no_trade_policy"]["confidence_threshold"] <= 0.75
    assert report["validation"]["raw_brier"] is not None
    assert report["validation"]["calibrated_brier"] is not None
    assert len(report["calibration_bins"]) == 10


def test_learning_engine_reports_insufficient_samples(tmp_path):
    database = tmp_path / "simulated.db"
    _seed_database(database, _rows(12, horizon="3h"))

    artifact = OrionLearningEngine(
        database,
        config=LearningConfig(min_samples_per_horizon=20),
    ).build_challenger()

    report = artifact["horizons"]["3h"]
    assert report["status"] == "insufficient_samples"
    assert report["sample_count"] == 12
    assert report["promotion_recommended"] is False


def test_learning_engine_writes_offline_artifact_only(tmp_path):
    database = tmp_path / "simulated.db"
    output = tmp_path / "learning" / "challenger.json"
    _seed_database(database, _rows(48))

    before = database.read_bytes()
    artifact = OrionLearningEngine(
        database,
        config=LearningConfig(min_samples_per_horizon=20),
    ).build_challenger(output_path=output)
    after = database.read_bytes()

    assert output.exists()
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["scope"] == SIMULATED_FORWARD
    assert persisted["automatic_live_promotion"] is False
    assert artifact["live_forward_mutated"] is False
    assert before == after

    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "live_predictions" not in tables
    assert "prediction_outcomes" not in tables


def test_learning_engine_ignores_pending_predictions(tmp_path):
    database = tmp_path / "simulated.db"
    settled = _rows(20)
    pending = dict(settled[0])
    pending["prediction_time_utc"] = "2026-02-01T00:00:00+00:00"
    pending["target_time_utc"] = "2026-02-01T00:05:00+00:00"
    pending["status"] = "pending"
    pending["actual_direction"] = None
    pending["direction_correct"] = None
    pending["brier_up"] = None
    _seed_database(database, [*settled, pending])

    artifact = OrionLearningEngine(
        database,
        config=LearningConfig(min_samples_per_horizon=20),
    ).build_challenger()

    assert artifact["settled_sample_count"] == 20
