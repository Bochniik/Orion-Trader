from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from premarket_directional_v4_common import (
    MODEL_VERSION,
    PREMARKET_TARGETS,
    REGIMES,
    V4_FEATURE_NAMES,
    apply_transform,
    chronological_splits,
    fit_transform,
    prepare_v4_frame,
)
from train_premarket_hierarchical import (
    binary_brier,
    binary_log_loss,
    binary_probabilities,
    fit_binary_logistic,
    fit_binary_temperature,
)


def evaluate_binary(p, y):
    pred = (p >= 0.5).astype(int)
    return {
        "samples": int(len(y)),
        "accuracy": round(float(np.mean(pred == y)), 6),
        "log_loss": round(binary_log_loss(p, y), 6),
        "brier": round(binary_brier(p, y), 6),
        "positive_rate": round(float(np.mean(y)), 6),
    }


def fit_stage(x_train, y_train, x_cal, y_cal):
    weights, bias = fit_binary_logistic(x_train, y_train)
    temperature = fit_binary_temperature(x_cal, y_cal, weights, bias)
    return {
        "weights": weights.tolist(),
        "bias": float(bias),
        "temperature": float(temperature),
    }


def stage_probability(stage, x):
    return binary_probabilities(
        x,
        np.asarray(stage["weights"], dtype=float),
        float(stage["bias"]),
        float(stage["temperature"]),
    )


def fit_target(frame: pd.DataFrame, target: str) -> dict:
    work = prepare_v4_frame(frame, target)
    train, validation, calibration, test = chronological_splits(work)

    x_train, impute, mean, scale = fit_transform(train)
    x_cal = apply_transform(calibration, impute, mean, scale)
    x_test = apply_transform(test, impute, mean, scale)

    y_edge_train = (train["label"].to_numpy() != "NO_EDGE").astype(int)
    y_edge_cal = (calibration["label"].to_numpy() != "NO_EDGE").astype(int)
    y_edge_test = (test["label"].to_numpy() != "NO_EDGE").astype(int)
    edge_global = fit_stage(x_train, y_edge_train, x_cal, y_edge_cal)

    train_dir = train["label"].to_numpy() != "NO_EDGE"
    cal_dir = calibration["label"].to_numpy() != "NO_EDGE"
    test_dir = test["label"].to_numpy() != "NO_EDGE"
    if min(int(train_dir.sum()), int(cal_dir.sum()), int(test_dir.sum())) < 100:
        raise ValueError(f"{target}: insufficient directional observations")

    y_dir_train = (train.loc[train_dir, "label"].to_numpy() == "UP").astype(int)
    y_dir_cal = (calibration.loc[cal_dir, "label"].to_numpy() == "UP").astype(int)
    y_dir_test = (test.loc[test_dir, "label"].to_numpy() == "UP").astype(int)
    direction_global = fit_stage(x_train[train_dir], y_dir_train, x_cal[cal_dir], y_dir_cal)

    regimes = {}
    for regime in REGIMES:
        train_mask = train["regime"].to_numpy() == regime
        cal_mask = calibration["regime"].to_numpy() == regime
        train_dir_mask = train_mask & train_dir
        cal_dir_mask = cal_mask & cal_dir
        if int(train_mask.sum()) < 500 or int(cal_mask.sum()) < 100:
            continue
        if int(train_dir_mask.sum()) < 250 or int(cal_dir_mask.sum()) < 50:
            continue
        regimes[regime] = {
            "edge_stage": fit_stage(
                x_train[train_mask],
                y_edge_train[train_mask],
                x_cal[cal_mask],
                y_edge_cal[cal_mask],
            ),
            "direction_stage": fit_stage(
                x_train[train_dir_mask],
                (train.loc[train_dir_mask, "label"].to_numpy() == "UP").astype(int),
                x_cal[cal_dir_mask],
                (calibration.loc[cal_dir_mask, "label"].to_numpy() == "UP").astype(int),
            ),
            "train_samples": int(train_mask.sum()),
            "train_directional_samples": int(train_dir_mask.sum()),
        }

    p_edge_global = stage_probability(edge_global, x_test)
    p_dir_global = stage_probability(direction_global, x_test)
    p_edge = p_edge_global.copy()
    p_dir = p_dir_global.copy()

    test_regimes = test["regime"].to_numpy()
    for regime, payload in regimes.items():
        mask = test_regimes == regime
        if not mask.any():
            continue
        # Shrink regime models toward the global model to reduce variance.
        p_edge_regime = stage_probability(payload["edge_stage"], x_test[mask])
        p_dir_regime = stage_probability(payload["direction_stage"], x_test[mask])
        p_edge[mask] = 0.65 * p_edge_regime + 0.35 * p_edge_global[mask]
        p_dir[mask] = 0.65 * p_dir_regime + 0.35 * p_dir_global[mask]

    direction_conf = np.maximum(p_dir, 1.0 - p_dir)
    pred_direction = np.where(p_dir >= 0.5, "UP", "DOWN")
    truth = test["label"].to_numpy()
    calls = (p_edge >= 0.55) & (direction_conf >= 0.55)
    directional_accuracy = float(np.mean(pred_direction[calls] == truth[calls])) if calls.any() else None

    edge_metrics = evaluate_binary(p_edge, y_edge_test)
    direction_metrics = evaluate_binary(
        p_dir[test_dir],
        y_dir_test,
    )

    return {
        "feature_names": list(V4_FEATURE_NAMES),
        "impute": impute.tolist(),
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "global": {
            "edge_stage": edge_global,
            "direction_stage": direction_global,
        },
        "regimes": regimes,
        "metrics": {
            "edge_test": edge_metrics,
            "direction_test": direction_metrics,
            "default_gate_test": {
                "edge_threshold": 0.55,
                "direction_threshold": 0.55,
                "samples": int(calls.sum()),
                "coverage": round(float(np.mean(calls)), 6),
                "directional_accuracy": round(directional_accuracy, 6) if directional_accuracy is not None else None,
            },
        },
        "distinct_session_dates": int(work["session_date"].nunique()),
        "first_snapshot": str(work["snapshot_at"].iloc[0]),
        "last_snapshot": str(work["snapshot_at"].iloc[-1]),
    }


def main():
    parser = argparse.ArgumentParser(description="Train Orion Premarket Directional Engine v4.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("backend/data/models/premarket_directional_v4.json"))
    parser.add_argument("--targets", nargs="*", choices=PREMARKET_TARGETS, default=list(PREMARKET_TARGETS))
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    artifact = {
        "model_version": MODEL_VERSION,
        "feature_names": list(V4_FEATURE_NAMES),
        "metadata": {
            "architecture": "hierarchical_edge_direction_with_time_regime_shrinkage",
            "regimes": {
                "early": "more_than_165_minutes_to_open",
                "mid": "31_to_165_minutes_to_open",
                "late": "0_to_30_minutes_to_open",
            },
            "regime_blend": {"regime": 0.65, "global": 0.35},
            "calibration": "held_out_temperature_scaling_per_binary_stage",
            "split_policy": "date_safe_chronological_60_train_15_validation_12.5_calibration_12.5_test",
            "training_rows_raw": int(len(frame)),
        },
        "targets": {},
    }

    for target in args.targets:
        print(f"Training v4 {target}...", flush=True)
        result = fit_target(frame, target)
        artifact["targets"][target] = result
        print(json.dumps(result["metrics"], indent=2))
        print(f"  regime models: {', '.join(sorted(result['regimes'])) or 'none'}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"Saved v4 model artifact to {args.output}")


if __name__ == "__main__":
    main()
