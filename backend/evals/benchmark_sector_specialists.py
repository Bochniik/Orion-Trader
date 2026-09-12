from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from app.services.intraday_probability_backtest_v3 import HORIZONS, walk_forward_v3_frame
from evals.benchmark_intraday_challenger_v4 import build_v3_1_holdout_report
from evals.intraday_challenger_tournament import evaluate_paired_horizon
from evals.specialist_engine_tournament import evaluate_specialists, generate_walk_forward_predictions

CONTRACT = "orion-sector-specialist-historical-screen-v1"
DEFAULT_UNIVERSE = Path("backend/evals/specialist_universe_v1.json")
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMD", "AMZN", "TSLA", "META", "GOOGL")

SEMANTICS = (
    "Historical screening only. V3 point-in-time walk-forward probabilities are converted to the existing "
    "chronological V3.1 held-out calibration records, then the frozen specialist hierarchy is fit using "
    "completed prior sessions only. Horizons remain separate. This screen may reject a specialist design, "
    "but cannot authorize promotion because the historical data are not an untouched decisive holdout."
)


def load_taxonomy(path: Path = DEFAULT_UNIVERSE) -> dict[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract") != "orion-specialist-universe-v1":
        raise ValueError("unsupported specialist universe contract")
    symbols = payload.get("symbols") or {}
    result: dict[str, dict[str, str]] = {}
    for symbol, meta in symbols.items():
        if meta.get("asset_type") == "equity":
            result[str(symbol).upper()] = {"sector": str(meta["sector"]), "asset_type": "equity"}
    return result


def build_horizon_records(
    symbol_reports: Mapping[str, Mapping[str, Any]],
    taxonomy: Mapping[str, Mapping[str, str]],
    *,
    calibration_fraction: float = 0.60,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    by_horizon: dict[str, list[dict[str, Any]]] = {h: [] for h in HORIZONS}
    failures: dict[str, str] = {}
    for raw_symbol, report in symbol_reports.items():
        symbol = str(raw_symbol).upper()
        meta = taxonomy.get(symbol)
        if not meta:
            failures[symbol] = "missing_frozen_taxonomy"
            continue
        try:
            heldout = build_v3_1_holdout_report(report, calibration_fraction=calibration_fraction)
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"
            continue
        for horizon in HORIZONS:
            for row in (heldout.get("prediction_records") or {}).get(horizon) or []:
                by_horizon[horizon].append(
                    {
                        "timestamp": row["timestamp"],
                        "symbol": symbol,
                        "sector": meta["sector"],
                        "p_up": row["p_up"],
                        "actual_up": row["actual_up"],
                    }
                )
    for rows in by_horizon.values():
        rows.sort(key=lambda row: (row["timestamp"], row["symbol"]))
    return by_horizon, failures


def _screen_group(
    generated: Mapping[str, Any],
    *,
    group_field: str,
    group_value: str,
    min_observations: int,
    min_sessions: int,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    records = generated["prediction_records"]
    parent = [row for row in records["global"] if str(row.get(group_field)) == group_value]
    child_all = [row for row in records["sector"] if str(row.get(group_field)) == group_value]
    child = [row for row in child_all if row.get("layer_active") is True]
    result = evaluate_paired_horizon(
        parent,
        child,
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
    return {
        "candidate_rows_total": len(child_all),
        "candidate_rows_active": len(child),
        "candidate_rows_fallback": len(child_all) - len(child),
        **result,
    }


def screen_records(
    records_by_horizon: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
) -> dict[str, Any]:
    horizons: Dict[str, Any] = {}
    for h_index, horizon in enumerate(HORIZONS):
        rows = list(records_by_horizon.get(horizon) or [])
        generated = generate_walk_forward_predictions(rows)
        sectors = sorted({str(row["sector"]) for row in rows})
        sector_results = {
            sector: _screen_group(
                generated,
                group_field="sector",
                group_value=sector,
                min_observations=min_observations,
                min_sessions=min_sessions,
                bootstrap_samples=bootstrap_samples,
                seed=20260912 + 100 * h_index + index,
            )
            for index, sector in enumerate(sectors)
        }
        horizons[horizon] = {
            "input_observations": len(rows),
            "input_sessions": len({str(row["timestamp"])[:10] for row in rows}),
            "generation_coverage": generated["coverage"],
            "overall_hierarchy": evaluate_specialists(
                generated,
                min_observations=min_observations,
                min_sessions=min_sessions,
                bootstrap_samples=bootstrap_samples,
            ),
            "sectors": sector_results,
        }
    return {
        "contract": CONTRACT,
        "semantics": SEMANTICS,
        "research_only": True,
        "screening_only": True,
        "decisive_holdout": False,
        "promotion_authorized": False,
        "horizon_partitioned": True,
        "horizons": horizons,
    }


def run_real_data_screen(
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    *,
    period: str = "60d",
    interval: str = "5m",
    calibration_fraction: float = 0.60,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
    taxonomy_path: Path = DEFAULT_UNIVERSE,
) -> dict[str, Any]:
    import yfinance as yf

    taxonomy = load_taxonomy(taxonomy_path)
    normalized = [str(symbol).upper() for symbol in symbols if str(symbol).upper() in taxonomy]
    spy = yf.download("SPY", period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    reports: dict[str, Mapping[str, Any]] = {}
    failures: dict[str, str] = {}
    for symbol in normalized:
        try:
            stock = yf.download(symbol, period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
            report = walk_forward_v3_frame(stock, spy, symbol=symbol, include_records=True)
            if not report.get("available"):
                raise ValueError("insufficient walk-forward history")
            reports[symbol] = report
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"

    records, conversion_failures = build_horizon_records(reports, taxonomy, calibration_fraction=calibration_fraction)
    failures.update(conversion_failures)
    result = screen_records(
        records,
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
    )
    result.update(
        {
            "requested_symbols": normalized,
            "successful_symbols": sorted(reports),
            "failed_symbols": failures,
            "period": period,
            "interval": interval,
            "calibration_fraction": calibration_fraction,
            "taxonomy_contract": "orion-specialist-universe-v1",
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Historical screening benchmark for Orion sector specialists.")
    parser.add_argument("symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--calibration-fraction", type=float, default=0.60)
    parser.add_argument("--min-observations", type=int, default=80)
    parser.add_argument("--min-sessions", type=int, default=8)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_real_data_screen(
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
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "failed_symbols": result["failed_symbols"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
