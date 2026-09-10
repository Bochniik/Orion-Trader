from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from app.services.intraday_probability_backtest_v3 import HORIZONS, _summary, walk_forward_v3_frame
from app.services.intraday_probability_challenger_v4 import walk_forward_challenger_v4_frame
from app.services.intraday_probability_calibration_v3_1 import _quality_from_metrics
from evals.audit_intraday_calibration_v3_1 import (
    DEFAULT_CALIBRATION_FRACTION,
    MIN_CALIBRATION_RECORDS,
    MIN_EVALUATION_RECORDS,
    _heldout_calibrated_records,
    _validate_records,
)
from evals.intraday_challenger_tournament import compare_reports

DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ")
MIN_SYMBOLS_PER_HORIZON = 3

SEMANTICS = (
    "Offline multi-symbol walk-forward tournament of regular-hours challenger v4 against raw v3 "
    "and leakage-safe held-out v3.1. Every symbol is evaluated independently on exact paired OOS "
    "timestamps; aggregation happens only after per-symbol tournament metrics exist. No runtime "
    "model, threshold, reliability profile, risk policy or trading path is modified."
)


def normalize_symbols(symbols: Iterable[str]) -> List[str]:
    output: List[str] = []
    seen = set()
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        output.append(symbol)
    if not output:
        raise ValueError("At least one symbol is required")
    return output


def build_v3_1_holdout_report(
    v3_report: Mapping[str, Any],
    *,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
) -> Dict[str, Any]:
    if not 0.5 <= calibration_fraction <= 0.8:
        raise ValueError("calibration_fraction must be between 0.50 and 0.80")

    source = v3_report.get("prediction_records") or {}
    if not isinstance(source, Mapping):
        raise ValueError("v3 report must contain prediction_records")

    records: Dict[str, List[Dict[str, Any]]] = {h: [] for h in HORIZONS}
    horizon_meta: Dict[str, Any] = {}
    for horizon in HORIZONS:
        clean = _validate_records(source.get(horizon) or [])
        split = int(len(clean) * calibration_fraction)
        if split < MIN_CALIBRATION_RECORDS or len(clean) - split < MIN_EVALUATION_RECORDS:
            horizon_meta[horizon] = {
                "available": False,
                "record_count": len(clean),
                "reason": "insufficient_calibration_or_evaluation_records",
            }
            continue

        calibration = clean[:split]
        evaluation = clean[split:]
        reliability = _quality_from_metrics(_summary(calibration), horizon)
        reliability_score = float(reliability["reliability_score"])
        records[horizon] = _heldout_calibrated_records(horizon, evaluation, reliability_score)
        horizon_meta[horizon] = {
            "available": True,
            "record_count": len(clean),
            "calibration_count": len(calibration),
            "evaluation_count": len(evaluation),
            "calibration_end_timestamp": calibration[-1]["timestamp"],
            "evaluation_start_timestamp": evaluation[0]["timestamp"],
            "reliability_score": reliability_score,
        }

    return {
        "contract": "orion-intraday-v3-1-heldout-records-v1",
        "symbol": str(v3_report.get("symbol") or "").upper(),
        "prediction_records": records,
        "horizons": horizon_meta,
        "calibration_fraction": calibration_fraction,
        "leakage_safe": True,
        "runtime_modified": False,
    }


def evaluate_symbol_reports(
    v3_report: Mapping[str, Any],
    v4_report: Mapping[str, Any],
    *,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
) -> Dict[str, Any]:
    symbol = str(v3_report.get("symbol") or v4_report.get("symbol") or "").upper()
    v3_1_report = build_v3_1_holdout_report(v3_report, calibration_fraction=calibration_fraction)
    versus_v3 = compare_reports(
        v3_report,
        v4_report,
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
    )
    versus_v3_1 = compare_reports(
        v3_1_report,
        v4_report,
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
    )
    return {
        "symbol": symbol,
        "versus_v3": versus_v3,
        "versus_v3_1": versus_v3_1,
        "v3_1_holdout": v3_1_report["horizons"],
    }


def _aggregate_baseline(
    symbol_results: Sequence[Mapping[str, Any]],
    baseline_key: str,
    *,
    min_symbols_per_horizon: int,
) -> Dict[str, Any]:
    by_horizon: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for result in symbol_results:
        tournament = result.get(baseline_key) or {}
        horizons = tournament.get("horizons") or {}
        if not isinstance(horizons, Mapping):
            continue
        for horizon in HORIZONS:
            row = horizons.get(horizon)
            if isinstance(row, Mapping) and int(row.get("paired_observations") or 0) > 0:
                by_horizon[horizon].append(row)

    summary: Dict[str, Any] = {}
    supported = 0
    for horizon in HORIZONS:
        rows = by_horizon[horizon]
        total_pairs = sum(int(row.get("paired_observations") or 0) for row in rows)
        eligible = sum(row.get("verdict") == "research_eligible" for row in rows)

        def weighted(key: str) -> float | None:
            if total_pairs <= 0:
                return None
            numerator = 0.0
            weight = 0
            for row in rows:
                value = row.get(key)
                count = int(row.get("paired_observations") or 0)
                if value is None or count <= 0:
                    continue
                numerator += float(value) * count
                weight += count
            return round(numerator / weight, 6) if weight else None

        brier = weighted("brier_improvement")
        logloss = weighted("log_loss_improvement")
        coverage_ok = len(rows) >= min_symbols_per_horizon
        majority_stable = eligible > len(rows) / 2 if rows else False
        proper_scores_positive = brier is not None and logloss is not None and brier > 0 and logloss > 0
        horizon_supported = bool(coverage_ok and majority_stable and proper_scores_positive)
        supported += int(horizon_supported)
        summary[horizon] = {
            "evaluable_symbols": len(rows),
            "minimum_symbols_required": min_symbols_per_horizon,
            "paired_observations": total_pairs,
            "research_eligible_symbols": eligible,
            "weighted_brier_improvement": brier,
            "weighted_log_loss_improvement": logloss,
            "coverage_ok": coverage_ok,
            "majority_session_stable": majority_stable,
            "proper_scores_positive": proper_scores_positive,
            "challenger_supported": horizon_supported,
        }

    return {
        "supported_horizons": supported,
        "required_horizons": len(HORIZONS),
        "research_conclusion": "challenger_supported" if supported == len(HORIZONS) else "challenger_not_demonstrated",
        "horizons": summary,
    }


def aggregate_symbol_tournaments(
    symbol_results: Sequence[Mapping[str, Any]],
    *,
    min_symbols_per_horizon: int = MIN_SYMBOLS_PER_HORIZON,
) -> Dict[str, Any]:
    if min_symbols_per_horizon < 1:
        raise ValueError("min_symbols_per_horizon must be >= 1")
    versus_v3 = _aggregate_baseline(symbol_results, "versus_v3", min_symbols_per_horizon=min_symbols_per_horizon)
    versus_v3_1 = _aggregate_baseline(symbol_results, "versus_v3_1", min_symbols_per_horizon=min_symbols_per_horizon)
    supported = (
        versus_v3["research_conclusion"] == "challenger_supported"
        and versus_v3_1["research_conclusion"] == "challenger_supported"
    )
    return {
        "contract": "orion-intraday-v4-multisymbol-tournament-v1",
        "semantics": SEMANTICS,
        "runtime_modified": False,
        "symbol_count": len(symbol_results),
        "min_symbols_per_horizon": min_symbols_per_horizon,
        "versus_v3": versus_v3,
        "versus_v3_1": versus_v3_1,
        "research_conclusion": "v4_research_eligible" if supported else "v4_not_demonstrated",
    }


def benchmark_symbols(
    symbols: Sequence[str],
    *,
    period: str = "60d",
    interval: str = "5m",
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
    min_symbols_per_horizon: int = MIN_SYMBOLS_PER_HORIZON,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
) -> Dict[str, Any]:
    import yfinance as yf

    normalized = normalize_symbols(symbols)
    spy = yf.download("SPY", period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    symbol_results: List[Dict[str, Any]] = []
    failures: Dict[str, str] = {}

    for symbol in normalized:
        try:
            stock = spy.copy() if symbol == "SPY" else yf.download(
                symbol,
                period=period,
                interval=interval,
                auto_adjust=False,
                prepost=False,
                progress=False,
                threads=False,
            )
            v3 = walk_forward_v3_frame(stock, spy, symbol=symbol, include_records=True)
            v4 = walk_forward_challenger_v4_frame(stock, spy, symbol=symbol, include_records=True)
            if not v3.get("available") or not v4.get("available"):
                raise ValueError("insufficient walk-forward history")
            symbol_results.append(
                evaluate_symbol_reports(
                    v3,
                    v4,
                    calibration_fraction=calibration_fraction,
                    min_observations=min_observations,
                    min_sessions=min_sessions,
                    bootstrap_samples=bootstrap_samples,
                )
            )
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"

    result = aggregate_symbol_tournaments(symbol_results, min_symbols_per_horizon=min_symbols_per_horizon)
    result.update({
        "requested_symbols": normalized,
        "failed_symbols": failures,
        "period": period,
        "interval": interval,
        "calibration_fraction": calibration_fraction,
        "symbols": symbol_results,
    })
    if failures:
        result["research_conclusion"] = "v4_not_demonstrated"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-symbol leakage-safe tournament of Orion regular-hours challenger v4.")
    parser.add_argument("symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--calibration-fraction", type=float, default=DEFAULT_CALIBRATION_FRACTION)
    parser.add_argument("--min-symbols-per-horizon", type=int, default=MIN_SYMBOLS_PER_HORIZON)
    parser.add_argument("--min-observations", type=int, default=80)
    parser.add_argument("--min-sessions", type=int, default=8)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--output")
    args = parser.parse_args()

    result = benchmark_symbols(
        args.symbols,
        period=args.period,
        interval=args.interval,
        calibration_fraction=args.calibration_fraction,
        min_symbols_per_horizon=args.min_symbols_per_horizon,
        min_observations=args.min_observations,
        min_sessions=args.min_sessions,
        bootstrap_samples=args.bootstrap_samples,
    )
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
