from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.frozen_symbol_specialist_engine import FrozenSymbolSpecialistEngine
from app.services.intraday_probability_backtest_v3 import HORIZONS, walk_forward_v3_frame
from app.services.symbol_specialist_engines import SpecialistEvidenceGate
from evals.benchmark_intraday_challenger_v4 import build_v3_1_holdout_report
from evals.benchmark_sector_specialists import load_taxonomy

CONTRACT = "orion-nvda-frozen-specialist-v1"
TARGET_SYMBOL = "NVDA"
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMD", "AMZN", "TSLA", "META", "GOOGL")
LOCKBOX_SESSIONS = 10
MIN_DEVELOPMENT_SESSIONS = 15


def _session(timestamp: str) -> str:
    return str(timestamp)[:10]


def build_horizon_records(
    reports: Mapping[str, Mapping[str, Any]],
    taxonomy: Mapping[str, Mapping[str, str]],
    *,
    calibration_fraction: float = 0.60,
) -> dict[str, list[dict[str, Any]]]:
    by_horizon = {h: [] for h in HORIZONS}
    for raw_symbol, report in reports.items():
        symbol = str(raw_symbol).upper()
        sector = str(taxonomy[symbol]["sector"])
        heldout = build_v3_1_holdout_report(report, calibration_fraction=calibration_fraction)
        for horizon in HORIZONS:
            for row in (heldout.get("prediction_records") or {}).get(horizon) or []:
                by_horizon[horizon].append(
                    {
                        "timestamp": row["timestamp"],
                        "symbol": symbol,
                        "sector": sector,
                        "p_up": row["p_up"],
                        "actual_up": int(row["actual_up"]),
                    }
                )
    for rows in by_horizon.values():
        rows.sort(key=lambda row: (row["timestamp"], row["symbol"]))
    return by_horizon


def _ece(probabilities: Sequence[float], labels: Sequence[int], bins: int = 10) -> float:
    if not probabilities:
        return float("nan")
    total = len(probabilities)
    result = 0.0
    for index in range(bins):
        lo = index / bins
        hi = (index + 1) / bins
        members = [i for i, p in enumerate(probabilities) if lo <= p < hi or (index == bins - 1 and p == 1.0)]
        if not members:
            continue
        confidence = sum(probabilities[i] for i in members) / len(members)
        observed = sum(labels[i] for i in members) / len(members)
        result += (len(members) / total) * abs(confidence - observed)
    return result


def _metrics(probabilities: Sequence[float], labels: Sequence[int]) -> dict[str, float | int]:
    count = len(labels)
    if count == 0:
        return {"samples": 0, "directional_accuracy": float("nan"), "brier": float("nan"), "ece": float("nan")}
    accuracy = sum((p >= 0.5) == bool(y) for p, y in zip(probabilities, labels)) / count
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / count
    return {"samples": count, "directional_accuracy": accuracy, "brier": brier, "ece": _ece(probabilities, labels)}


def evaluate_horizon(records: Sequence[Mapping[str, Any]], *, horizon: str) -> dict[str, Any]:
    target_sector = "Information Technology"
    sessions = sorted({_session(str(row["timestamp"])) for row in records if str(row.get("symbol")).upper() == TARGET_SYMBOL})
    required = MIN_DEVELOPMENT_SESSIONS + LOCKBOX_SESSIONS
    if len(sessions) < required:
        return {
            "horizon": horizon,
            "verdict": "AWAITING_MORE_EVIDENCE",
            "reason": f"need {required} NVDA sessions, found {len(sessions)}",
            "nvda_sessions": len(sessions),
        }
    lockbox_sessions = sessions[-LOCKBOX_SESSIONS:]
    development_sessions = set(sessions[:-LOCKBOX_SESSIONS])
    development = [row for row in records if _session(str(row["timestamp"])) in development_sessions]
    lockbox = [
        row for row in records
        if str(row.get("symbol")).upper() == TARGET_SYMBOL and _session(str(row["timestamp"])) in lockbox_sessions
    ]
    model = FrozenSymbolSpecialistEngine.fit(
        development,
        symbol=TARGET_SYMBOL,
        sector=target_sector,
        horizon=horizon,
    )
    incumbent: list[float] = []
    specialist: list[float] = []
    labels: list[int] = []
    by_session: dict[str, dict[str, list[float] | list[int]]] = {}
    for row in lockbox:
        prediction = model.predict(float(row["p_up"]))
        incumbent.append(prediction["incumbent_probability_up"])
        specialist.append(prediction["specialist_probability_up"])
        labels.append(int(row["actual_up"]))
        bucket = by_session.setdefault(_session(str(row["timestamp"])), {"incumbent": [], "specialist": [], "labels": []})
        bucket["incumbent"].append(prediction["incumbent_probability_up"])
        bucket["specialist"].append(prediction["specialist_probability_up"])
        bucket["labels"].append(int(row["actual_up"]))

    incumbent_metrics = _metrics(incumbent, labels)
    specialist_metrics = _metrics(specialist, labels)
    accuracy_improvement = float(specialist_metrics["directional_accuracy"]) - float(incumbent_metrics["directional_accuracy"])
    brier_improvement = float(incumbent_metrics["brier"]) - float(specialist_metrics["brier"])
    ece_improvement = float(incumbent_metrics["ece"]) - float(specialist_metrics["ece"])
    session_brier_wins = 0
    for values in by_session.values():
        parent = _metrics(values["incumbent"], values["labels"])
        child = _metrics(values["specialist"], values["labels"])
        if float(child["brier"]) < float(parent["brier"]):
            session_brier_wins += 1

    gate = SpecialistEvidenceGate()
    checks = {
        "enough_oos_samples": len(lockbox) >= gate.min_oos_samples,
        "enough_oos_sessions": len(lockbox_sessions) >= gate.min_oos_sessions,
        "directional_accuracy_improved": accuracy_improvement >= gate.min_directional_accuracy_improvement,
        "brier_improved": brier_improvement >= gate.min_brier_improvement,
        "coverage_ok": 1.0 >= gate.min_coverage,
        "calibration_non_degraded": ece_improvement >= 0.0,
        "session_stability": session_brier_wins >= math.ceil(0.6 * len(lockbox_sessions)),
    }
    verdict = "RESEARCH_VALIDATED" if all(checks.values()) else "REJECTED"
    if not checks["enough_oos_samples"] or not checks["enough_oos_sessions"]:
        verdict = "AWAITING_MORE_EVIDENCE"
    return {
        "horizon": horizon,
        "symbol": TARGET_SYMBOL,
        "engine": model.registration(),
        "development_sessions": len(development_sessions),
        "lockbox_sessions": lockbox_sessions,
        "lockbox_samples": len(lockbox),
        "incumbent": incumbent_metrics,
        "specialist": specialist_metrics,
        "directional_accuracy_improvement": accuracy_improvement,
        "brier_improvement": brier_improvement,
        "ece_improvement": ece_improvement,
        "session_brier_wins": session_brier_wins,
        "session_brier_win_rate": session_brier_wins / len(lockbox_sessions),
        "coverage": 1.0,
        "checks": checks,
        "verdict": verdict,
        "research_only": True,
        "automatic_live_promotion": False,
    }


def run_real_data_benchmark(
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    *,
    period: str = "60d",
    interval: str = "5m",
    calibration_fraction: float = 0.60,
) -> dict[str, Any]:
    import yfinance as yf

    taxonomy = load_taxonomy()
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
    if TARGET_SYMBOL not in reports:
        return {"contract": CONTRACT, "symbol": TARGET_SYMBOL, "failed_symbols": failures, "verdict": "AWAITING_MORE_EVIDENCE", "reason": "NVDA data unavailable", "research_only": True}
    records = build_horizon_records(reports, taxonomy, calibration_fraction=calibration_fraction)
    horizons = {horizon: evaluate_horizon(records[horizon], horizon=horizon) for horizon in HORIZONS}
    validated = [h for h, result in horizons.items() if result.get("verdict") == "RESEARCH_VALIDATED"]
    overall = "RESEARCH_VALIDATED" if validated else "REJECTED"
    if all(result.get("verdict") == "AWAITING_MORE_EVIDENCE" for result in horizons.values()):
        overall = "AWAITING_MORE_EVIDENCE"
    return {
        "contract": CONTRACT,
        "symbol": TARGET_SYMBOL,
        "period": period,
        "interval": interval,
        "calibration_fraction": calibration_fraction,
        "requested_symbols": normalized,
        "successful_symbols": sorted(reports),
        "failed_symbols": failures,
        "lockbox_policy": "latest_10_whole_NVDA_sessions_reserved_before_model_fit",
        "same_evidence_approval_forbidden": True,
        "horizons": horizons,
        "validated_horizons": validated,
        "verdict": overall,
        "research_only": True,
        "automatic_live_promotion": False,
        "live_forward_mutated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen NVDA specialist historical lockbox benchmark.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    args = parser.parse_args()
    result = run_real_data_benchmark(period=args.period, interval=args.interval)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "verdict": result["verdict"], "validated_horizons": result.get("validated_horizons", [])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
