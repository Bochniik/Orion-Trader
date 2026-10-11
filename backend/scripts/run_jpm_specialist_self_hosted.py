from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.services.accelerated_learning_job import run_accelerated_learning_job
from app.services.market_universe_db import MarketUniverseDatabase
from evals.benchmark_jpm_specialist_simulated_v1 import run as benchmark_jpm

RESEARCH_SYMBOLS = (
    "JPM",
    "BAC",
    "WFC",
    "GS",
    "C",
    "AAPL",
    "NVDA",
    "TSLA",
    "META",
    "AMZN",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the JPM specialist research cycle on a self-hosted runner.")
    parser.add_argument("--root", default="data/self-hosted-jpm")
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    args = parser.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    universe_db = root / "market_universe.db"
    simulated_db = root / "simulated_forward.db"
    checkpoint = root / "replay_checkpoint.json"
    learning_artifact = root / "learning_challenger.json"
    cycle_artifact = root / "accelerated_learning_cycle.json"
    benchmark_artifact = root / "jpm-specialist-v1-evidence.json"
    summary_artifact = root / "jpm-self-hosted-summary.json"

    universe_db.unlink(missing_ok=True)
    checkpoint.unlink(missing_ok=True)
    os.environ["ORION_MARKET_UNIVERSE_DB"] = str(universe_db.resolve())

    market_db = MarketUniverseDatabase()
    market_db.upsert_assets(
        [
            {
                "symbol": symbol,
                "class": "us_equity",
                "tradable": True,
                "status": "active",
            }
            for symbol in RESEARCH_SYMBOLS
        ],
        source="jpm-specialist-self-hosted-v1",
    )

    learning = run_accelerated_learning_job(
        simulated_db=simulated_db,
        checkpoint_path=checkpoint,
        learning_artifact_path=learning_artifact,
        cycle_artifact_path=cycle_artifact,
        top_n=len(RESEARCH_SYMBOLS),
        candidate_limit=len(RESEARCH_SYMBOLS),
        minimum_adv=0.0,
        period=args.period,
        interval=args.interval,
        batch_size=2,
        prepost=False,
        run_id="jpm-specialist-self-hosted-v1",
    )
    if learning.get("scope") != "SIMULATED_FORWARD" or learning.get("live_forward_mutated") is not False:
        raise RuntimeError("self-hosted JPM replay violated SIMULATED_FORWARD safety contract")

    benchmark = benchmark_jpm(simulated_db)
    benchmark_artifact.write_text(
        json.dumps(benchmark, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    summary = {
        "contract": "orion-jpm-self-hosted-cycle-v1",
        "scope": "SIMULATED_FORWARD",
        "symbols": list(RESEARCH_SYMBOLS),
        "replay_prediction_count": (learning.get("replay") or {}).get("prediction_count"),
        "replay_settled_prediction_count": (learning.get("replay") or {}).get("settled_prediction_count"),
        "jpm_verdict": benchmark.get("verdict"),
        "jpm_horizons": benchmark.get("horizons"),
        "automatic_live_promotion": False,
        "live_forward_mutated": False,
    }
    summary_artifact.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
