from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Sequence

from app.services.intraday_probability_backtest_v3 import walk_forward_v3_frame
from app.services.intraday_probability_long_horizon_challenger_v5 import (
    DESIGN_ID,
    LONG_HORIZONS,
    walk_forward_long_horizon_challenger_v5_frame,
)
from evals.benchmark_intraday_challenger_v4 import (
    DEFAULT_SYMBOLS,
    MIN_SYMBOLS_PER_HORIZON,
    build_v3_1_holdout_report,
    normalize_symbols,
)
from evals.long_horizon_challenger_gate import evaluate_long_horizon_candidate

SEMANTICS = (
    "Historical screening only for the frozen long-horizon v5 candidate against raw v3 and "
    "leakage-safe held-out v3.1. Comparisons are paired on identical 3h/5h OOS timestamps. "
    "A pass may justify forward shadow collection but can never confer forward research "
    "eligibility or runtime promotion."
)


def evaluate_symbol_reports(
    v3_report: Mapping[str, Any],
    v5_report: Mapping[str, Any],
    *,
    calibration_fraction: float = 0.60,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
) -> Dict[str, Any]:
    design_id = str(v5_report.get("design_id") or "")
    if design_id != DESIGN_ID:
        raise ValueError(f"Expected frozen candidate {DESIGN_ID}, got {design_id or 'missing design_id'}")

    symbol = str(v3_report.get("symbol") or v5_report.get("symbol") or "").upper()
    v3_1_report = build_v3_1_holdout_report(v3_report, calibration_fraction=calibration_fraction)
    versus_v3 = evaluate_long_horizon_candidate(
        v3_report,
        v5_report,
        evidence_mode="historical_screen",
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
    )
    versus_v3_1 = evaluate_long_horizon_candidate(
        v3_1_report,
        v5_report,
        evidence_mode="historical_screen",
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
    )
    return {
        "symbol": symbol,
        "candidate_design_id": design_id,
        "versus_v3": versus_v3,
        "versus_v3_1": versus_v3_1,
        "v3_1_holdout": {h: v3_1_report["horizons"].get(h) for h in LONG_HORIZONS},
    }


def _aggregate_baseline(
    symbol_results: Sequence[Mapping[str, Any]],
    baseline_key: str,
    *,
    min_symbols_per_horizon: int,
) -> Dict[str, Any]:
    by_horizon: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for result in symbol_results:
        gate = result.get(baseline_key) or {}
        tournament = gate.get("paired_tournament") or {}
        horizons = tournament.get("horizons") or {}
        if not isinstance(horizons, Mapping):
            continue
        for horizon in LONG_HORIZONS:
            row = horizons.get(horizon)
            if isinstance(row, Mapping) and int(row.get("paired_observations") or 0) > 0:
                by_horizon[horizon].append(row)

    summary: Dict[str, Any] = {}
    supported = 0
    for horizon in LONG_HORIZONS:
        rows = by_horizon[horizon]
        total_pairs = sum(int(row.get("paired_observations") or 0) for row in rows)
        stable_symbols = sum(row.get("verdict") == "research_eligible" for row in rows)

        def weighted(key: str) -> float | None:
            numerator = 0.0
            weight = 0
            for row in rows:
                count = int(row.get("paired_observations") or 0)
                value = row.get(key)
                if count <= 0 or value is None:
                    continue
                numerator += float(value) * count
                weight += count
            return round(numerator / weight, 6) if weight else None

        brier = weighted("brier_improvement")
        logloss = weighted("log_loss_improvement")
        coverage_ok = len(rows) >= min_symbols_per_horizon
        majority_stable = stable_symbols > len(rows) / 2 if rows else False
        proper_scores_positive = brier is not None and logloss is not None and brier > 0 and logloss > 0
        horizon_supported = bool(coverage_ok and majority_stable and proper_scores_positive)
        supported += int(horizon_supported)
        summary[horizon] = {
            "evaluable_symbols": len(rows),
            "minimum_symbols_required": min_symbols_per_horizon,
            "paired_observations": total_pairs,
            "stable_symbols": stable_symbols,
            "weighted_brier_improvement": brier,
            "weighted_log_loss_improvement": logloss,
            "coverage_ok": coverage_ok,
            "majority_session_stable": majority_stable,
            "proper_scores_positive": proper_scores_positive,
            "historical_screen_supported": horizon_supported,
        }

    return {
        "supported_horizons": supported,
        "required_horizons": len(LONG_HORIZONS),
        "historical_screen_conclusion": (
            "historical_screen_supported" if supported == len(LONG_HORIZONS) else "historical_screen_not_demonstrated"
        ),
        "horizons": summary,
    }


def aggregate_symbol_screens(
    symbol_results: Sequence[Mapping[str, Any]],
    *,
    min_symbols_per_horizon: int = MIN_SYMBOLS_PER_HORIZON,
) -> Dict[str, Any]:
    if min_symbols_per_horizon < 1:
        raise ValueError("min_symbols_per_horizon must be >= 1")
    versus_v3 = _aggregate_baseline(symbol_results, "versus_v3", min_symbols_per_horizon=min_symbols_per_horizon)
    versus_v3_1 = _aggregate_baseline(symbol_results, "versus_v3_1", min_symbols_per_horizon=min_symbols_per_horizon)
    survived = (
        versus_v3["historical_screen_conclusion"] == "historical_screen_supported"
        and versus_v3_1["historical_screen_conclusion"] == "historical_screen_supported"
    )
    return {
        "contract": "orion-long-horizon-v5-historical-screen-v1",
        "semantics": SEMANTICS,
        "candidate_design_id": DESIGN_ID,
        "research_only": True,
        "historical_screening_only": True,
        "forward_research_eligible": False,
        "runtime_modified": False,
        "promotion_allowed": False,
        "symbol_count": len(symbol_results),
        "min_symbols_per_horizon": min_symbols_per_horizon,
        "versus_v3": versus_v3,
        "versus_v3_1": versus_v3_1,
        "research_conclusion": "v5_survives_historical_screen" if survived else "v5_reject_unchanged",
    }


def benchmark_symbols(
    symbols: Sequence[str],
    *,
    period: str = "60d",
    interval: str = "5m",
    calibration_fraction: float = 0.60,
    min_symbols_per_horizon: int = MIN_SYMBOLS_PER_HORIZON,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
) -> Dict[str, Any]:
    import yfinance as yf

    normalized = normalize_symbols(symbols)
    spy = yf.download("SPY", period=period, interval=interval, auto_adjust=False, prepost=False, progress=False, threads=False)
    if spy is None or spy.empty:
        result = aggregate_symbol_screens([], min_symbols_per_horizon=min_symbols_per_horizon)
        result.update({"requested_symbols": normalized, "failed_symbols": {"SPY": "empty benchmark data"}})
        result["research_conclusion"] = "v5_reject_unchanged"
        return result

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
            if stock is None or stock.empty:
                raise ValueError("empty symbol data")
            v3 = walk_forward_v3_frame(stock, spy, symbol=symbol, include_records=True)
            v5 = walk_forward_long_horizon_challenger_v5_frame(stock, spy, symbol=symbol, include_records=True)
            if not v3.get("available") or not v5.get("available"):
                raise ValueError("insufficient walk-forward history")
            symbol_results.append(
                evaluate_symbol_reports(
                    v3,
                    v5,
                    calibration_fraction=calibration_fraction,
                    min_observations=min_observations,
                    min_sessions=min_sessions,
                    bootstrap_samples=bootstrap_samples,
                )
            )
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"

    result = aggregate_symbol_screens(symbol_results, min_symbols_per_horizon=min_symbols_per_horizon)
    result.update({
        "requested_symbols": normalized,
        "failed_symbols": failures,
        "period": period,
        "interval": interval,
        "calibration_fraction": calibration_fraction,
        "symbols": symbol_results,
    })
    if failures:
        result["research_conclusion"] = "v5_reject_unchanged"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Historical-only paired screen of frozen Orion long-horizon v5.")
    parser.add_argument("symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--calibration-fraction", type=float, default=0.60)
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
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
