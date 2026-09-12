from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.intraday_probability_backtest_v3 import HORIZONS, walk_forward_v3_frame
from evals.benchmark_sector_specialists import (
    DEFAULT_SYMBOLS,
    DEFAULT_UNIVERSE,
    build_horizon_records,
    load_taxonomy,
    screen_records,
)

CONTRACT = "orion-sector-specialist-loo-robustness-v1"
DEFAULT_TARGET_SECTOR = "Information Technology"
DEFAULT_FOCUS_HORIZONS = ("3h", "5h")

SEMANTICS = (
    "Historical diagnostic only. Re-run the frozen sector-specialist screen after removing one target-sector "
    "symbol at a time. A sign flip in proper-score improvement marks the observed sector hint as constituent-"
    "sensitive. Consistent positive signs are only a distributed historical hint, never promotion evidence."
)


def _sector_row(report: Mapping[str, Any], horizon: str, sector: str) -> dict[str, Any]:
    try:
        row = report["horizons"][horizon]["sectors"][sector]
    except KeyError as exc:
        raise ValueError(f"missing sector result for {sector} at {horizon}") from exc
    return dict(row)


def _point_positive(row: Mapping[str, Any]) -> bool:
    brier = row.get("brier_improvement")
    logloss = row.get("log_loss_improvement")
    return bool(brier is not None and logloss is not None and float(brier) > 0 and float(logloss) > 0)


def audit_leave_one_out(
    records_by_horizon: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    target_sector: str = DEFAULT_TARGET_SECTOR,
    focus_horizons: Sequence[str] = DEFAULT_FOCUS_HORIZONS,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
) -> dict[str, Any]:
    unknown = [h for h in focus_horizons if h not in HORIZONS]
    if unknown:
        raise ValueError(f"unsupported focus horizons: {', '.join(unknown)}")

    sector_symbols = sorted(
        {
            str(row["symbol"])
            for horizon in focus_horizons
            for row in (records_by_horizon.get(horizon) or [])
            if str(row.get("sector")) == target_sector
        }
    )
    if len(sector_symbols) < 3:
        raise ValueError("leave-one-out audit requires at least three target-sector symbols")

    baseline = screen_records(
        records_by_horizon,
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
    )
    omissions: dict[str, Any] = {}
    for symbol in sector_symbols:
        reduced = {
            horizon: [dict(row) for row in (records_by_horizon.get(horizon) or []) if str(row.get("symbol")) != symbol]
            for horizon in HORIZONS
        }
        screened = screen_records(
            reduced,
            min_observations=min_observations,
            min_sessions=min_sessions,
            bootstrap_samples=bootstrap_samples,
        )
        omissions[symbol] = {
            horizon: _sector_row(screened, horizon, target_sector)
            for horizon in focus_horizons
        }

    horizon_summary: dict[str, Any] = {}
    any_sensitive = False
    for horizon in focus_horizons:
        base = _sector_row(baseline, horizon, target_sector)
        rows = {symbol: omissions[symbol][horizon] for symbol in sector_symbols}
        signs = {symbol: _point_positive(row) for symbol, row in rows.items()}
        positive_count = sum(signs.values())
        baseline_positive = _point_positive(base)
        constituent_sensitive = bool(baseline_positive and positive_count != len(rows))
        any_sensitive = any_sensitive or constituent_sensitive
        horizon_summary[horizon] = {
            "baseline": base,
            "omissions": rows,
            "baseline_point_positive": baseline_positive,
            "positive_omissions": positive_count,
            "omission_count": len(rows),
            "all_omissions_point_positive": positive_count == len(rows),
            "constituent_sensitive": constituent_sensitive,
        }

    if any_sensitive:
        conclusion = "historical_hint_constituent_sensitive"
    elif all(row["baseline_point_positive"] and row["all_omissions_point_positive"] for row in horizon_summary.values()):
        conclusion = "historical_hint_distributed_but_unconfirmed"
    else:
        conclusion = "historical_hint_not_consistent"

    return {
        "contract": CONTRACT,
        "semantics": SEMANTICS,
        "research_only": True,
        "screening_only": True,
        "decisive_holdout": False,
        "promotion_authorized": False,
        "target_sector": target_sector,
        "focus_horizons": list(focus_horizons),
        "sector_symbols": sector_symbols,
        "conclusion": conclusion,
        "horizons": horizon_summary,
    }


def run_real_data_audit(
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
    result = audit_leave_one_out(
        records,
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
    )
    result.update({
        "requested_symbols": normalized,
        "successful_symbols": sorted(reports),
        "failed_symbols": failures,
        "period": period,
        "interval": interval,
        "calibration_fraction": calibration_fraction,
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Leave-one-symbol-out robustness audit for the historical sector specialist hint.")
    parser.add_argument("symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--calibration-fraction", type=float, default=0.60)
    parser.add_argument("--min-observations", type=int, default=80)
    parser.add_argument("--min-sessions", type=int, default=8)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_real_data_audit(
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
    print(json.dumps({"output": str(output), "conclusion": result["conclusion"], "failed_symbols": result["failed_symbols"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
