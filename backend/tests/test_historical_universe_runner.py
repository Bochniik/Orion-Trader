from pathlib import Path
import json

import pandas as pd
import pytest

from app.services.historical_universe_runner import HistoricalUniverseRunner, UniverseRunnerConfig
from app.services.market_replay_engine import REPLAY_ENGINE_ID, SIMULATED_FORWARD


def _frame(start="2026-09-01 13:30", periods=20):
    index = pd.date_range(start, periods=periods, freq="5min", tz="UTC")
    base = pd.Series(range(periods), index=index, dtype=float) + 100.0
    return pd.DataFrame({
        "Open": base,
        "High": base + 1.0,
        "Low": base - 1.0,
        "Close": base + 0.5,
        "Volume": 1000.0,
    }, index=index)


class FakeArena:
    def __init__(self):
        self.calls = []

    def run(self, universe, benchmark, *, decision_times_by_symbol=None, session_id=None):
        self.calls.append((sorted(universe), session_id, decision_times_by_symbol))
        symbols = {symbol: {"prediction_count": 2} for symbol in universe}
        return {
            "scope": SIMULATED_FORWARD,
            "prediction_count": len(universe) * 2,
            "settled_prediction_count": len(universe) * 2,
            "failed_symbol_count": 0,
            "symbols": symbols,
            "horizons": {
                "5m": {
                    "settled_count": len(universe) * 2,
                    "mean_brier_up": 0.2,
                    "directional_accuracy": 0.75,
                }
            },
        }


def test_runner_batches_universe_and_writes_checkpoint(tmp_path):
    frames = {symbol: _frame() for symbol in ("SPY", "AAPL", "MSFT", "NVDA")}

    def loader(symbol, **kwargs):
        assert kwargs["period"] == "60d"
        assert kwargs["interval"] == "5m"
        assert kwargs["prepost"] is False
        return frames[symbol]

    arena = FakeArena()
    checkpoint = tmp_path / "replay-checkpoint.json"
    runner = HistoricalUniverseRunner(
        arena=arena,
        loader=loader,
        config=UniverseRunnerConfig(batch_size=2),
        checkpoint_path=checkpoint,
    )

    result = runner.run(["AAPL", "MSFT", "NVDA"], run_id="run-1")

    assert result["scope"] == SIMULATED_FORWARD
    assert result["replay_engine_id"] == REPLAY_ENGINE_ID
    assert result["requested_symbol_count"] == 3
    assert result["resumed_symbol_count"] == 0
    assert result["processed_symbol_count"] == 3
    assert result["successful_symbol_count"] == 3
    assert result["prediction_count"] == 6
    assert result["settled_prediction_count"] == 6
    assert result["mean_brier_up"] == pytest.approx(0.2)
    assert result["directional_accuracy"] == pytest.approx(0.75)
    assert result["live_forward_mutated"] is False
    assert len(arena.calls) == 2
    assert arena.calls[0][1] == "run-1:batch-1"
    assert arena.calls[1][1] == "run-1:batch-2"
    assert checkpoint.exists()
    text = checkpoint.read_text(encoding="utf-8")
    assert '"scope": "SIMULATED_FORWARD"' in text
    assert f'"replay_engine_id": "{REPLAY_ENGINE_ID}"' in text
    assert '"prediction_count": 6' in text
    assert '"period": "60d"' in text


def test_runner_resumes_checkpoint_without_reprocessing_completed_symbols(tmp_path):
    frames = {symbol: _frame() for symbol in ("SPY", "AAPL", "MSFT", "NVDA")}
    loaded = []

    def loader(symbol, **kwargs):
        loaded.append(symbol)
        return frames[symbol]

    checkpoint = tmp_path / "replay-checkpoint.json"
    first_arena = FakeArena()
    first = HistoricalUniverseRunner(
        arena=first_arena,
        loader=loader,
        config=UniverseRunnerConfig(batch_size=2),
        checkpoint_path=checkpoint,
    ).run(["AAPL", "MSFT"], run_id="first")
    assert first["prediction_count"] == 4

    loaded.clear()
    resumed_arena = FakeArena()
    resumed = HistoricalUniverseRunner(
        arena=resumed_arena,
        loader=loader,
        config=UniverseRunnerConfig(batch_size=2),
        checkpoint_path=checkpoint,
    ).run(["AAPL", "MSFT", "NVDA"], run_id="second")

    assert resumed["requested_symbol_count"] == 3
    assert resumed["resumed_symbol_count"] == 2
    assert resumed["processed_symbol_count"] == 1
    assert resumed["successful_symbol_count"] == 3
    assert resumed["prediction_count"] == 6
    assert resumed["settled_prediction_count"] == 6
    assert resumed["mean_brier_up"] == pytest.approx(0.2)
    assert resumed["directional_accuracy"] == pytest.approx(0.75)
    assert resumed_arena.calls == [(["NVDA"], "second:batch-1", None)]
    assert loaded == ["SPY", "NVDA"]

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["completed_symbols"] == ["AAPL", "MSFT", "NVDA"]
    assert payload["prediction_count"] == 6
    assert payload["settled_prediction_count"] == 6
    assert payload["brier_count"] == 6
    assert payload["direction_count"] == 6


def test_runner_all_completed_is_noop_and_does_not_load_market_data(tmp_path):
    frames = {symbol: _frame() for symbol in ("SPY", "AAPL")}

    def loader(symbol, **kwargs):
        return frames[symbol]

    checkpoint = tmp_path / "replay-checkpoint.json"
    HistoricalUniverseRunner(
        arena=FakeArena(),
        loader=loader,
        checkpoint_path=checkpoint,
    ).run(["AAPL"], run_id="first")

    def forbidden_loader(symbol, **kwargs):
        raise AssertionError("no market data should be loaded for a completed replay universe")

    arena = FakeArena()
    result = HistoricalUniverseRunner(
        arena=arena,
        loader=forbidden_loader,
        checkpoint_path=checkpoint,
    ).run(["AAPL"], run_id="second")

    assert result["resumed_symbol_count"] == 1
    assert result["processed_symbol_count"] == 0
    assert result["prediction_count"] == 2
    assert result["settled_prediction_count"] == 2
    assert result["batches"] == []
    assert arena.calls == []


def test_runner_rejects_checkpoint_from_incompatible_configuration(tmp_path):
    checkpoint = tmp_path / "replay-checkpoint.json"
    checkpoint.write_text(json.dumps({
        "runner_id": "historical-universe-runner-v1",
        "replay_engine_id": REPLAY_ENGINE_ID,
        "scope": SIMULATED_FORWARD,
        "period": "30d",
        "interval": "5m",
        "prepost": False,
        "benchmark_symbol": "SPY",
        "completed_symbols": ["AAPL"],
    }), encoding="utf-8")

    runner = HistoricalUniverseRunner(
        arena=FakeArena(),
        loader=lambda symbol, **kwargs: _frame(),
        config=UniverseRunnerConfig(period="60d"),
        checkpoint_path=checkpoint,
    )

    with pytest.raises(ValueError, match="checkpoint configuration mismatch: period"):
        runner.run(["AAPL"])


def test_runner_replays_symbols_when_checkpoint_engine_version_is_stale(tmp_path):
    frames = {symbol: _frame() for symbol in ("SPY", "AAPL")}
    checkpoint = tmp_path / "replay-checkpoint.json"
    checkpoint.write_text(json.dumps({
        "runner_id": "historical-universe-runner-v1",
        "replay_engine_id": "market-replay-v1",
        "scope": SIMULATED_FORWARD,
        "period": "60d",
        "interval": "5m",
        "prepost": False,
        "benchmark_symbol": "SPY",
        "completed_symbols": ["AAPL"],
        "prediction_count": 0,
        "settled_prediction_count": 0,
    }), encoding="utf-8")

    loaded = []

    def loader(symbol, **kwargs):
        loaded.append(symbol)
        return frames[symbol]

    arena = FakeArena()
    result = HistoricalUniverseRunner(
        arena=arena,
        loader=loader,
        checkpoint_path=checkpoint,
    ).run(["AAPL"], run_id="replay-v2")

    assert result["resumed_symbol_count"] == 0
    assert result["processed_symbol_count"] == 1
    assert result["prediction_count"] == 2
    assert arena.calls == [(["AAPL"], "replay-v2:batch-1", None)]
    assert loaded == ["SPY", "AAPL"]
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["replay_engine_id"] == REPLAY_ENGINE_ID


def test_runner_can_disable_checkpoint_resume(tmp_path):
    frames = {symbol: _frame() for symbol in ("SPY", "AAPL")}

    def loader(symbol, **kwargs):
        return frames[symbol]

    checkpoint = tmp_path / "replay-checkpoint.json"
    HistoricalUniverseRunner(
        arena=FakeArena(),
        loader=loader,
        checkpoint_path=checkpoint,
    ).run(["AAPL"], run_id="first")

    arena = FakeArena()
    result = HistoricalUniverseRunner(
        arena=arena,
        loader=loader,
        config=UniverseRunnerConfig(resume_from_checkpoint=False),
        checkpoint_path=checkpoint,
    ).run(["AAPL"], run_id="fresh")

    assert result["resumed_symbol_count"] == 0
    assert result["processed_symbol_count"] == 1
    assert result["prediction_count"] == 2
    assert len(arena.calls) == 1


def test_runner_continues_after_symbol_download_failure():
    frames = {"SPY": _frame(), "AAPL": _frame()}

    def loader(symbol, **kwargs):
        if symbol == "BROKEN":
            raise RuntimeError("provider unavailable")
        return frames[symbol]

    runner = HistoricalUniverseRunner(
        arena=FakeArena(),
        loader=loader,
        config=UniverseRunnerConfig(batch_size=10, continue_on_symbol_error=True),
    )
    result = runner.run(["AAPL", "BROKEN"], run_id="run-errors")

    assert result["successful_symbol_count"] == 1
    assert result["failed_symbol_count"] == 1
    assert result["failures"][0]["symbol"] == "BROKEN"
    assert "provider unavailable" in result["failures"][0]["error"]


def test_runner_fail_fast_on_download_failure():
    def loader(symbol, **kwargs):
        if symbol == "SPY":
            return _frame()
        raise RuntimeError("boom")

    runner = HistoricalUniverseRunner(
        arena=FakeArena(),
        loader=loader,
        config=UniverseRunnerConfig(continue_on_symbol_error=False),
    )

    try:
        runner.run(["AAPL"])
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError")


def test_runner_rejects_duplicate_historical_timestamps():
    frame = _frame()
    broken = pd.concat([frame, frame.iloc[[-1]]])

    def loader(symbol, **kwargs):
        return frame if symbol == "SPY" else broken

    result = HistoricalUniverseRunner(
        arena=FakeArena(),
        loader=loader,
        config=UniverseRunnerConfig(continue_on_symbol_error=True),
    ).run(["AAPL"])

    assert result["successful_symbol_count"] == 0
    assert result["failed_symbol_count"] == 1
    assert "duplicate timestamps" in result["failures"][0]["error"]


def test_runner_passes_symbol_specific_decision_times():
    frames = {symbol: _frame() for symbol in ("SPY", "AAPL")}

    def loader(symbol, **kwargs):
        return frames[symbol]

    arena = FakeArena()
    decision_time = frames["AAPL"].index[5]
    HistoricalUniverseRunner(arena=arena, loader=loader).run(
        ["AAPL"],
        run_id="run-decisions",
        decision_times_by_symbol={"AAPL": [decision_time]},
    )

    assert arena.calls[0][2] == {"AAPL": [decision_time]}
