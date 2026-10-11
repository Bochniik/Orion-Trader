from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals import benchmark_tsla_specialist_simulated_v1 as shared

CONTRACT = "orion-jpm-simulated-forward-specialist-v1"
TARGET_SYMBOL = "JPM"
TARGET_SECTOR = "Financials"

# Reuse the frozen, leakage-safe evaluator introduced for TSLA while changing
# only preregistered symbol/sector identity. The inspected lockbox is never used
# to refit or rescue the specialist.
shared.CONTRACT = CONTRACT
shared.TARGET_SYMBOL = TARGET_SYMBOL
shared.TARGET_SECTOR = TARGET_SECTOR
shared.SECTOR_MAP.update(
    {
        "JPM": "Financials",
        "BAC": "Financials",
        "WFC": "Financials",
        "GS": "Financials",
        "MS": "Financials",
        "C": "Financials",
        "V": "Financials",
        "MA": "Financials",
    }
)


def run(database: Path) -> dict:
    result = shared.run(database)
    result["contract"] = CONTRACT
    result["symbol"] = TARGET_SYMBOL
    result["sector"] = TARGET_SECTOR
    result["research_only"] = True
    result["runtime_influence_allowed"] = False
    result["automatic_live_promotion"] = False
    result["same_evidence_approval_forbidden"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the frozen JPM specialist on SIMULATED_FORWARD evidence."
    )
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
