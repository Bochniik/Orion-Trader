from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.accelerated_learning_cycle import (
    AcceleratedLearningCycle,
    AcceleratedLearningCycleConfig,
)
from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.prediction_arena import SimulatedForwardStore


def _iso(base: datetime, minutes: int) -> str:
    return (base + timedelta(minutes=minutes)).isoformat()


def _seed(path, *, count=100, long_maturity_index=None):
    store = SimulatedForwardStore(path)
    session_id = "walk-forward-fixture"
    store.start_session(session_id=session_id, config={"fixture": True})
    base = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        high_bucket = index % 2 == 0
        p_up = 0.90 if high_bucket else 0.10
        cycle = index % 10
        if high_bucket:
            actual = "UP" if cycle not in {0, 2} else "DOWN"
        else:
            actual = "DOWN" if cycle not in {1, 3} else "UP"
        target_minutes = index + 5
        if long_maturity_index is not None and index == long_maturity_index:
            target_minutes = index + 50
        actual_up = 1 if actual == "UP" else 0
        predicted = "UP" if p_up >= 0.5 else "DOWN"
        rows.append({
            "scope": SIMULATED_FORWARD,
            "symbol": "AAPL",
            "horizon": "5m",
            "prediction_time_utc": _iso(base, index),
            "target_time_utc": _iso(base, target_minutes),
            "reference_price": 100.0,
            "probability_up": p_up,
            "probability_down": 1.0 - p_up,
            "direction": predicted,
            "model_version": "model-a",
            "status": "settled",
            "settled_at_utc": _iso(base, target_minutes + 1),
            "future_price": 101.0 if actual == "UP" else 99.0,
            "realized_return": 0.01 if actual == "UP" else -0.01,
            "actual_direction": actual,
            "direction_correct": int(predicted == actual),
            "brier_up": (p_up - actual_up) ** 2,
        })
    store.save_predictions(session_id, rows)
    store.complete_session(session_id, {
        "symbol_count": 1,
        "prediction_count": len(rows),
        "settled_prediction_count": len(rows),
    })


def test_walk_forward_cycle_uses_only_simulated_unseen_evidence(tmp_path):
    database = tmp_path / "simulated.db"
    _seed(database, count=100)
    before = database.read_bytes()

    cycle = AcceleratedLearningCycle(
        database,
        config=AcceleratedLearningCycleConfig(
            min_train_samples=40,
            fold_size=20,
            min_evaluated_folds=2,
            min_fold_pass_rate=0.5,
            minimum_brier_improvement=0.001,
        ),
    )
    result = cycle.run()

    assert result["scope"] == SIMULATED_FORWARD
    assert result["walk_forward"] is True
    assert result["automatic_live_promotion"] is False
    assert result["live_forward_mutated"] is False
    assert database.read_bytes() == before

    report = result["reports"]["5m::model-a"]
    assert report["evaluated_fold_count"] >= 2
    assert report["out_of_sample_sample_count"] >= 40
    assert report["aggregate"]["brier_improvement"] > 0
    assert report["keep_challenger"] is True
    for fold in report["folds"]:
        if fold["status"] == "evaluated":
            assert fold["train_end_target_time_utc"] < fold["evaluation_start_prediction_time_utc"]
            assert fold["maturity_purge_applied"] is True


def test_walk_forward_cycle_purges_outcome_not_mature_at_fold_start(tmp_path):
    database = tmp_path / "simulated.db"
    _seed(database, count=80, long_maturity_index=39)

    cycle = AcceleratedLearningCycle(
        database,
        config=AcceleratedLearningCycleConfig(
            min_train_samples=40,
            fold_size=20,
            min_evaluated_folds=1,
            min_fold_pass_rate=0.0,
            minimum_brier_improvement=-1.0,
        ),
    )
    result = cycle.run()
    first_fold = result["reports"]["5m::model-a"]["folds"][0]

    assert first_fold["evaluation_start_prediction_time_utc"].endswith("15:10:00+00:00")
    assert first_fold["purged_training_sample_count"] >= 1
    assert first_fold["train_end_target_time_utc"] < first_fold["evaluation_start_prediction_time_utc"]


def test_walk_forward_cycle_requires_multiple_oos_folds_before_keep(tmp_path):
    database = tmp_path / "simulated.db"
    _seed(database, count=60)

    cycle = AcceleratedLearningCycle(
        database,
        config=AcceleratedLearningCycleConfig(
            min_train_samples=40,
            fold_size=20,
            min_evaluated_folds=2,
            min_fold_pass_rate=0.0,
            minimum_brier_improvement=-1.0,
            max_accuracy_degradation=1.0,
        ),
    )
    report = cycle.run()["reports"]["5m::model-a"]

    assert report["evaluated_fold_count"] == 1
    assert report["gates"]["enough_folds"] is False
    assert report["keep_challenger"] is False
