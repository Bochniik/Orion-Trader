from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from app.services.intraday_probability_long_horizon_challenger_v5 import LONG_HORIZONS

SUPPORTED_CONTRACT = "orion-long-horizon-v5-historical-screen-v1"


def audit_screening_protocol(
    payload: Mapping[str, Any],
    *,
    min_observations: int = 80,
    min_symbols_per_horizon: int = 3,
) -> Dict[str, Any]:
    """Audit whether a historical screen could have satisfied its own per-symbol gate.

    This audit intentionally ignores model scores. It only checks protocol geometry:
    whether enough symbols had enough paired V3.1 holdout observations to be capable of
    receiving a stable/research-eligible verdict under the configured tournament rules.
    """
    if min_observations < 1:
        raise ValueError("min_observations must be >= 1")
    if min_symbols_per_horizon < 1:
        raise ValueError("min_symbols_per_horizon must be >= 1")

    benchmark = payload.get("benchmark") if isinstance(payload.get("benchmark"), Mapping) else payload
    if not isinstance(benchmark, Mapping):
        raise ValueError("benchmark payload must be a mapping")
    if benchmark.get("contract") != SUPPORTED_CONTRACT:
        raise ValueError("unsupported benchmark contract")

    symbols = benchmark.get("symbols") or []
    if not isinstance(symbols, list):
        raise ValueError("benchmark symbols must be a list")

    horizons: Dict[str, Any] = {}
    infeasible_horizons: list[str] = []
    for horizon in LONG_HORIZONS:
        counts: list[int] = []
        capable_symbols: list[str] = []
        incapable_symbols: list[str] = []
        for row in symbols:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol") or "").upper()
            v31 = row.get("versus_v3_1") or {}
            tournament = v31.get("paired_tournament") or {}
            horizon_row = (tournament.get("horizons") or {}).get(horizon) or {}
            paired = int(horizon_row.get("paired_observations") or 0)
            counts.append(paired)
            if paired >= min_observations:
                capable_symbols.append(symbol)
            else:
                incapable_symbols.append(symbol)

        enough_capable_symbols = len(capable_symbols) >= min_symbols_per_horizon
        if not enough_capable_symbols:
            infeasible_horizons.append(horizon)
        horizons[horizon] = {
            "required_min_observations_per_symbol": min_observations,
            "required_min_capable_symbols": min_symbols_per_horizon,
            "observed_symbol_count": len(counts),
            "capable_symbol_count": len(capable_symbols),
            "capable_symbols": capable_symbols,
            "incapable_symbols": incapable_symbols,
            "min_paired_observations": min(counts) if counts else 0,
            "max_paired_observations": max(counts) if counts else 0,
            "protocol_feasible": enough_capable_symbols,
        }

    assessable = bool(symbols)
    feasible = bool(assessable and not infeasible_horizons)
    if not assessable:
        decision = "protocol_not_assessable"
        disposition = "do_not_draw_model_conclusion"
    elif feasible:
        decision = "protocol_feasible"
        disposition = "benchmark_model_conclusion_may_be_interpreted"
    else:
        decision = "benchmark_inconclusive_protocol_infeasible"
        disposition = "do_not_promote_or_reject_model_from_this_screen"

    return {
        "contract": "orion-long-horizon-screening-protocol-audit-v1",
        "research_only": True,
        "runtime_modified": False,
        "score_blind_audit": True,
        "source_benchmark_contract": benchmark.get("contract"),
        "source_research_conclusion": benchmark.get("research_conclusion"),
        "assessable": assessable,
        "protocol_feasible": feasible,
        "decision_grade": feasible,
        "decision": decision,
        "model_disposition": disposition,
        "infeasible_horizons": infeasible_horizons,
        "horizons": horizons,
        "recommendations": [
            "Do not lower thresholds or retune V5 on the frozen evaluation window after observing model outcomes.",
            "Pre-register a feasible long-horizon validation geometry before collecting or evaluating the next untouched holdout.",
            "Keep runtime, risk policy, thresholds and broker behavior unchanged until decision-grade evidence exists.",
        ] if not feasible else [
            "Protocol geometry is capable of satisfying the configured per-symbol coverage gate; interpret model scores under the existing frozen rules."
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit feasibility of the Orion long-horizon historical screening protocol.")
    parser.add_argument("input", help="V5 benchmark evidence JSON or benchmark JSON")
    parser.add_argument("--min-observations", type=int, default=80)
    parser.add_argument("--min-symbols-per-horizon", type=int, default=3)
    parser.add_argument("--output")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = audit_screening_protocol(
        payload,
        min_observations=args.min_observations,
        min_symbols_per_horizon=args.min_symbols_per_horizon,
    )
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
