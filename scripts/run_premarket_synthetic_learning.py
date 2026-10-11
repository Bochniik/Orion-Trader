from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import numpy as np
import pandas as pd

from app.services.premarket_v5_runtime import predict_premarket_v5_outlook
from simulate_premarket_market import HORIZONS, SCENARIOS, Scenario, generate_scenario

CONTRACT = "orion-premarket-synthetic-learning-v1"
DEFAULT_DEVELOPMENT_SEEDS = (11, 23, 37, 41, 53, 67)
DEFAULT_LOCKBOX_SEEDS = (101, 131, 151)
MIN_LOCKBOX_SAMPLES_PER_HORIZON = 60
MIN_BRIER_IMPROVEMENT = 0.002
RIDGE_L2 = 1e-3
LOGISTIC_L2 = 1e-3


def _sigmoid(value: np.ndarray | float) -> np.ndarray | float:
    clipped = np.clip(value, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _logit(probability: float) -> float:
    p = float(np.clip(probability, 1e-6, 1.0 - 1e-6))
    return float(math.log(p / (1.0 - p)))


def _seed_manifest(seeds: Sequence[int], *, role: str) -> dict:
    canonical = json.dumps({"role": role, "seeds": list(map(int, seeds))}, sort_keys=True).encode("utf-8")
    return {
        "role": role,
        "seeds": list(map(int, seeds)),
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }


def validate_seed_split(development_seeds: Sequence[int], lockbox_seeds: Sequence[int]) -> None:
    development = tuple(map(int, development_seeds))
    lockbox = tuple(map(int, lockbox_seeds))
    if not development or not lockbox:
        raise ValueError("development_and_lockbox_seeds_required")
    if len(set(development)) != len(development) or len(set(lockbox)) != len(lockbox):
        raise ValueError("duplicate_seed_within_split")
    if set(development) & set(lockbox):
        raise ValueError("development_lockbox_seed_overlap")


def _collect_rows_for_scenario(
    scenario: Scenario,
    *,
    seed: int,
    session_date: str,
    previous_close: float,
    evaluation_step_minutes: int,
) -> list[dict]:
    frame, latent = generate_scenario(
        scenario,
        session_date=session_date,
        previous_close=previous_close,
        seed=int(seed),
    )
    rows: list[dict] = []
    evaluation_points = latent.index[60:-30:evaluation_step_minutes]

    for as_of in evaluation_points:
        visible = frame.loc[frame.index <= as_of]
        if len(visible) < 3:
            continue
        observed_as_of = pd.Timestamp(visible.index[-1])
        observed_price = float(visible.iloc[-1]["Close"])
        v5 = predict_premarket_v5_outlook(
            visible,
            previous_close=previous_close,
            feed="sip",
            as_of=as_of,
        )
        if v5.get("available") is not True:
            continue
        for horizon in HORIZONS:
            signal = (v5.get("signals") or {}).get(f"premarket_{horizon}m")
            if not isinstance(signal, dict):
                continue
            target_time = as_of + pd.Timedelta(minutes=horizon)
            if target_time not in latent.index:
                continue
            future_price = float(latent.loc[target_time])
            actual_return_pct = (future_price / observed_price - 1.0) * 100.0
            p_up = signal.get("probability_up")
            predicted_return = signal.get("predicted_return_pct")
            if p_up is None or predicted_return is None:
                continue
            rows.append(
                {
                    "scenario": scenario.name,
                    "seed": int(seed),
                    "as_of": as_of.isoformat(),
                    "observed_as_of": observed_as_of.isoformat(),
                    "observed_age_minutes": float((as_of - observed_as_of) / pd.Timedelta(minutes=1)),
                    "horizon": int(horizon),
                    "incumbent_probability_up": float(p_up),
                    "incumbent_predicted_return_pct": float(predicted_return),
                    "incumbent_gate_passed": signal.get("research_gate_passed") is True,
                    "actual_up": bool(actual_return_pct > 0.0),
                    "actual_return_pct": float(actual_return_pct),
                }
            )
    return rows


def collect_synthetic_dataset(
    *,
    seeds: Sequence[int],
    session_date: str = "2026-10-08",
    previous_close: float = 100.0,
    evaluation_step_minutes: int = 5,
    scenarios: Iterable[Scenario] = SCENARIOS,
) -> list[dict]:
    rows: list[dict] = []
    scenario_tuple = tuple(scenarios)
    for seed in seeds:
        for scenario_index, scenario in enumerate(scenario_tuple):
            rows.extend(
                _collect_rows_for_scenario(
                    scenario,
                    seed=int(seed) + scenario_index * 1009,
                    session_date=session_date,
                    previous_close=previous_close,
                    evaluation_step_minutes=evaluation_step_minutes,
                )
            )
    return rows


def _fit_logistic_calibrator(rows: Sequence[dict]) -> np.ndarray:
    x = np.asarray(
        [
            [
                1.0,
                _logit(float(row["incumbent_probability_up"])),
                float(row["incumbent_predicted_return_pct"]),
            ]
            for row in rows
        ],
        dtype=float,
    )
    y = np.asarray([1.0 if row["actual_up"] else 0.0 for row in rows], dtype=float)
    weights = np.zeros(x.shape[1], dtype=float)
    learning_rate = 0.03
    for _ in range(2500):
        probabilities = np.asarray(_sigmoid(x @ weights), dtype=float)
        gradient = (x.T @ (probabilities - y)) / max(len(y), 1)
        gradient[1:] += LOGISTIC_L2 * weights[1:]
        weights -= learning_rate * gradient
    return weights


def _fit_return_corrector(rows: Sequence[dict]) -> np.ndarray:
    x = np.asarray(
        [[1.0, float(row["incumbent_predicted_return_pct"])] for row in rows],
        dtype=float,
    )
    y = np.asarray([float(row["actual_return_pct"]) for row in rows], dtype=float)
    penalty = np.eye(x.shape[1], dtype=float) * RIDGE_L2
    penalty[0, 0] = 0.0
    return np.linalg.solve(x.T @ x + penalty, x.T @ y)


def train_challenger(rows: Sequence[dict]) -> dict:
    if len(rows) < 20:
        raise ValueError("insufficient_development_samples")
    by_horizon: Dict[str, dict] = {}
    for horizon in HORIZONS:
        horizon_rows = [row for row in rows if int(row["horizon"]) == int(horizon)]
        if len(horizon_rows) < 20:
            raise ValueError(f"insufficient_development_samples_{horizon}m")
        logistic = _fit_logistic_calibrator(horizon_rows)
        return_weights = _fit_return_corrector(horizon_rows)
        by_horizon[str(horizon)] = {
            "sample_count": len(horizon_rows),
            "probability_calibrator": {
                "kind": "synthetic_platt_plus_return",
                "weights": logistic.tolist(),
            },
            "return_corrector": {
                "kind": "synthetic_ridge_on_incumbent_return",
                "weights": return_weights.tolist(),
            },
        }
    return {
        "model_kind": "premarket_v5_synthetic_challenger_overlay",
        "research_only": True,
        "runtime_routing_enabled": False,
        "automatic_promotion_allowed": False,
        "targets": by_horizon,
    }


def _challenger_prediction(row: dict, target: dict) -> tuple[float, float]:
    probability_weights = np.asarray(target["probability_calibrator"]["weights"], dtype=float)
    return_weights = np.asarray(target["return_corrector"]["weights"], dtype=float)
    probability_features = np.asarray(
        [
            1.0,
            _logit(float(row["incumbent_probability_up"])),
            float(row["incumbent_predicted_return_pct"]),
        ],
        dtype=float,
    )
    return_features = np.asarray([1.0, float(row["incumbent_predicted_return_pct"])], dtype=float)
    probability_up = float(_sigmoid(probability_features @ probability_weights))
    predicted_return = float(return_features @ return_weights)
    return probability_up, predicted_return


def _metrics(rows: Sequence[dict], challenger: dict) -> dict:
    if not rows:
        return {"sample_count": 0}
    incumbent_brier: list[float] = []
    challenger_brier: list[float] = []
    incumbent_correct: list[bool] = []
    challenger_correct: list[bool] = []
    incumbent_abs_error: list[float] = []
    challenger_abs_error: list[float] = []
    gated_count = 0
    for row in rows:
        target = challenger["targets"][str(int(row["horizon"]))]
        challenger_p_up, challenger_return = _challenger_prediction(row, target)
        actual_up = bool(row["actual_up"])
        actual_binary = 1.0 if actual_up else 0.0
        incumbent_p = float(row["incumbent_probability_up"])
        incumbent_return = float(row["incumbent_predicted_return_pct"])
        actual_return = float(row["actual_return_pct"])
        incumbent_brier.append((incumbent_p - actual_binary) ** 2)
        challenger_brier.append((challenger_p_up - actual_binary) ** 2)
        incumbent_correct.append((incumbent_p >= 0.5) == actual_up)
        challenger_correct.append((challenger_p_up >= 0.5) == actual_up)
        incumbent_abs_error.append(abs(incumbent_return - actual_return))
        challenger_abs_error.append(abs(challenger_return - actual_return))
        if row.get("incumbent_gate_passed") is True:
            gated_count += 1
    return {
        "sample_count": len(rows),
        "incumbent_brier": float(np.mean(incumbent_brier)),
        "challenger_brier": float(np.mean(challenger_brier)),
        "brier_improvement": float(np.mean(incumbent_brier) - np.mean(challenger_brier)),
        "incumbent_directional_accuracy": float(np.mean(incumbent_correct)),
        "challenger_directional_accuracy": float(np.mean(challenger_correct)),
        "directional_accuracy_delta": float(np.mean(challenger_correct) - np.mean(incumbent_correct)),
        "incumbent_return_mae_pct": float(np.mean(incumbent_abs_error)),
        "challenger_return_mae_pct": float(np.mean(challenger_abs_error)),
        "return_mae_improvement_pct": float(np.mean(incumbent_abs_error) - np.mean(challenger_abs_error)),
        "incumbent_gate_coverage": float(gated_count / len(rows)),
    }


def evaluate_lockbox(rows: Sequence[dict], challenger: dict) -> dict:
    by_horizon: Dict[str, dict] = {}
    passes = []
    for horizon in HORIZONS:
        horizon_rows = [row for row in rows if int(row["horizon"]) == int(horizon)]
        metrics = _metrics(horizon_rows, challenger)
        enough = int(metrics.get("sample_count", 0)) >= MIN_LOCKBOX_SAMPLES_PER_HORIZON
        brier_ok = enough and float(metrics.get("brier_improvement", -999.0)) >= MIN_BRIER_IMPROVEMENT
        accuracy_ok = enough and float(metrics.get("directional_accuracy_delta", -999.0)) >= 0.0
        return_ok = enough and float(metrics.get("return_mae_improvement_pct", -999.0)) >= 0.0
        passed = bool(enough and brier_ok and accuracy_ok and return_ok)
        by_horizon[str(horizon)] = {
            **metrics,
            "minimum_samples_required": MIN_LOCKBOX_SAMPLES_PER_HORIZON,
            "minimum_brier_improvement_required": MIN_BRIER_IMPROVEMENT,
            "passes_preregistered_gate": passed,
        }
        passes.append(passed)
    all_pass = bool(passes and all(passes))
    return {
        "by_horizon": by_horizon,
        "all_horizons_pass": all_pass,
        "verdict": "RESEARCH_VALIDATED_SYNTHETIC" if all_pass else "REJECTED_OR_INSUFFICIENT_SYNTHETIC",
        "production_eligible": False,
        "live_forward_validation_required": True,
    }


def run_learning_loop(
    *,
    development_seeds: Sequence[int] = DEFAULT_DEVELOPMENT_SEEDS,
    lockbox_seeds: Sequence[int] = DEFAULT_LOCKBOX_SEEDS,
    session_date: str = "2026-10-08",
    evaluation_step_minutes: int = 5,
) -> dict:
    validate_seed_split(development_seeds, lockbox_seeds)
    development_rows = collect_synthetic_dataset(
        seeds=development_seeds,
        session_date=session_date,
        evaluation_step_minutes=evaluation_step_minutes,
    )
    challenger = train_challenger(development_rows)
    lockbox_rows = collect_synthetic_dataset(
        seeds=lockbox_seeds,
        session_date=session_date,
        evaluation_step_minutes=evaluation_step_minutes,
    )
    evaluation = evaluate_lockbox(lockbox_rows, challenger)
    return {
        "contract": CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_date": session_date,
        "research_only": True,
        "synthetic_evidence_only": True,
        "runtime_routing_enabled": False,
        "automatic_promotion_allowed": False,
        "live_forward_validation_required": True,
        "development_manifest": _seed_manifest(development_seeds, role="development"),
        "lockbox_manifest": _seed_manifest(lockbox_seeds, role="untouched_lockbox"),
        "development_sample_count": len(development_rows),
        "lockbox_sample_count": len(lockbox_rows),
        "challenger": challenger,
        "lockbox_evaluation": evaluation,
        "safety_note": "Synthetic evidence may train and reject a research challenger, but can never promote or route production Premarket V5 without separate real historical/live-forward validation.",
    }


def _parse_seed_csv(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and lockbox-evaluate a synthetic Premarket V5 research challenger")
    parser.add_argument("--session-date", default="2026-10-08")
    parser.add_argument("--development-seeds", default=",".join(map(str, DEFAULT_DEVELOPMENT_SEEDS)))
    parser.add_argument("--lockbox-seeds", default=",".join(map(str, DEFAULT_LOCKBOX_SEEDS)))
    parser.add_argument("--output", default="backend/data/simulations/premarket_synthetic_learning.json")
    args = parser.parse_args()
    payload = run_learning_loop(
        development_seeds=_parse_seed_csv(args.development_seeds),
        lockbox_seeds=_parse_seed_csv(args.lockbox_seeds),
        session_date=args.session_date,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "contract": payload["contract"],
        "development_sample_count": payload["development_sample_count"],
        "lockbox_sample_count": payload["lockbox_sample_count"],
        "verdict": payload["lockbox_evaluation"]["verdict"],
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
