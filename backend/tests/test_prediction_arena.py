from __future__ import annotations

import sqlite3

import pandas as pd

from app.services.market_replay_engine import MarketReplayEngine, ReplayConfig, SIMULATED_FORWARD
from app.services.prediction_arena import ArenaConfig, PredictionArena, SimulatedForwardStore


def _frame(start="2026-01-05 14:30:00+00:00", periods=8, base=100.0):
    index = pd.date_range(start=start, periods=periods, freq="5min")
    return pd.DataFrame(
        {
            "Open": [base + i for i in range(periods)],
            "High": [base + i + 0.5 for i in range(periods)],
            "Low": [base + i - 0.5 for i in range(periods)],
            "Close": [base + i for i in range(periods)],
            "Volume": [1000 + i for i in range(periods)],
        },
        index=index,
    )


def _predictor(stock, benchmark, *, symbol, as_of):
    assert stock.index.max() <= pd.Timestamp(as_of)
    assert benchmark.index.max() <= pd.Timestamp(as_of)
    target = pd.Timestamp(as_of) + pd.Timedelta(minutes=5)
    if target > stock.index.max() + pd.Timedelta(minutes=5):
        return {"symbol": symbol, "available": False, "reason": "no_target"}
    return {
        "symbol": symbol,
        "available": True,
        "design_id": "stub-v1",
        "forward_adapter_id": "stub-forward",
        "model_version": "model-a",
        "as_of": pd.Timestamp(as_of).isoformat(),
        "horizons": {
            "5m": {
                "available": True,
                "probability_up": 0.7,
                "probability_down": 0.3,
                "direction": "bullish",
                "target_time_utc": target.isoformat(),
                "training_samples": 123,
                "training_cutoff": (pd.Timestamp(as_of) - pd.Timedelta(minutes=5)).isoformat(),
                "max_training_timestamp": (pd.Timestamp(as_of) - pd.Timedelta(minutes=5)).isoformat(),
            }
        },
    }


def test_arena_runs_multiple_symbols_and_persists_separately(tmp_path):
    benchmark = _frame(base=500.0)
    universe = {"aaa": _frame(base=100.0), "bbb": _frame(base=200.0)}
    engine = MarketReplayEngine(predictor=_predictor, config=ReplayConfig(stride_bars=2, warmup_bars=2))
    store_path = tmp_path / "simulated-forward.sqlite3"
    store = SimulatedForwardStore(store_path)
    arena = PredictionArena(replay_engine=engine, store=store)

    result = arena.run(universe, benchmark, session_id="session-test")

    assert result["scope"] == SIMULATED_FORWARD
    assert result["symbol_count"] == 2
    assert result["successful_symbol_count"] == 2
    assert result["prediction_count"] > 0
    assert result["persisted_prediction_count"] == result["prediction_count"]
    assert result["live_forward_mutated"] is False
    assert set(result["symbols"]) == {"AAA", "BBB"}
    assert "5m" in result["horizons"]

    persisted = store.session_predictions("session-test")
    assert len(persisted) == result["prediction_count"]
    assert {row["scope"] for row in persisted} == {SIMULATED_FORWARD}
    assert {row["symbol"] for row in persisted} == {"AAA", "BBB"}

    with sqlite3.connect(store_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "simulated_forward_predictions" in tables
    assert "simulated_forward_sessions" in tables
    assert "live_predictions" not in tables
    assert "prediction_outcomes" not in tables


def test_store_deduplicates_same_evidence_across_replay_sessions(tmp_path):
    benchmark = _frame(base=500.0)
    universe = {"AAA": _frame(base=100.0)}
    engine = MarketReplayEngine(predictor=_predictor, config=ReplayConfig(stride_bars=2, warmup_bars=2))
    store_path = tmp_path / "simulated-forward.sqlite3"
    store = SimulatedForwardStore(store_path)
    arena = PredictionArena(replay_engine=engine, store=store)

    first = arena.run(universe, benchmark, session_id="cloud-run-1")
    second = arena.run(universe, benchmark, session_id="cloud-run-2")

    assert first["prediction_count"] > 0
    assert first["persisted_prediction_count"] == first["prediction_count"]
    assert second["prediction_count"] == first["prediction_count"]
    assert second["persisted_prediction_count"] == 0
    assert store.session_predictions("cloud-run-1")
    assert store.session_predictions("cloud-run-2") == []

    with sqlite3.connect(store_path) as connection:
        persisted_count = connection.execute(
            "SELECT COUNT(*) FROM simulated_forward_predictions"
        ).fetchone()[0]
        unique_index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sim_forward_evidence_unique'"
        ).fetchone()
    assert persisted_count == first["prediction_count"]
    assert unique_index is not None


def test_store_rejects_live_forward_rows(tmp_path):
    store = SimulatedForwardStore(tmp_path / "sim.sqlite3")
    store.start_session(session_id="s", config={})
    row = {
        "scope": "LIVE_FORWARD",
        "symbol": "AAA",
        "horizon": "5m",
        "prediction_time_utc": "2026-01-01T00:00:00+00:00",
        "target_time_utc": "2026-01-01T00:05:00+00:00",
        "reference_price": 100.0,
        "probability_up": 0.6,
        "probability_down": 0.4,
        "status": "pending",
    }
    try:
        store.save_predictions("s", [row])
    except ValueError as exc:
        assert "SIMULATED_FORWARD" in str(exc)
    else:
        raise AssertionError("LIVE_FORWARD evidence must be rejected")


def test_arena_collects_symbol_failure_without_poisoning_other_results(tmp_path):
    benchmark = _frame(base=500.0)
    good = _frame(base=100.0)
    bad = good.copy()
    bad.index = pd.DatetimeIndex(list(bad.index[:-1]) + [bad.index[-2]])

    engine = MarketReplayEngine(predictor=_predictor, config=ReplayConfig(stride_bars=2, warmup_bars=2))
    store = SimulatedForwardStore(tmp_path / "sim.sqlite3")
    arena = PredictionArena(replay_engine=engine, store=store, config=ArenaConfig(fail_fast=False))

    result = arena.run({"GOOD": good, "BAD": bad}, benchmark)

    assert result["successful_symbol_count"] == 1
    assert result["failed_symbol_count"] == 1
    assert result["failures"][0]["symbol"] == "BAD"
    assert result["symbols"]["GOOD"]["scope"] == SIMULATED_FORWARD


def test_arena_can_run_without_persistence():
    benchmark = _frame(base=500.0)
    engine = MarketReplayEngine(predictor=_predictor, config=ReplayConfig(stride_bars=2, warmup_bars=2))
    arena = PredictionArena(
        replay_engine=engine,
        store=None,
        config=ArenaConfig(persist_predictions=False),
    )
    result = arena.run({"AAA": _frame(base=100.0)}, benchmark)
    assert result["persisted_prediction_count"] == 0
    assert result["prediction_count"] > 0
