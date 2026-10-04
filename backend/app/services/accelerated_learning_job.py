"""End-to-end accelerated learning job for OrionTrader.

Runs the historical replay into the dedicated SIMULATED_FORWARD store, then builds a
learning challenger and evaluates it with the walk-forward accelerated-learning cycle.
The job never reads from or mutates LIVE_FORWARD state and never promotes a model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.accelerated_learning_cycle import AcceleratedLearningCycle
from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.orion_learning_engine import OrionLearningEngine
from app.services.replay_job import run_replay_job

JOB_ID = "accelerated-learning-job-v1"


def _assert_simulation_only(payload: dict[str, Any], *, stage: str) -> None:
    if payload.get("scope") != SIMULATED_FORWARD:
        raise RuntimeError(f"{stage} returned non-simulated scope")
    if payload.get("live_forward_mutated") is not False:
        raise RuntimeError(f"{stage} violated simulation-only persistence contract")


def run_accelerated_learning_job(
    *,
    simulated_db: str | Path = "data/simulated_forward.db",
    checkpoint_path: str | Path = "data/replay_checkpoint.json",
    learning_artifact_path: str | Path | None = "data/learning_challenger.json",
    cycle_artifact_path: str | Path | None = "data/accelerated_learning_cycle.json",
    top_n: int = 100,
    candidate_limit: int = 1000,
    minimum_adv: float = 25_000_000.0,
    period: str = "60d",
    interval: str = "5m",
    batch_size: int = 10,
    prepost: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run replay -> learning -> walk-forward evaluation as one offline job."""
    simulated_db = Path(simulated_db)
    checkpoint_path = Path(checkpoint_path)

    replay = run_replay_job(
        simulated_db=simulated_db,
        checkpoint_path=checkpoint_path,
        top_n=top_n,
        candidate_limit=candidate_limit,
        minimum_adv=minimum_adv,
        period=period,
        interval=interval,
        batch_size=batch_size,
        prepost=prepost,
        run_id=run_id,
    )
    _assert_simulation_only(replay, stage="replay")

    learning = OrionLearningEngine(simulated_db).build_challenger(
        output_path=learning_artifact_path
    )
    _assert_simulation_only(learning, stage="learning")

    cycle = AcceleratedLearningCycle(simulated_db).run(output_path=cycle_artifact_path)
    _assert_simulation_only(cycle, stage="walk-forward cycle")

    kept = list(cycle.get("kept_challengers") or [])
    result = {
        "job_id": JOB_ID,
        "scope": SIMULATED_FORWARD,
        "run_id": replay.get("run_id") or replay.get("session_id") or run_id,
        "simulated_database": str(simulated_db),
        "checkpoint_path": str(checkpoint_path),
        "replay": replay,
        "learning": learning,
        "walk_forward": cycle,
        "kept_challengers": kept,
        "kept_challenger_count": len(kept),
        "automatic_live_promotion": False,
        "live_forward_mutated": False,
    }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Orion replay, learning, and walk-forward evaluation offline"
    )
    parser.add_argument("--simulated-db", default="data/simulated_forward.db")
    parser.add_argument("--checkpoint", default="data/replay_checkpoint.json")
    parser.add_argument("--learning-artifact", default="data/learning_challenger.json")
    parser.add_argument("--cycle-artifact", default="data/accelerated_learning_cycle.json")
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--candidate-limit", type=int, default=1000)
    parser.add_argument("--minimum-adv", type=float, default=25_000_000.0)
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--prepost", action="store_true")
    parser.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_accelerated_learning_job(
        simulated_db=args.simulated_db,
        checkpoint_path=args.checkpoint,
        learning_artifact_path=args.learning_artifact,
        cycle_artifact_path=args.cycle_artifact,
        top_n=args.top_n,
        candidate_limit=args.candidate_limit,
        minimum_adv=args.minimum_adv,
        period=args.period,
        interval=args.interval,
        batch_size=args.batch_size,
        prepost=args.prepost,
        run_id=args.run_id,
    )
    _assert_simulation_only(result, stage="accelerated learning job")
    print(json.dumps(result, default=str, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
