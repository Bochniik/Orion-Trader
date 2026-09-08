from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from train_premarket_predictive import FEATURE_NAMES, TARGETS, matrix


MODEL_VERSION = "premarket_predictive_v3_hierarchical"


def sigmoid(z):
    z = np.clip(z, -50.0, 50.0)
    return 1.0 / (1.0 + np.exp(-z))


def binary_log_loss(p, y):
    p = np.clip(p, 1e-12, 1.0 - 1e-12)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def binary_brier(p, y):
    return float(np.mean((p - y) ** 2))


def balanced_weights(y):
    y = np.asarray(y, dtype=int)
    counts = np.bincount(y, minlength=2).astype(float)
    if np.any(counts <= 0):
        return np.ones(len(y), dtype=float)
    weights = np.array([len(y) / (2.0 * counts[0]), len(y) / (2.0 * counts[1])])
    return weights[y]


def fit_binary_logistic(x, y, *, epochs=1800, learning_rate=0.035, l2=0.002):
    n, p = x.shape
    weights = np.zeros(p, dtype=float)
    bias = 0.0
    sample_weights = balanced_weights(y)
    normalizer = float(np.sum(sample_weights))

    for _ in range(epochs):
        logits = x @ weights + bias
        probs = sigmoid(logits)
        error = (probs - y) * sample_weights
        grad_w = (x.T @ error) / normalizer + l2 * weights
        grad_b = float(np.sum(error) / normalizer)
        weights -= learning_rate * grad_w
        bias -= learning_rate * grad_b

    return weights, float(bias)


def binary_probabilities(x, weights, bias, temperature=1.0):
    return sigmoid((x @ weights + bias) / float(temperature))


def fit_binary_temperature(x, y, weights, bias):
    candidates = np.geomspace(0.45, 3.0, 90)
    losses = [binary_log_loss(binary_probabilities(x, weights, bias, t), y) for t in candidates]
    return float(candidates[int(np.argmin(losses))])


def prepare_frame(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    label = f"label_{target}"
    required = ["ticker", "session_date", "snapshot_at", *FEATURE_NAMES, label]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns for {target}: {', '.join(missing)}")

    work = frame[required].copy()
    work["ticker"] = work["ticker"].astype(str).str.upper().str.strip()
    work["session_date"] = pd.to_datetime(work["session_date"], errors="coerce").dt.date
    work["snapshot_at"] = pd.to_datetime(work["snapshot_at"], utc=True, errors="coerce")
    for feature in FEATURE_NAMES:
        work[feature] = pd.to_numeric(work[feature], errors="coerce")
    work["label"] = work[label].astype(str).str.upper().str.strip()
    work = work[work["label"].isin(["UP", "DOWN", "NO_EDGE"])]
    work = work.dropna(subset=["ticker", "session_date", "snapshot_at"])
    return work.sort_values(["session_date", "snapshot_at", "ticker"]).reset_index(drop=True)


def chronological_date_splits(work: pd.DataFrame):
    dates = sorted(work["session_date"].unique())
    if len(dates) < 40:
        raise ValueError(f"Need at least 40 session dates, found {len(dates)}")
    n = len(dates)
    train_end = max(1, int(n * 0.60))
    validation_end = max(train_end + 1, int(n * 0.75))
    calibration_end = max(validation_end + 1, int(n * 0.875))
    calibration_end = min(calibration_end, n - 1)
    groups = [
        set(dates[:train_end]),
        set(dates[train_end:validation_end]),
        set(dates[validation_end:calibration_end]),
        set(dates[calibration_end:]),
    ]
    splits = tuple(work[work["session_date"].isin(g)].copy() for g in groups)
    if any(s.empty for s in splits):
        raise ValueError("Chronological split produced an empty partition")
    return splits


def evaluate_binary(p, y):
    pred = (p >= 0.5).astype(int)
    return {
        "samples": int(len(y)),
        "accuracy": round(float(np.mean(pred == y)), 6),
        "log_loss": round(binary_log_loss(p, y), 6),
        "brier": round(binary_brier(p, y), 6),
        "positive_rate": round(float(np.mean(y)), 6),
    }


def train_stage(train, calibration, test, *, y_train, y_calibration, y_test, x_train, x_calibration, x_test):
    weights, bias = fit_binary_logistic(x_train, y_train)
    temperature = fit_binary_temperature(x_calibration, y_calibration, weights, bias)
    p_test = binary_probabilities(x_test, weights, bias, temperature)
    return {
        "weights": weights.tolist(),
        "bias": float(bias),
        "temperature": float(temperature),
        "metrics": {
            "test": evaluate_binary(p_test, y_test),
            "calibration_before": evaluate_binary(binary_probabilities(x_calibration, weights, bias, 1.0), y_calibration),
            "calibration_after": evaluate_binary(binary_probabilities(x_calibration, weights, bias, temperature), y_calibration),
        },
    }


def train_target(frame: pd.DataFrame, target: str) -> dict:
    work = prepare_frame(frame, target)
    train, validation, calibration, test = chronological_date_splits(work)

    x_train, impute, mean, scale = matrix(train)
    x_validation, _, _, _ = matrix(validation, impute=impute, mean=mean, scale=scale)
    x_cal, _, _, _ = matrix(calibration, impute=impute, mean=mean, scale=scale)
    x_test, _, _, _ = matrix(test, impute=impute, mean=mean, scale=scale)

    edge_train = (train["label"].to_numpy() != "NO_EDGE").astype(int)
    edge_cal = (calibration["label"].to_numpy() != "NO_EDGE").astype(int)
    edge_test = (test["label"].to_numpy() != "NO_EDGE").astype(int)
    edge_stage = train_stage(
        train,
        calibration,
        test,
        y_train=edge_train,
        y_calibration=edge_cal,
        y_test=edge_test,
        x_train=x_train,
        x_calibration=x_cal,
        x_test=x_test,
    )

    train_dir_mask = train["label"].to_numpy() != "NO_EDGE"
    cal_dir_mask = calibration["label"].to_numpy() != "NO_EDGE"
    test_dir_mask = test["label"].to_numpy() != "NO_EDGE"
    if min(int(train_dir_mask.sum()), int(cal_dir_mask.sum()), int(test_dir_mask.sum())) < 100:
        raise ValueError(f"{target}: not enough directional observations for stage 2")

    direction_train = (train.loc[train_dir_mask, "label"].to_numpy() == "UP").astype(int)
    direction_cal = (calibration.loc[cal_dir_mask, "label"].to_numpy() == "UP").astype(int)
    direction_test = (test.loc[test_dir_mask, "label"].to_numpy() == "UP").astype(int)
    direction_stage = train_stage(
        train.loc[train_dir_mask],
        calibration.loc[cal_dir_mask],
        test.loc[test_dir_mask],
        y_train=direction_train,
        y_calibration=direction_cal,
        y_test=direction_test,
        x_train=x_train[train_dir_mask],
        x_calibration=x_cal[cal_dir_mask],
        x_test=x_test[test_dir_mask],
    )

    p_edge = binary_probabilities(x_test, np.asarray(edge_stage["weights"]), edge_stage["bias"], edge_stage["temperature"])
    p_up_given_edge = binary_probabilities(x_test, np.asarray(direction_stage["weights"]), direction_stage["bias"], direction_stage["temperature"])
    p_up = p_edge * p_up_given_edge
    p_down = p_edge * (1.0 - p_up_given_edge)
    p_no_edge = 1.0 - p_edge
    probs = np.column_stack([p_down, p_no_edge, p_up])
    pred = np.argmax(probs, axis=1)
    label_to_idx = {"DOWN": 0, "NO_EDGE": 1, "UP": 2}
    y_test_three = np.array([label_to_idx[v] for v in test["label"].to_numpy()], dtype=int)
    directional_call = pred != 1
    directional_accuracy = float(np.mean(pred[directional_call] == y_test_three[directional_call])) if directional_call.any() else None

    return {
        "feature_names": list(FEATURE_NAMES),
        "impute": impute.tolist(),
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "edge_stage": edge_stage,
        "direction_stage": direction_stage,
        "combined_test": {
            "samples": int(len(test)),
            "accuracy": round(float(np.mean(pred == y_test_three)), 6),
            "directional_calls": int(directional_call.sum()),
            "directional_coverage": round(float(np.mean(directional_call)), 6),
            "directional_accuracy": round(directional_accuracy, 6) if directional_accuracy is not None else None,
        },
        "distinct_session_dates": int(work["session_date"].nunique()),
        "first_snapshot": str(work["snapshot_at"].iloc[0]),
        "last_snapshot": str(work["snapshot_at"].iloc[-1]),
    }


def main():
    parser = argparse.ArgumentParser(description="Train Orion hierarchical EDGE -> DIRECTION predictive models.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("backend/data/models/premarket_predictive_v3_hierarchical.json"))
    parser.add_argument("--targets", nargs="*", choices=TARGETS, default=list(TARGETS))
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    artifact = {
        "model_version": MODEL_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "metadata": {
            "architecture": "stage1_EDGE_vs_NO_EDGE_then_stage2_UP_vs_DOWN_given_EDGE",
            "class_weighting": "balanced_training_weights_per_binary_stage",
            "calibration": "held_out_temperature_scaling_per_stage",
            "split_policy": "date_safe_chronological_60_train_15_validation_12.5_calibration_12.5_test",
            "training_rows_raw": int(len(frame)),
        },
        "targets": {},
    }

    for target in args.targets:
        print(f"Training hierarchical {target}...", flush=True)
        result = train_target(frame, target)
        artifact["targets"][target] = result
        print(json.dumps({
            "edge_test": result["edge_stage"]["metrics"]["test"],
            "direction_test": result["direction_stage"]["metrics"]["test"],
            "combined_test": result["combined_test"],
        }, indent=2))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"Saved hierarchical model artifact to {args.output}")


if __name__ == "__main__":
    main()
