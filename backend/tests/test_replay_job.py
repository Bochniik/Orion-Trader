from pathlib import Path

import pytest

from app.services import replay_job


class _FakeStore:
    def __init__(self, path):
        self.path = Path(path)


class _FakeArena:
    def __init__(self, *, store):
        self.store = store


class _FakeRunner:
    def __init__(self, *, arena, config, checkpoint_path):
        self.arena = arena
        self.config = config
        self.checkpoint_path = Path(checkpoint_path)


class _FakeSelector:
    def __init__(self, *, config):
        self.config = config


class _FakeOrchestrator:
    def __init__(self, *, selector, runner):
        self.selector = selector
        self.runner = runner
        self.run_ids = []

    def run(self, *, run_id=None):
        self.run_ids.append(run_id)
        return {
            "scope": "SIMULATED_FORWARD",
            "live_forward_mutated": False,
            "run_id": run_id,
        }


def _patch_stack(monkeypatch):
    monkeypatch.setattr(replay_job, "SimulatedForwardStore", _FakeStore)
    monkeypatch.setattr(replay_job, "PredictionArena", _FakeArena)
    monkeypatch.setattr(replay_job, "HistoricalUniverseRunner", _FakeRunner)
    monkeypatch.setattr(replay_job, "ReplayLiquidityUniverseSelector", _FakeSelector)
    monkeypatch.setattr(replay_job, "ReplayUniverseOrchestrator", _FakeOrchestrator)


def test_build_replay_job_wires_dedicated_simulated_store(monkeypatch, tmp_path):
    _patch_stack(monkeypatch)
    simulated_db = tmp_path / "simulated_forward.db"
    checkpoint = tmp_path / "replay_checkpoint.json"

    orchestrator = replay_job.build_replay_job(
        simulated_db=simulated_db,
        checkpoint_path=checkpoint,
        top_n=42,
        candidate_limit=333,
        minimum_adv=50_000_000,
        period="30d",
        interval="5m",
        batch_size=7,
        prepost=True,
    )

    assert orchestrator.runner.arena.store.path == simulated_db
    assert orchestrator.runner.checkpoint_path == checkpoint
    assert orchestrator.runner.config.period == "30d"
    assert orchestrator.runner.config.interval == "5m"
    assert orchestrator.runner.config.batch_size == 7
    assert orchestrator.runner.config.prepost is True
    assert orchestrator.selector.config.top_n == 42
    assert orchestrator.selector.config.candidate_limit == 333
    assert orchestrator.selector.config.minimum_average_dollar_volume == 50_000_000


def test_run_replay_job_forwards_explicit_run_id(monkeypatch, tmp_path):
    _patch_stack(monkeypatch)

    summary = replay_job.run_replay_job(
        simulated_db=tmp_path / "sim.db",
        checkpoint_path=tmp_path / "checkpoint.json",
        run_id="replay-test-001",
    )

    assert summary["scope"] == "SIMULATED_FORWARD"
    assert summary["live_forward_mutated"] is False
    assert summary["run_id"] == "replay-test-001"


def test_main_accepts_simulation_only_summary(monkeypatch, capsys):
    monkeypatch.setattr(
        replay_job,
        "run_replay_job",
        lambda **kwargs: {
            "scope": "SIMULATED_FORWARD",
            "live_forward_mutated": False,
            "run_id": kwargs.get("run_id"),
        },
    )

    assert replay_job.main(["--run-id", "safe-run"]) == 0
    output = capsys.readouterr().out
    assert '"scope": "SIMULATED_FORWARD"' in output
    assert '"run_id": "safe-run"' in output


@pytest.mark.parametrize(
    "summary",
    [
        {"scope": "LIVE_FORWARD", "live_forward_mutated": False},
        {"scope": "SIMULATED_FORWARD", "live_forward_mutated": True},
        {"scope": "SIMULATED_FORWARD"},
    ],
)
def test_main_rejects_any_live_forward_contract_violation(monkeypatch, summary):
    monkeypatch.setattr(replay_job, "run_replay_job", lambda **kwargs: summary)

    with pytest.raises(RuntimeError, match="simulation-only persistence contract"):
        replay_job.main([])
