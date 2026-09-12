from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.intraday_probability_backtest_v3 import walk_forward_v3_frame
from evals.benchmark_intraday_challenger_v4 import build_v3_1_holdout_report
from evals.intraday_challenger_tournament import evaluate_paired_horizon
from evals.specialist_engine_tournament import generate_walk_forward_predictions

CONTRACT = "orion-industry-specialist-historical-screen-v1"
DEFAULT_PREREG = Path("backend/evals/industry_specialist_prereg_v1.json")


def load_prereg(path: Path = DEFAULT_PREREG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract") != "orion-industry-specialist-prereg-v1":
        raise ValueError("unsupported industry specialist preregistration contract")
    if payload.get("target_horizon") != "3h":
        raise ValueError("v1 preregistration must target only 3h")
    if payload.get("decisive_holdout_assigned") is not False:
        raise ValueError("historical screen cannot use an assigned decisive holdout")
    industry = [str(x).upper() for x in payload.get("industry_symbols") or []]
    controls = [str(x).upper() for x in payload.get("control_symbols") or []]
    if len(industry) < 3 or not controls or set(industry) & set(controls):
        raise ValueError("preregistered industry/control cohorts are invalid")
    return payload


def build_records(
    symbol_reports: Mapping[str, Mapping[str, Any]],
    prereg: Mapping[str, Any],
) -> list[dict[str, Any]]:
    target = str(prereg["target_horizon"])
    fraction = float(prereg["calibration_fraction"])
    industry_symbols = {str(x).upper() for x in prereg["industry_symbols"]}
    rows: list[dict[str, Any]] = []
    for raw_symbol, report in symbol_reports.items():
        symbol = str(raw_symbol).upper()
        heldout = build_v3_1_holdout_report(report, calibration_fraction=fraction)
        label = str(prereg["industry_label"]) if symbol in industry_symbols else "Control"
        for row in (heldout.get("prediction_records") or {}).get(target) or []:
            rows.append(
                {
                    "timestamp": row["timestamp"],
                    "symbol": symbol,
                    "sector": label,
                    "p_up": row["p_up"],
                    "actual_up": row["actual_up"],
                }
            )
    return sorted(rows, key=lambda row: (row["timestamp"], row["symbol"]))


def evaluate_records(records: Sequence[Mapping[str, Any]], prereg: Mapping[str, Any]) -> dict[str, Any]:
    generated = generate_walk_forward_predictions(
        records,
        min_global_obs=int(prereg["minimum_global_observations"]),
        min_global_sessions=int(prereg["minimum_global_sessions"]),
        min_sector_obs=int(prereg["minimum_industry_observations"]),
        min_sector_sessions=int(prereg["minimum_industry_sessions"]),
        min_ticker_obs=10**9,
        min_ticker_sessions=10**9,
        ridge=float(prereg["ridge"]),
    )
    label = str(prereg["industry_label"])
    parent = [row for row in generated["prediction_records"]["global"] if row.get("sector") == label]
    child_all = [row for row in generated["prediction_records"]["sector"] if row.get("sector") == label]
    child = [row for row in child_all if row.get("layer_active") is True]
    paired = evaluate_paired_horizon(
        parent,
        child,
        min_observations=int(prereg["minimum_evaluation_observations"]),
        min_sessions=int(prereg["minimum_evaluation_sessions"]),
        bootstrap_samples=int(prereg["bootstrap_samples"]),
        seed=20260912,
    )
    return {
        "contract": CONTRACT,
        "candidate_id": prereg["candidate_id"],
        "research_only": True,
        "screening_only": True,
        "decisive_holdout": False,
        "promotion_authorized": False,
        "target_horizon": prereg["target_horizon"],
        "comparison": "global_to_semiconductor_specialist",
        "candidate_rows_total": len(child_all),
        "candidate_rows_active": len(child),
        "candidate_rows_fallback": len(child_all) - len(child),
        "generation_coverage": generated["coverage"],
        "result": paired,
    }


def run_real_data_screen(prereg: Mapping[str, Any]) -> dict[str, Any]:
    import yfinance as yf

    symbols = [str(x).upper() for x in prereg["industry_symbols"] + prereg["control_symbols"]]
    period = str(prereg["period"])
    interval = str(prereg["interval"])
    spy = yf.download("SPY", period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    reports: dict[str, Mapping[str, Any]] = {}
    failures: dict[str, str] = {}
    for symbol in symbols:
        try:
            stock = yf.download(symbol, period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
            report = walk_forward_v3_frame(stock, spy, symbol=symbol, include_records=True)
            if not report.get("available"):
                raise ValueError("insufficient walk-forward history")
            reports[symbol] = report
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"
    result = evaluate_records(build_records(reports, prereg), prereg)
    result.update(
        {
            "requested_symbols": symbols,
            "successful_symbols": sorted(reports),
            "failed_symbols": failures,
            "period": period,
            "interval": interval,
            "calibration_fraction": prereg["calibration_fraction"],
            "preregistration": dict(prereg),
        }
    )
    if failures:
        result["result"]["verdict"] = "not_demonstrated"
        result["failure_policy"] = "any_symbol_failure_invalidates_historical_support"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Preregistered historical screen of Orion semiconductor 3h specialist.")
    parser.add_argument("--prereg", type=Path, default=DEFAULT_PREREG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prereg = load_prereg(args.prereg)
    result = run_real_data_screen(prereg)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "failed_symbols": result["failed_symbols"], "verdict": result["result"].get("verdict")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
