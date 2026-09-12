from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_sector_specialist_historical_evidence import _canonical_json_sha256, run_evidence as run_base_evidence

CONTRACT = "orion-sector-specialist-loo-evidence-v1"
CORE_FILES = (
    "backend/evals/audit_sector_specialist_leave_one_out.py",
    "backend/evals/benchmark_sector_specialists.py",
    "backend/evals/specialist_engine_tournament.py",
    "backend/evals/benchmark_intraday_challenger_v4.py",
    "backend/evals/intraday_challenger_tournament.py",
    "backend/app/services/intraday_probability_backtest_v3.py",
    "backend/app/services/intraday_probability_calibration_v3_1.py",
    "backend/evals/specialist_universe_v1.json",
)


def run_evidence(symbols, **kwargs):
    from evals.audit_sector_specialist_leave_one_out import run_real_data_audit

    payload = run_base_evidence(
        symbols,
        source_paths=CORE_FILES,
        benchmark_fn=run_real_data_audit,
        **kwargs,
    )
    evidence = payload["evidence"]
    evidence["contract"] = CONTRACT
    evidence["diagnostic"] = "leave_one_symbol_out_information_technology_3h_5h"
    evidence["evidence_payload_sha256"] = ""
    evidence["evidence_payload_sha256"] = _canonical_json_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run content-addressed leave-one-out robustness evidence for the historical sector specialist hint.")
    parser.add_argument("symbols", nargs="*", default=["AAPL", "MSFT", "NVDA", "AMD", "AMZN", "TSLA", "META", "GOOGL"])
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--calibration-fraction", type=float, default=0.60)
    parser.add_argument("--min-observations", type=int, default=80)
    parser.add_argument("--min-sessions", type=int, default=8)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = run_evidence(
        args.symbols,
        period=args.period,
        interval=args.interval,
        calibration_fraction=args.calibration_fraction,
        min_observations=args.min_observations,
        min_sessions=args.min_sessions,
        bootstrap_samples=args.bootstrap_samples,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "conclusion": payload["benchmark"]["conclusion"],
        "benchmark_result_sha256": payload["evidence"]["benchmark_result_sha256"],
        "evidence_payload_sha256": payload["evidence"]["evidence_payload_sha256"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
