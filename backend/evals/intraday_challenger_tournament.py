from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

from backend.evals.adaptive_forward_evidence import assess_forward_evidence_readiness

HORIZONS = ("30m", "1h", "3h", "5h")
MIN_PAIRED_OBSERVATIONS = 80
MIN_DISTINCT_SESSIONS = 8
BOOTSTRAP_SAMPLES = 2000
DEFAULT_SEED = 20260910

SEMANTICS = (
    "Offline paired challenger tournament. Incumbent and challenger are scored only on the "
    "same symbol/timestamped out-of-sample observations. Session-block bootstrap resamples whole "
    "trading days, preserving intraday dependence. Adaptive challengers must first pass their "
    "immutable preregistered forward-evidence readiness contract."
)


@dataclass(frozen=True)
class PairedObservation:
    timestamp: str
    session: str
    actual_up: int
    incumbent_p: float
    challenger_p: float
    symbol: str = ""


def _finite_probability_pct(value: Any) -> float | None:
    try:
        p = float(value) / 100.0
    except (TypeError, ValueError, OverflowError):
        return None
    if not np.isfinite(p) or p < 0.0 or p > 1.0:
        return None
    return float(np.clip(p, 1e-9, 1.0 - 1e-9))


def _session_key(timestamp: str) -> str | None:
    try:
        return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError):
        return None


def _normalize_records(records: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str], Tuple[int, float]]:
    result: Dict[Tuple[str, str], Tuple[int, float]] = {}
    for row in records:
        if not isinstance(row, Mapping):
            continue
        timestamp = str(row.get("timestamp") or "").strip()
        symbol = str(row.get("symbol") or "").upper().strip()
        session = _session_key(timestamp)
        p = _finite_probability_pct(row.get("p_up"))
        try:
            actual = int(row.get("actual_up"))
        except (TypeError, ValueError):
            continue
        if not timestamp or session is None or p is None or actual not in (0, 1):
            continue
        key = (symbol, timestamp)
        candidate = (actual, p)
        if key in result and result[key] != candidate:
            label = f"{symbol}@{timestamp}" if symbol else timestamp
            raise ValueError(f"Conflicting duplicate record at {label}")
        result[key] = candidate
    return result


def pair_records(incumbent_records: Iterable[Mapping[str, Any]], challenger_records: Iterable[Mapping[str, Any]]) -> List[PairedObservation]:
    incumbent = _normalize_records(incumbent_records)
    challenger = _normalize_records(challenger_records)
    paired: List[PairedObservation] = []
    for symbol, timestamp in sorted(set(incumbent) & set(challenger), key=lambda key: (key[1], key[0])):
        incumbent_actual, incumbent_p = incumbent[(symbol, timestamp)]
        challenger_actual, challenger_p = challenger[(symbol, timestamp)]
        if incumbent_actual != challenger_actual:
            raise ValueError(f"Outcome mismatch at {symbol}@{timestamp}")
        paired.append(PairedObservation(timestamp, _session_key(timestamp) or "", incumbent_actual, incumbent_p, challenger_p, symbol))
    return paired


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def _log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-9, 1.0 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def _directional_accuracy(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p >= 0.5).astype(int) == y))


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    total = len(y)
    if total == 0:
        return float("nan")
    error = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for index in range(bins):
        low, high = edges[index], edges[index + 1]
        mask = (p >= low) & (p < high if index < bins - 1 else p <= high)
        if mask.any():
            error += float(mask.sum()) / total * abs(float(np.mean(y[mask])) - float(np.mean(p[mask])))
    return error


def _metrics(rows: Sequence[PairedObservation], field: str) -> Dict[str, float]:
    y = np.asarray([row.actual_up for row in rows], dtype=float)
    p = np.asarray([getattr(row, field) for row in rows], dtype=float)
    return {"brier_score": round(_brier(y, p), 6), "log_loss": round(_log_loss(y, p), 6), "directional_accuracy": round(_directional_accuracy(y, p), 6), "ece_10bin": round(_ece(y, p), 6)}


def _bootstrap_session_ci(rows: Sequence[PairedObservation], *, samples: int = BOOTSTRAP_SAMPLES, seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    grouped: Dict[str, List[PairedObservation]] = defaultdict(list)
    for row in rows:
        grouped[row.session].append(row)
    if not grouped:
        return {"available": False, "reason": "no_sessions"}
    sessions = sorted(grouped)
    brier, logloss = [], []
    for session in sessions:
        rs = grouped[session]
        y = np.asarray([r.actual_up for r in rs], dtype=float)
        inc = np.asarray([r.incumbent_p for r in rs], dtype=float)
        chal = np.asarray([r.challenger_p for r in rs], dtype=float)
        brier.append(_brier(y, inc) - _brier(y, chal))
        logloss.append(_log_loss(y, inc) - _log_loss(y, chal))
    brier, logloss = np.asarray(brier), np.asarray(logloss)
    rng = np.random.default_rng(seed)
    boot_brier, boot_logloss = np.empty(samples), np.empty(samples)
    for i in range(samples):
        idx = rng.integers(0, len(sessions), size=len(sessions))
        boot_brier[i], boot_logloss[i] = float(np.mean(brier[idx])), float(np.mean(logloss[idx]))
    return {"available": True, "method": "paired_session_block_bootstrap", "samples": samples, "seed": seed, "brier_improvement_ci95": [round(float(np.quantile(boot_brier, .025)), 6), round(float(np.quantile(boot_brier, .975)), 6)], "log_loss_improvement_ci95": [round(float(np.quantile(boot_logloss, .025)), 6), round(float(np.quantile(boot_logloss, .975)), 6)]}


def evaluate_paired_horizon(incumbent_records: Iterable[Mapping[str, Any]], challenger_records: Iterable[Mapping[str, Any]], *, min_observations: int = MIN_PAIRED_OBSERVATIONS, min_sessions: int = MIN_DISTINCT_SESSIONS, bootstrap_samples: int = BOOTSTRAP_SAMPLES, seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    paired = pair_records(incumbent_records, challenger_records)
    sessions = sorted({row.session for row in paired})
    incumbent = _metrics(paired, "incumbent_p") if paired else None
    challenger = _metrics(paired, "challenger_p") if paired else None
    coverage_ok = len(paired) >= min_observations and len(sessions) >= min_sessions
    bootstrap = _bootstrap_session_ci(paired, samples=bootstrap_samples, seed=seed) if paired else {"available": False, "reason": "no_paired_records"}
    brier_improvement = round(incumbent["brier_score"] - challenger["brier_score"], 6) if incumbent and challenger else None
    log_loss_improvement = round(incumbent["log_loss"] - challenger["log_loss"], 6) if incumbent and challenger else None
    stable = bool(coverage_ok and bootstrap.get("available") and bootstrap["brier_improvement_ci95"][0] > 0 and bootstrap["log_loss_improvement_ci95"][0] > 0)
    verdict = "research_eligible" if stable and brier_improvement > 0 and log_loss_improvement > 0 else "not_demonstrated"
    return {"paired_observations": len(paired), "distinct_sessions": len(sessions), "minimum_observations": min_observations, "minimum_sessions": min_sessions, "coverage_ok": coverage_ok, "incumbent": incumbent, "challenger": challenger, "brier_improvement": brier_improvement, "log_loss_improvement": log_loss_improvement, "bootstrap": bootstrap, "verdict": verdict}


def _flatten_challenger_evidence(challenger: Mapping[str, Any], horizons: Sequence[str]) -> list[Mapping[str, Any]]:
    records = challenger.get("prediction_records") or {}
    flattened: list[Mapping[str, Any]] = []
    for horizon in horizons:
        for row in records.get(horizon) or []:
            item = dict(row)
            item.setdefault("horizon", horizon)
            item.setdefault("session_date", _session_key(str(item.get("timestamp") or "")))
            flattened.append(item)
    return flattened


def compare_adaptive_reports(registration: Mapping[str, Any], incumbent: Mapping[str, Any], challenger: Mapping[str, Any], *, bootstrap_samples: int = BOOTSTRAP_SAMPLES, seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """Fail closed before scoring an adaptive challenger on forward evidence."""
    horizons = tuple(registration.get("candidate", {}).get("horizons") or ())
    if not horizons:
        raise ValueError("registered candidate must define horizons")
    readiness = assess_forward_evidence_readiness(registration, _flatten_challenger_evidence(challenger, horizons))
    if not readiness["tournament_ready"]:
        raise ValueError("adaptive challenger forward evidence is not tournament-ready")
    result = compare_reports(incumbent, challenger, horizons=horizons, bootstrap_samples=bootstrap_samples, seed=seed)
    result["forward_evidence_readiness"] = readiness
    result["adaptive_registration_required"] = True
    return result


def compare_reports(incumbent: Mapping[str, Any], challenger: Mapping[str, Any], *, horizons: Sequence[str] = HORIZONS, min_observations: int = MIN_PAIRED_OBSERVATIONS, min_sessions: int = MIN_DISTINCT_SESSIONS, bootstrap_samples: int = BOOTSTRAP_SAMPLES, seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    incumbent_records, challenger_records = incumbent.get("prediction_records") or {}, challenger.get("prediction_records") or {}
    if not isinstance(incumbent_records, Mapping) or not isinstance(challenger_records, Mapping):
        raise ValueError("Both reports must contain prediction_records mappings")
    results: Dict[str, Any] = {}
    eligible = 0
    for offset, horizon in enumerate(horizons):
        result = evaluate_paired_horizon(incumbent_records.get(horizon) or [], challenger_records.get(horizon) or [], min_observations=min_observations, min_sessions=min_sessions, bootstrap_samples=bootstrap_samples, seed=seed + offset)
        results[horizon] = result
        eligible += int(result["verdict"] == "research_eligible")
    return {"contract": "orion-intraday-challenger-tournament-v1", "semantics": SEMANTICS, "paired_only": True, "runtime_modified": False, "horizons_required": list(horizons), "eligible_horizons": eligible, "research_conclusion": "challenger_research_eligible" if eligible == len(horizons) else "challenger_not_demonstrated", "horizons": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Leakage-safe paired tournament for Orion intraday challenger reports.")
    parser.add_argument("incumbent_report")
    parser.add_argument("challenger_report")
    parser.add_argument("--registration", help="Immutable adaptive challenger registration; required for adaptive scoring")
    parser.add_argument("--output")
    parser.add_argument("--min-observations", type=int, default=MIN_PAIRED_OBSERVATIONS)
    parser.add_argument("--min-sessions", type=int, default=MIN_DISTINCT_SESSIONS)
    parser.add_argument("--bootstrap-samples", type=int, default=BOOTSTRAP_SAMPLES)
    args = parser.parse_args()
    with open(args.incumbent_report, "r", encoding="utf-8") as handle:
        incumbent = json.load(handle)
    with open(args.challenger_report, "r", encoding="utf-8") as handle:
        challenger = json.load(handle)
    if args.registration:
        with open(args.registration, "r", encoding="utf-8") as handle:
            registration = json.load(handle)
        result = compare_adaptive_reports(registration, incumbent, challenger, bootstrap_samples=args.bootstrap_samples)
    else:
        result = compare_reports(incumbent, challenger, min_observations=args.min_observations, min_sessions=args.min_sessions, bootstrap_samples=args.bootstrap_samples)
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
