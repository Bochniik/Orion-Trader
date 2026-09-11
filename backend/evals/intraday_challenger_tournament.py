from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

HORIZONS = ("30m", "1h", "3h", "5h")
MIN_PAIRED_OBSERVATIONS = 80
MIN_DISTINCT_SESSIONS = 8
BOOTSTRAP_SAMPLES = 2000
DEFAULT_SEED = 20260910

SEMANTICS = (
    "Offline paired challenger tournament. Incumbent and challenger are scored only on the "
    "same symbol/timestamped out-of-sample observations. Session-block bootstrap resamples whole "
    "trading days, preserving intraday dependence. A challenger is research-eligible only "
    "when coverage is sufficient and proper-score improvement is positive and stable."
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
    """Normalize records by (symbol, timestamp), preserving legacy symbol-less reports."""
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


def pair_records(
    incumbent_records: Iterable[Mapping[str, Any]],
    challenger_records: Iterable[Mapping[str, Any]],
) -> List[PairedObservation]:
    incumbent = _normalize_records(incumbent_records)
    challenger = _normalize_records(challenger_records)
    paired: List[PairedObservation] = []
    for symbol, timestamp in sorted(set(incumbent) & set(challenger), key=lambda key: (key[1], key[0])):
        incumbent_actual, incumbent_p = incumbent[(symbol, timestamp)]
        challenger_actual, challenger_p = challenger[(symbol, timestamp)]
        if incumbent_actual != challenger_actual:
            label = f"{symbol}@{timestamp}" if symbol else timestamp
            raise ValueError(f"Outcome mismatch at {label}")
        paired.append(
            PairedObservation(
                timestamp=timestamp,
                session=_session_key(timestamp) or "",
                actual_up=incumbent_actual,
                incumbent_p=incumbent_p,
                challenger_p=challenger_p,
                symbol=symbol,
            )
        )
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
        if not mask.any():
            continue
        error += float(mask.sum()) / total * abs(float(np.mean(y[mask])) - float(np.mean(p[mask])))
    return error


def _metrics(rows: Sequence[PairedObservation], field: str) -> Dict[str, float]:
    y = np.asarray([row.actual_up for row in rows], dtype=float)
    p = np.asarray([getattr(row, field) for row in rows], dtype=float)
    return {
        "brier_score": round(_brier(y, p), 6),
        "log_loss": round(_log_loss(y, p), 6),
        "directional_accuracy": round(_directional_accuracy(y, p), 6),
        "ece_10bin": round(_ece(y, p), 6),
    }


def _session_deltas(rows: Sequence[PairedObservation]) -> Dict[str, Tuple[float, float]]:
    grouped: Dict[str, List[PairedObservation]] = defaultdict(list)
    for row in rows:
        grouped[row.session].append(row)
    result: Dict[str, Tuple[float, float]] = {}
    for session, session_rows in grouped.items():
        y = np.asarray([row.actual_up for row in session_rows], dtype=float)
        incumbent = np.asarray([row.incumbent_p for row in session_rows], dtype=float)
        challenger = np.asarray([row.challenger_p for row in session_rows], dtype=float)
        result[session] = (
            _brier(y, incumbent) - _brier(y, challenger),
            _log_loss(y, incumbent) - _log_loss(y, challenger),
        )
    return result


def _bootstrap_session_ci(
    rows: Sequence[PairedObservation],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = DEFAULT_SEED,
) -> Dict[str, Any]:
    deltas = _session_deltas(rows)
    sessions = sorted(deltas)
    if not sessions:
        return {"available": False, "reason": "no_sessions"}
    brier = np.asarray([deltas[s][0] for s in sessions], dtype=float)
    logloss = np.asarray([deltas[s][1] for s in sessions], dtype=float)
    rng = np.random.default_rng(seed)
    boot_brier = np.empty(samples, dtype=float)
    boot_logloss = np.empty(samples, dtype=float)
    for i in range(samples):
        idx = rng.integers(0, len(sessions), size=len(sessions))
        boot_brier[i] = float(np.mean(brier[idx]))
        boot_logloss[i] = float(np.mean(logloss[idx]))
    return {
        "available": True,
        "method": "paired_session_block_bootstrap",
        "samples": samples,
        "seed": seed,
        "brier_improvement_ci95": [round(float(np.quantile(boot_brier, 0.025)), 6), round(float(np.quantile(boot_brier, 0.975)), 6)],
        "log_loss_improvement_ci95": [round(float(np.quantile(boot_logloss, 0.025)), 6), round(float(np.quantile(boot_logloss, 0.975)), 6)],
        "probability_brier_improvement_positive": round(float(np.mean(boot_brier > 0)), 6),
        "probability_log_loss_improvement_positive": round(float(np.mean(boot_logloss > 0)), 6),
    }


def evaluate_paired_horizon(
    incumbent_records: Iterable[Mapping[str, Any]],
    challenger_records: Iterable[Mapping[str, Any]],
    *,
    min_observations: int = MIN_PAIRED_OBSERVATIONS,
    min_sessions: int = MIN_DISTINCT_SESSIONS,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    seed: int = DEFAULT_SEED,
) -> Dict[str, Any]:
    paired = pair_records(incumbent_records, challenger_records)
    sessions = sorted({row.session for row in paired})
    incumbent = _metrics(paired, "incumbent_p") if paired else None
    challenger = _metrics(paired, "challenger_p") if paired else None
    coverage_ok = len(paired) >= min_observations and len(sessions) >= min_sessions
    bootstrap = _bootstrap_session_ci(paired, samples=bootstrap_samples, seed=seed) if paired else {"available": False, "reason": "no_paired_records"}

    if incumbent and challenger:
        brier_improvement = round(incumbent["brier_score"] - challenger["brier_score"], 6)
        log_loss_improvement = round(incumbent["log_loss"] - challenger["log_loss"], 6)
        accuracy_delta = round(challenger["directional_accuracy"] - incumbent["directional_accuracy"], 6)
        ece_improvement = round(incumbent["ece_10bin"] - challenger["ece_10bin"], 6)
    else:
        brier_improvement = log_loss_improvement = accuracy_delta = ece_improvement = None

    stable = bool(
        coverage_ok
        and bootstrap.get("available")
        and bootstrap["brier_improvement_ci95"][0] > 0
        and bootstrap["log_loss_improvement_ci95"][0] > 0
    )
    point_improves = bool(
        brier_improvement is not None
        and log_loss_improvement is not None
        and brier_improvement > 0
        and log_loss_improvement > 0
    )
    verdict = "research_eligible" if stable and point_improves else "not_demonstrated"

    return {
        "paired_observations": len(paired),
        "distinct_sessions": len(sessions),
        "minimum_observations": min_observations,
        "minimum_sessions": min_sessions,
        "coverage_ok": coverage_ok,
        "incumbent": incumbent,
        "challenger": challenger,
        "brier_improvement": brier_improvement,
        "log_loss_improvement": log_loss_improvement,
        "directional_accuracy_delta": accuracy_delta,
        "ece_improvement": ece_improvement,
        "bootstrap": bootstrap,
        "verdict": verdict,
    }


def compare_reports(
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    horizons: Sequence[str] = HORIZONS,
    min_observations: int = MIN_PAIRED_OBSERVATIONS,
    min_sessions: int = MIN_DISTINCT_SESSIONS,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    seed: int = DEFAULT_SEED,
) -> Dict[str, Any]:
    incumbent_records = incumbent.get("prediction_records") or {}
    challenger_records = challenger.get("prediction_records") or {}
    if not isinstance(incumbent_records, Mapping) or not isinstance(challenger_records, Mapping):
        raise ValueError("Both reports must contain prediction_records mappings")

    results: Dict[str, Any] = {}
    eligible = 0
    for offset, horizon in enumerate(horizons):
        result = evaluate_paired_horizon(
            incumbent_records.get(horizon) or [],
            challenger_records.get(horizon) or [],
            min_observations=min_observations,
            min_sessions=min_sessions,
            bootstrap_samples=bootstrap_samples,
            seed=seed + offset,
        )
        results[horizon] = result
        eligible += int(result["verdict"] == "research_eligible")

    all_eligible = eligible == len(horizons)
    return {
        "contract": "orion-intraday-challenger-tournament-v1",
        "semantics": SEMANTICS,
        "paired_only": True,
        "runtime_modified": False,
        "horizons_required": list(horizons),
        "eligible_horizons": eligible,
        "research_conclusion": "challenger_research_eligible" if all_eligible else "challenger_not_demonstrated",
        "horizons": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Leakage-safe paired tournament for Orion intraday challenger reports.")
    parser.add_argument("incumbent_report")
    parser.add_argument("challenger_report")
    parser.add_argument("--output")
    parser.add_argument("--min-observations", type=int, default=MIN_PAIRED_OBSERVATIONS)
    parser.add_argument("--min-sessions", type=int, default=MIN_DISTINCT_SESSIONS)
    parser.add_argument("--bootstrap-samples", type=int, default=BOOTSTRAP_SAMPLES)
    args = parser.parse_args()

    with open(args.incumbent_report, "r", encoding="utf-8") as handle:
        incumbent = json.load(handle)
    with open(args.challenger_report, "r", encoding="utf-8") as handle:
        challenger = json.load(handle)
    result = compare_reports(
        incumbent,
        challenger,
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