from pathlib import Path

import pandas as pd
import pytest

from app.services.historical_universe_runner import HistoricalUniverseRunner, UniverseRunnerConfig
from app.services.market_replay_engine import SIMULATED_FORWARD


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
    assert result["requested_symbol_count"] == 3
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
    assert '"prediction_count": 6' in text


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
