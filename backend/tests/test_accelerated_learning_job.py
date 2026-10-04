from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import accelerated_learning_job as job
from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.prediction_arena import SimulatedForwardStore


def _iso(base: datetime, minutes: int) -> str:
    return (base + timedelta(minutes=minutes)).isoformat()


def _seed_simulated(path, *, count: int = 100) -> None:
    store = SimulatedForwardStore(path)
    session_id = "accelerated-job-fixture"
    store.start_session(session_id=session_id, config={"fixture": True})
    base = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        p_up = 0.90 if index % 2 == 0 else 0.10
        cycle = index % 10
        if index % 2 == 0:
            actual = "UP" if cycle not in {0, 2} else "DOWN"
        else:
            actual = "DOWN" if cycle not in {1, 3} else "UP"
        actual_up = int(actual == "UP")
        predicted = "UP" if p_up >= 0.5 else "DOWN"
        rows.append({
            "scope": SIMULATED_FORWARD,
            "symbol": "AAPL",
            "horizon": "5m",
            "prediction_time_utc": _iso(base, index),
            "target_time_utc": _iso(base, index + 5),
            "reference_price": 100.0,
            "probability_up": p_up,
            "probability_down": 1.0 - p_up,
            "direction": predicted,
            "model_version": "model-a",
            "status": "settled",
            "settled_at_utc": _iso(base, index + 6),
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


def test_end_to_end_job_runs_replay_learning_and_walk_forward(monkeypatch, tmp_path):
    database = tmp_path / "simulated.db"
    checkpoint = tmp_path / "checkpoint.json"
    learning_artifact = tmp_path / "learning.json"
    cycle_artifact = tmp_path / "cycle.json"
    _seed_simulated(database)
    before = database.read_bytes()
    replay_calls = []

    def fake_replay_job(**kwargs):
        replay_calls.append(kwargs)
        return {
            "scope": SIMULATED_FORWARD,
            "run_id": kwargs.get("run_id") or "fixture-run",
            "prediction_count": 100,
            "settled_prediction_count": 100,
            "live_forward_mutated": False,
        }

    monkeypatch.setattr(job, "run_replay_job", fake_replay_job)

    result = job.run_accelerated_learning_job(
        simulated_db=database,
        checkpoint_path=checkpoint,
        learning_artifact_path=learning_artifact,
        cycle_artifact_path=cycle_artifact,
        top_n=25,
        candidate_limit=250,
        minimum_adv=50_000_000.0,
        period="30d",
        interval="5m",
        batch_size=5,
        prepost=True,
        run_id="fixture-run",
    )

    assert replay_calls == [{
        "simulated_db": database,
        "checkpoint_path": checkpoint,
        "top_n": 25,
        "candidate_limit": 250,
        "minimum_adv": 50_000_000.0,
        "period": "30d",
        "interval": "5m",
        "batch_size": 5,
        "prepost": True,
        "run_id": "fixture-run",
    }]
    assert result["scope"] == SIMULATED_FORWARD
    assert result["replay"]["scope"] == SIMULATED_FORWARD
    assert result["learning"]["scope"] == SIMULATED_FORWARD
    assert result["walk_forward"]["scope"] == SIMULATED_FORWARD
    assert result["automatic_live_promotion"] is False
    assert result["live_forward_mutated"] is False
    assert database.read_bytes() == before
    assert learning_artifact.exists()
    assert cycle_artifact.exists()
    assert result["walk_forward"]["reports"]["5m::model-a"]["evaluated_fold_count"] >= 2


def test_end_to_end_job_rejects_non_simulated_stage(monkeypatch, tmp_path):
    database = tmp_path / "simulated.db"
    _seed_simulated(database)

    monkeypatch.setattr(job, "run_replay_job", lambda **kwargs: {
        "scope": "LIVE_FORWARD",
        "live_forward_mutated": False,
    })

    import pytest
    with pytest.raises(RuntimeError, match="replay returned non-simulated scope"):
        job.run_accelerated_learning_job(
            simulated_db=database,
            checkpoint_path=tmp_path / "checkpoint.json",
            learning_artifact_path=None,
            cycle_artifact_path=None,
        )
