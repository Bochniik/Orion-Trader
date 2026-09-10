from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Sequence

import numpy as np

from app.services.intraday_probability_backtest_v3 import HORIZONS
from evals.audit_intraday_calibration_v3_1 import audit_symbol

DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ")
MIN_SYMBOLS_PER_HORIZON = 3

SEMANTICS = (
    "Cross-symbol benchmark of the leakage-safe V3.1 held-out calibration audit. "
    "Each symbol is audited independently with chronological calibration/evaluation splits; "
    "aggregation happens only after per-symbol holdout metrics exist. This benchmark does not "
    "modify runtime profiles or promote a model."
)


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if np.isfinite(result) else None


def normalize_symbols(symbols: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(symbol)
    if not result:
        raise ValueError("At least one symbol is required")
    return result


def _weighted_mean(rows: Sequence[Dict[str, Any]], key: str) -> float | None:
    weighted = 0.0
    total_weight = 0.0
    for row in rows:
        value = _finite_float(row.get(key))
        weight = _finite_float(row.get("evaluation_count"))
        if value is None or weight is None or weight <= 0:
            continue
        weighted += value * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return round(weighted / total_weight, 6)


def aggregate_audits(
    audits: Sequence[Dict[str, Any]],
    *,
    min_symbols_per_horizon: int = MIN_SYMBOLS_PER_HORIZON,
) -> Dict[str, Any]:
    if min_symbols_per_horizon < 1:
        raise ValueError("min_symbols_per_horizon must be >= 1")

    clean_audits = [row for row in audits if isinstance(row, dict)]
    by_horizon: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    symbol_results: Dict[str, Dict[str, Any]] = {}

    for audit in clean_audits:
        symbol = str(audit.get("symbol") or "").upper()
        if symbol:
            symbol_results[symbol] = audit
        horizons = audit.get("horizons") or {}
        if not isinstance(horizons, dict):
            continue
        for horizon in HORIZONS:
            row = horizons.get(horizon)
            if isinstance(row, dict) and row.get("available") is True:
                by_horizon[horizon].append(row)

    horizon_summary: Dict[str, Any] = {}
    supported_horizons = 0
    for horizon in HORIZONS:
        rows = by_horizon[horizon]
        improved = sum(row.get("verdict") == "improves_proper_scores" for row in rows)
        degraded = sum(row.get("verdict") == "degrades_proper_scores" for row in rows)
        mixed = sum(row.get("verdict") == "mixed_proper_scores" for row in rows)
        brier = _weighted_mean(rows, "brier_improvement")
        log_loss = _weighted_mean(rows, "log_loss_improvement")
        coverage_ok = len(rows) >= min_symbols_per_horizon
        proper_scores_positive = brier is not None and log_loss is not None and brier > 0 and log_loss > 0
        majority_improved = improved > len(rows) / 2 if rows else False
        supported = bool(coverage_ok and proper_scores_positive and majority_improved)
        supported_horizons += int(supported)

        horizon_summary[horizon] = {
            "evaluable_symbols": len(rows),
            "minimum_symbols_required": min_symbols_per_horizon,
            "improved_symbols": improved,
            "degraded_symbols": degraded,
            "mixed_symbols": mixed,
            "weighted_brier_improvement": brier,
            "weighted_log_loss_improvement": log_loss,
            "coverage_ok": coverage_ok,
            "majority_improved": majority_improved,
            "proper_scores_positive": proper_scores_positive,
            "heuristic_supported": supported,
        }

    all_horizons_supported = supported_horizons == len(HORIZONS)
    conclusion = (
        "heuristic_supported_across_benchmark"
        if all_horizons_supported
        else "heuristic_not_demonstrated_across_benchmark"
    )

    return {
        "contract": "orion-intraday-v3-1-cross-symbol-benchmark-v1",
        "method": "aggregate_independent_chronological_oos_calibration_holdouts",
        "semantics": SEMANTICS,
        "symbol_count": len(symbol_results),
        "min_symbols_per_horizon": min_symbols_per_horizon,
        "supported_horizons": supported_horizons,
        "required_horizons": len(HORIZONS),
        "research_conclusion": conclusion,
        "runtime_modified": False,
        "horizons": horizon_summary,
        "symbols": symbol_results,
    }


def benchmark_symbols(
    symbols: Sequence[str],
    *,
    period: str = "60d",
    interval: str = "5m",
    calibration_fraction: float = 0.60,
    min_symbols_per_horizon: int = MIN_SYMBOLS_PER_HORIZON,
    audit_fn: Callable[..., Dict[str, Any]] = audit_symbol,
) -> Dict[str, Any]:
    normalized = normalize_symbols(symbols)
    audits: List[Dict[str, Any]] = []
    failures: Dict[str, str] = {}

    for symbol in normalized:
        try:
            audits.append(
                audit_fn(
                    symbol,
                    period=period,
                    interval=interval,
                    calibration_fraction=calibration_fraction,
                )
            )
        except Exception as exc:  # research batch should preserve other symbols' evidence
            failures[symbol] = f"{type(exc).__name__}: {exc}"

    result = aggregate_audits(audits, min_symbols_per_horizon=min_symbols_per_horizon)
    result["requested_symbols"] = normalized
    result["failed_symbols"] = failures
    result["period"] = period
    result["interval"] = interval
    result["calibration_fraction"] = calibration_fraction
    if failures:
        result["research_conclusion"] = "heuristic_not_demonstrated_across_benchmark"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-symbol held-out benchmark of Orion V3.1 calibration.")
    parser.add_argument("symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--calibration-fraction", type=float, default=0.60)
    parser.add_argument("--min-symbols-per-horizon", type=int, default=MIN_SYMBOLS_PER_HORIZON)
    parser.add_argument("--output")
    args = parser.parse_args()

    result = benchmark_symbols(
        args.symbols,
        period=args.period,
        interval=args.interval,
        calibration_fraction=args.calibration_fraction,
        min_symbols_per_horizon=args.min_symbols_per_horizon,
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
