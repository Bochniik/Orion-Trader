from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

EPS = 1e-12


def _binary_metrics(probabilities: list[float], outcomes: list[int]) -> dict[str, Any]:
    if not outcomes:
        return {"sample_count": 0, "brier_score": None, "log_loss": None, "directional_accuracy": None}
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(outcomes)
    loss = 0.0
    correct = 0
    for p, y in zip(probabilities, outcomes):
        clipped = min(max(float(p), EPS), 1.0 - EPS)
        loss += -(y * math.log(clipped) + (1 - y) * math.log(1.0 - clipped))
        correct += int((p >= 0.5) == bool(y))
    return {
        "sample_count": len(outcomes),
        "brier_score": round(brier, 8),
        "log_loss": round(loss / len(outcomes), 8),
        "directional_accuracy": round(correct / len(outcomes), 6),
    }


def benchmark(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in records if r.get("engine") == "regular_hours_v3_1" and r.get("actual_up") in (0, 1)]
    rows.sort(key=lambda r: (str(r.get("prediction_time_utc", "")), str(r.get("symbol", "")), str(r.get("horizon", ""))))
    by_horizon: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_horizon[str(row.get("horizon"))].append(row)

    output: dict[str, Any] = {}
    for horizon, group in sorted(by_horizon.items()):
        outcomes = [int(r["actual_up"]) for r in group]
        model_p = [float(r["probability_up"]) for r in group]
        neutral_p = [0.5] * len(group)
        always_up_p = [1.0 - EPS] * len(group)

        # Expanding prior is strictly chronological. For each forecast it uses
        # only outcomes whose target timestamp is strictly earlier than the
        # current prediction timestamp. Same-time/future labels never leak in.
        prior_p: list[float] = []
        for row in group:
            prediction_time = str(row.get("prediction_time_utc", ""))
            history = [
                int(previous["actual_up"])
                for previous in group
                if str(previous.get("target_time_utc", "")) < prediction_time
            ]
            prior_p.append(sum(history) / len(history) if history else 0.5)

        model = _binary_metrics(model_p, outcomes)
        neutral = _binary_metrics(neutral_p, outcomes)
        always_up = _binary_metrics(always_up_p, outcomes)
        chronological_prior = _binary_metrics(prior_p, outcomes)
        output[horizon] = {
            "model": model,
            "baselines": {
                "neutral_50_50": neutral,
                "always_up": always_up,
                "chronological_expanding_prior": chronological_prior,
            },
            "brier_improvement_vs_50_50": round(neutral["brier_score"] - model["brier_score"], 8),
            "brier_improvement_vs_chronological_prior": round(chronological_prior["brier_score"] - model["brier_score"], 8),
        }
    return {
        "contract": "orion-cloud-shadow-baseline-benchmark-v1",
        "leakage_safe": True,
        "engine": "regular_hours_v3_1",
        "policy": {
            "neutral_50_50": "fixed p(up)=0.5; no labels used",
            "always_up": "fixed UP forecast; diagnostic reference only",
            "chronological_expanding_prior": "p(up) uses only rows whose target_time_utc is strictly before the forecast prediction_time_utc",
            "evaluation_set_majority": "intentionally omitted because it uses future holdout labels",
        },
        "by_horizon": output,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark settled regular-hours shadow forecasts against leakage-safe baselines.")
    parser.add_argument("evaluation", type=Path)
    parser.add_argument("--output", type=Path, default=Path("backend/data/cloud_shadow/evaluation/baseline-benchmark.json"))
    args = parser.parse_args()
    payload = json.loads(args.evaluation.read_text(encoding="utf-8"))
    report = benchmark(list(payload.get("records") or []))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["by_horizon"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
