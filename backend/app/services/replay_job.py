"""Executable accelerated-learning replay job.

Builds Orion's dedicated SIMULATED_FORWARD stack and runs the liquidity-selected
historical universe without touching the LIVE_FORWARD store.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.historical_universe_runner import HistoricalUniverseRunner, UniverseRunnerConfig
from app.services.prediction_arena import PredictionArena, SimulatedForwardStore
from app.services.replay_universe_orchestrator import ReplayUniverseOrchestrator
from app.services.replay_universe_selector import ReplayLiquidityUniverseSelector, ReplayUniverseSelectionConfig


def build_replay_job(
    *,
    simulated_db: str | Path,
    checkpoint_path: str | Path,
    top_n: int = 100,
    candidate_limit: int = 1000,
    minimum_adv: float = 25_000_000.0,
    period: str = "60d",
    interval: str = "5m",
    batch_size: int = 10,
    prepost: bool = False,
) -> ReplayUniverseOrchestrator:
    """Construct the production replay stack with simulation-only persistence."""
    store = SimulatedForwardStore(simulated_db)
    arena = PredictionArena(store=store)
    runner = HistoricalUniverseRunner(
        arena=arena,
        config=UniverseRunnerConfig(
            period=period,
            interval=interval,
            batch_size=batch_size,
            prepost=prepost,
        ),
        checkpoint_path=checkpoint_path,
    )
    selector = ReplayLiquidityUniverseSelector(
        config=ReplayUniverseSelectionConfig(
            top_n=top_n,
            candidate_limit=candidate_limit,
            minimum_average_dollar_volume=minimum_adv,
        )
    )
    return ReplayUniverseOrchestrator(selector=selector, runner=runner)


def run_replay_job(**kwargs: Any) -> dict[str, Any]:
    run_id = kwargs.pop("run_id", None)
    return build_replay_job(**kwargs).run(run_id=run_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Orion accelerated historical replay")
    parser.add_argument("--simulated-db", default="data/simulated_forward.db")
    parser.add_argument("--checkpoint", default="data/replay_checkpoint.json")
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
    summary = run_replay_job(
        simulated_db=args.simulated_db,
        checkpoint_path=args.checkpoint,
        top_n=args.top_n,
        candidate_limit=args.candidate_limit,
        minimum_adv=args.minimum_adv,
        period=args.period,
        interval=args.interval,
        batch_size=args.batch_size,
        prepost=args.prepost,
        run_id=args.run_id,
    )
    if summary.get("scope") != "SIMULATED_FORWARD" or summary.get("live_forward_mutated") is not False:
        raise RuntimeError("Replay job violated simulation-only persistence contract")
    print(json.dumps(summary, default=str, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
