from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

LEDGER_CONTRACT = "orion-cloud-shadow-evidence-ledger-v1"
CONTRACT = "orion-rth-forward-baseline-diagnostics-v1"
EPSILON = 1e-15

SEMANTICS = (
    "Research-only proper-score comparison of the RTH incumbent against neutral 50/50 and a "
    "strictly chronological expanding prior. Outcomes sharing a prediction timestamp are scored "
    "before any of them are admitted to the prior, preventing cross-sectional same-timestamp leakage."
)


def _probability(value: Any) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid probability_up: {value}") from exc
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise ValueError(f"Invalid probability_up: {value}")
    return p


def _actual(value: Any) -> int:
    try:
        y = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid actual_up: {value}") from exc
    if y not in (0, 1):
        raise ValueError(f"Invalid actual_up: {value}")
    return y


def _normalize(ledger: Mapping[str, Any], engine: str) -> list[dict[str, Any]]:
    if ledger.get("contract") != LEDGER_CONTRACT:
        raise ValueError(f"Unsupported evidence ledger contract: {ledger.get('contract')}")
    raw_records = ledger.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("Evidence ledger records must be a list")

    rows: list[dict[str, Any]] = []
    seen: dict[str, tuple[Any, ...]] = {}
    for raw in raw_records:
        if not isinstance(raw, Mapping) or str(raw.get("engine") or "") != engine:
            continue
        symbol = str(raw.get("symbol") or "").upper().strip()
        horizon = str(raw.get("horizon") or "").strip()
        prediction_time = str(raw.get("prediction_time_utc") or "").strip()
        if not symbol or not horizon or not prediction_time:
            raise ValueError("Settled record missing symbol/horizon/prediction_time_utc")
        p = _probability(raw.get("probability_up"))
        y = _actual(raw.get("actual_up"))
        identity = str(raw.get("record_id") or "").strip() or "|".join(
            [engine, symbol, horizon, prediction_time, str(raw.get("target_time_utc") or "")]
        )
        fingerprint = (p, y, str(raw.get("target_time_utc") or ""), str(raw.get("material_sha256") or ""))
        if identity in seen and seen[identity] != fingerprint:
            raise ValueError(f"Conflicting duplicate settled evidence: {identity}")
        if identity in seen:
            continue
        seen[identity] = fingerprint
        rows.append({
            "symbol": symbol,
            "horizon": horizon,
            "prediction_time_utc": prediction_time,
            "session": prediction_time[:10],
            "probability_up": p,
            "actual_up": y,
        })
    return rows


def _brier(probabilities: list[float], outcomes: list[int]) -> float | None:
    if not outcomes:
        return None
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(outcomes)


def _log_loss(probabilities: list[float], outcomes: list[int]) -> float | None:
    if not outcomes:
        return None
    total = 0.0
    for p, y in zip(probabilities, outcomes):
        q = min(max(p, EPSILON), 1.0 - EPSILON)
        total += -(y * math.log(q) + (1 - y) * math.log(1.0 - q))
    return total / len(outcomes)


def _metrics(probabilities: list[float], outcomes: list[int]) -> dict[str, Any]:
    brier = _brier(probabilities, outcomes)
    loss = _log_loss(probabilities, outcomes)
    accuracy = None
    if outcomes:
        accuracy = sum(int((p >= 0.5) == bool(y)) for p, y in zip(probabilities, outcomes)) / len(outcomes)
    return {
        "observations": len(outcomes),
        "brier_score": round(brier, 6) if brier is not None else None,
        "binary_log_loss": round(loss, 6) if loss is not None else None,
        "directional_accuracy": round(accuracy, 6) if accuracy is not None else None,
    }


def _chronological_prior(rows: list[dict[str, Any]]) -> list[float]:
    """Return priors using only outcomes from strictly earlier prediction timestamps."""
    indexed = list(enumerate(rows))
    by_time: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, row in indexed:
        by_time[row["prediction_time_utc"]].append((index, row))

    priors = [0.5] * len(rows)
    positives = 0
    total = 0
    for prediction_time in sorted(by_time):
        group = by_time[prediction_time]
        prior = positives / total if total else 0.5
        for index, _row in group:
            priors[index] = prior
        # Critical: update only after every same-timestamp forecast has been scored.
        positives += sum(int(row["actual_up"]) for _, row in group)
        total += len(group)
    return priors


def _comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["prediction_time_utc"], row["symbol"]))
    model = [float(row["probability_up"]) for row in ordered]
    outcomes = [int(row["actual_up"]) for row in ordered]
    prior = _chronological_prior(ordered)
    neutral = [0.5] * len(ordered)
    model_metrics = _metrics(model, outcomes)
    prior_metrics = _metrics(prior, outcomes)
    neutral_metrics = _metrics(neutral, outcomes)

    def delta(metric: str, baseline: dict[str, Any]) -> float | None:
        a = model_metrics[metric]
        b = baseline[metric]
        return round(float(a) - float(b), 6) if a is not None and b is not None else None

    return {
        "model": model_metrics,
        "chronological_expanding_prior": prior_metrics,
        "neutral_50_50": neutral_metrics,
        "model_minus_prior": {
            "brier_score": delta("brier_score", prior_metrics),
            "binary_log_loss": delta("binary_log_loss", prior_metrics),
        },
        "model_minus_neutral": {
            "brier_score": delta("brier_score", neutral_metrics),
            "binary_log_loss": delta("binary_log_loss", neutral_metrics),
        },
        "beats_prior_on_both_proper_scores": bool(
            model_metrics["brier_score"] is not None
            and model_metrics["brier_score"] < prior_metrics["brier_score"]
            and model_metrics["binary_log_loss"] < prior_metrics["binary_log_loss"]
        ),
        "beats_neutral_on_both_proper_scores": bool(
            model_metrics["brier_score"] is not None
            and model_metrics["brier_score"] < neutral_metrics["brier_score"]
            and model_metrics["binary_log_loss"] < neutral_metrics["binary_log_loss"]
        ),
    }


def build_report(ledger: Mapping[str, Any], *, engine: str = "regular_hours_v3_1") -> dict[str, Any]:
    rows = _normalize(ledger, engine)
    by_horizon: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_horizon[row["horizon"]].append(row)
    horizons = {horizon: _comparison(group) for horizon, group in sorted(by_horizon.items())}
    all_comparison = _comparison(rows)
    return {
        "contract": CONTRACT,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "semantics": SEMANTICS,
        "engine": engine,
        "settled_observations": len(rows),
        "distinct_sessions": len({row["session"] for row in rows}),
        "overall": all_comparison,
        "horizons": horizons,
        "promotion_gate": {
            "eligible": False,
            "reason": "diagnostic_only_requires_new_preregistered_forward_candidate",
            "same_evidence_promotion_forbidden": True,
        },
        "safety": {
            "research_only": True,
            "runtime_modified": False,
            "automatic_promotion_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare settled RTH forecasts with leakage-safe baselines.")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--engine", default="regular_hours_v3_1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(json.loads(args.ledger.read_text(encoding="utf-8")), engine=args.engine)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
