from __future__ import annotations

import argparse
import json
from pathlib import Path

import evals.benchmark_tsla_specialist_simulated_v1 as shared


CONTRACT = "orion-aapl-simulated-forward-specialist-v1"
TARGET_SYMBOL = "AAPL"
TARGET_SECTOR = "Information Technology"


def run(database: Path) -> dict:
    original_symbol = shared.TARGET_SYMBOL
    original_sector = shared.TARGET_SECTOR
    original_contract = shared.CONTRACT
    try:
        shared.TARGET_SYMBOL = TARGET_SYMBOL
        shared.TARGET_SECTOR = TARGET_SECTOR
        shared.CONTRACT = CONTRACT
        result = shared.run(database)
        result["symbol"] = TARGET_SYMBOL
        result["sector"] = TARGET_SECTOR
        result["contract"] = CONTRACT
        return result
    finally:
        shared.TARGET_SYMBOL = original_symbol
        shared.TARGET_SECTOR = original_sector
        shared.CONTRACT = original_contract


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the frozen AAPL specialist on a SIMULATED_FORWARD SQLite state artifact.")
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(Path(args.database))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
