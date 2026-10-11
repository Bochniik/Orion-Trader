from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.frozen_symbol_specialist_engine import FrozenSymbolSpecialistEngine
from app.services.symbol_specialist_engines import SpecialistEvidenceGate

CONTRACT = "orion-tsla-simulated-forward-specialist-v1"
TARGET_SYMBOL = "TSLA"
TARGET_SECTOR = "Consumer Discretionary"
MODEL_VERSION = "long-horizon-v5-20260911-a"
HORIZONS = ("3h", "5h")
LOCKBOX_SESSIONS = 10
MIN_DEVELOPMENT_SESSIONS = 15
SECTOR_MAP = {
    "AAPL": "Information Technology",
    "AMD": "Information Technology",
    "MSFT": "Information Technology",
    "NVDA": "Information Technology",
    "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary",
    "GOOGL": "Communication Services",
    "META": "Communication Services",
}


def _session(timestamp: str) -> str:
    return str(timestamp)[:10]


def _ece(probabilities: Sequence[float], labels: Sequence[int], bins: int = 10) -> float:
    if not probabilities:
        return float("nan")
    total = len(probabilities)
    value = 0.0
    for index in range(bins):
        lo = index / bins
        hi = (index + 1) / bins
        members = [
            i
            for i, probability in enumerate(probabilities)
            if lo <= probability < hi or (index == bins - 1 and probability == 1.0)
        ]
        if not members:
            continue
        mean_probability = sum(probabilities[i] for i in members) / len(members)
        observed = sum(labels[i] for i in members) / len(members)
        value += (len(members) / total) * abs(mean_probability - observed)
    return value


def _metrics(probabilities: Sequence[float], labels: Sequence[int]) -> dict[str, float | int]:
    count = len(labels)
    if count == 0:
        return {
            "samples": 0,
            "directional_accuracy": float("nan"),
            "brier": float("nan"),
            "ece": float("nan"),
        }
    accuracy = sum((p >= 0.5) == bool(y) for p, y in zip(probabilities, labels)) / count
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / count
    return {
        "samples": count,
        "directional_accuracy": accuracy,
        "brier": brier,
        "ece": _ece(probabilities, labels),
    }


def load_records(database: Path, *, horizon: str) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT symbol, prediction_time_utc, probability_up, actual_direction
            FROM simulated_forward_predictions
            WHERE scope = 'SIMULATED_FORWARD'
              AND status = 'settled'
              AND actual_direction IN ('UP', 'DOWN')
              AND model_version = ?
              AND horizon = ?
            ORDER BY prediction_time_utc ASC, id ASC
            """,
            (MODEL_VERSION, horizon),
        ).fetchall()
    finally:
        connection.close()

    records: list[dict[str, Any]] = []
    for symbol, timestamp, probability_up, actual_direction in rows:
        normalized = str(symbol).upper()
        sector = SECTOR_MAP.get(normalized)
        if not sector:
            continue
        records.append(
            {
                "timestamp": str(timestamp),
                "symbol": normalized,
                "sector": sector,
                "p_up": float(probability_up),
                "actual_up": 1 if str(actual_direction).upper() == "UP" else 0,
            }
        )
    return records


def _bootstrap_session_deltas(
    grouped: Mapping[str, Sequence[tuple[float, float, int]]],
    *,
    seed: int,
    iterations: int = 5000,
) -> dict[str, list[float]]:
    sessions = sorted(grouped)
    if not sessions:
        return {"accuracy_delta_95_ci": [float("nan"), float("nan")], "brier_improvement_95_ci": [float("nan"), float("nan")]}
    rng = random.Random(seed)
    accuracy_deltas: list[float] = []
    brier_deltas: list[float] = []
    for _ in range(iterations):
        sampled_sessions = [rng.choice(sessions) for _ in sessions]
        rows = [row for session in sampled_sessions for row in grouped[session]]
        incumbent = [row[0] for row in rows]
        specialist = [row[1] for row in rows]
        labels = [row[2] for row in rows]
        incumbent_metrics = _metrics(incumbent, labels)
        specialist_metrics = _metrics(specialist, labels)
        accuracy_deltas.append(
            float(specialist_metrics["directional_accuracy"]) - float(incumbent_metrics["directional_accuracy"])
        )
        brier_deltas.append(float(incumbent_metrics["brier"]) - float(specialist_metrics["brier"]))
    accuracy_deltas.sort()
    brier_deltas.sort()

    def interval(values: Sequence[float]) -> list[float]:
        lo = values[int(0.025 * (len(values) - 1))]
        hi = values[int(0.975 * (len(values) - 1))]
        return [lo, hi]

    return {
        "accuracy_delta_95_ci": interval(accuracy_deltas),
        "brier_improvement_95_ci": interval(brier_deltas),
    }


def evaluate_horizon(records: Sequence[Mapping[str, Any]], *, horizon: str) -> dict[str, Any]:
    target_sessions = sorted(
        {_session(str(row["timestamp"])) for row in records if str(row.get("symbol")).upper() == TARGET_SYMBOL}
    )
    required_sessions = MIN_DEVELOPMENT_SESSIONS + LOCKBOX_SESSIONS
    if len(target_sessions) < required_sessions:
        return {
            "horizon": horizon,
            "verdict": "AWAITING_MORE_EVIDENCE",
            "reason": f"need at least {required_sessions} TSLA sessions, found {len(target_sessions)}",
            "tsla_sessions": len(target_sessions),
        }

    lockbox_sessions = target_sessions[-LOCKBOX_SESSIONS:]
    development_sessions = set(target_sessions[:-LOCKBOX_SESSIONS])
    lockbox_set = set(lockbox_sessions)
    development = [row for row in records if _session(str(row["timestamp"])) in development_sessions]
    lockbox = [
        row
        for row in records
        if str(row.get("symbol")).upper() == TARGET_SYMBOL and _session(str(row["timestamp"])) in lockbox_set
    ]

    model = FrozenSymbolSpecialistEngine.fit(
        development,
        symbol=TARGET_SYMBOL,
        sector=TARGET_SECTOR,
        horizon=horizon,
    )

    incumbent_probabilities: list[float] = []
    specialist_probabilities: list[float] = []
    labels: list[int] = []
    by_session: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    for row in lockbox:
        prediction = model.predict(float(row["p_up"]))
        incumbent = float(prediction["incumbent_probability_up"])
        specialist = float(prediction["specialist_probability_up"])
        actual = int(row["actual_up"])
        incumbent_probabilities.append(incumbent)
        specialist_probabilities.append(specialist)
        labels.append(actual)
        by_session[_session(str(row["timestamp"]))].append((incumbent, specialist, actual))

    incumbent_metrics = _metrics(incumbent_probabilities, labels)
    specialist_metrics = _metrics(specialist_probabilities, labels)
    accuracy_improvement = float(specialist_metrics["directional_accuracy"]) - float(incumbent_metrics["directional_accuracy"])
    brier_improvement = float(incumbent_metrics["brier"]) - float(specialist_metrics["brier"])
    ece_improvement = float(incumbent_metrics["ece"]) - float(specialist_metrics["ece"])

    session_wins = 0
    for rows in by_session.values():
        incumbent_brier = sum((incumbent - actual) ** 2 for incumbent, _, actual in rows) / len(rows)
        specialist_brier = sum((specialist - actual) ** 2 for _, specialist, actual in rows) / len(rows)
        session_wins += specialist_brier < incumbent_brier

    gate = SpecialistEvidenceGate()
    enough_samples = len(lockbox) >= gate.min_oos_samples
    enough_sessions = len(by_session) >= gate.min_oos_sessions
    accuracy_gate = accuracy_improvement >= gate.min_directional_accuracy_improvement
    brier_gate = brier_improvement >= gate.min_brier_improvement
    calibration_gate = ece_improvement >= 0.0
    session_win_rate = session_wins / len(by_session) if by_session else 0.0
    bootstrap = _bootstrap_session_deltas(by_session, seed=20261011 + (0 if horizon == "3h" else 1))

    if enough_samples and enough_sessions and accuracy_gate and brier_gate and calibration_gate:
        verdict = "RESEARCH_VALIDATED"
    elif accuracy_improvement < 0.0 or brier_improvement < 0.0 or ece_improvement < 0.0:
        verdict = "REJECTED"
    else:
        verdict = "AWAITING_MORE_EVIDENCE"

    return {
        "horizon": horizon,
        "verdict": verdict,
        "model_id": model.model_id,
        "model_registration": model.registration(),
        "development_sessions": len(development_sessions),
        "development_symbol_samples": model.symbol_observations,
        "lockbox_sessions": lockbox_sessions,
        "lockbox_session_count": len(by_session),
        "lockbox_samples": len(lockbox),
        "incumbent": incumbent_metrics,
        "specialist": specialist_metrics,
        "directional_accuracy_improvement": accuracy_improvement,
        "brier_improvement": brier_improvement,
        "ece_improvement": ece_improvement,
        "session_brier_win_rate": session_win_rate,
        "uncertainty": bootstrap,
        "gate": {
            "min_oos_samples": gate.min_oos_samples,
            "min_oos_sessions": gate.min_oos_sessions,
            "min_directional_accuracy_improvement": gate.min_directional_accuracy_improvement,
            "min_brier_improvement": gate.min_brier_improvement,
            "checks": {
                "enough_samples": enough_samples,
                "enough_sessions": enough_sessions,
                "accuracy_improved": accuracy_gate,
                "brier_improved": brier_gate,
                "calibration_non_degraded": calibration_gate,
            },
        },
    }


def run(database: Path) -> dict[str, Any]:
    horizons = {horizon: evaluate_horizon(load_records(database, horizon=horizon), horizon=horizon) for horizon in HORIZONS}
    if any(result["verdict"] == "REJECTED" for result in horizons.values()):
        overall = "REJECTED"
    elif all(result["verdict"] == "RESEARCH_VALIDATED" for result in horizons.values()):
        overall = "RESEARCH_VALIDATED"
    else:
        overall = "AWAITING_MORE_EVIDENCE"
    return {
        "contract": CONTRACT,
        "symbol": TARGET_SYMBOL,
        "sector": TARGET_SECTOR,
        "scope": "SIMULATED_FORWARD",
        "model_version": MODEL_VERSION,
        "research_only": True,
        "runtime_influence_allowed": False,
        "automatic_live_promotion": False,
        "same_evidence_approval_forbidden": True,
        "verdict": overall,
        "horizons": horizons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the frozen TSLA specialist on a SIMULATED_FORWARD SQLite state artifact.")
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(Path(args.database))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
