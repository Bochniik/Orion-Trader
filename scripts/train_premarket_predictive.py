from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.premarket_predictive_engine import (
    CLASSES,
    FEATURE_NAMES,
    MODEL_VERSION,
    TARGETS,
)


def softmax(logits):
    logits = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(logits)
    return exp / np.sum(exp, axis=1, keepdims=True)


def one_hot(y):
    result = np.zeros((len(y), 3), dtype=float)
    result[np.arange(len(y)), y] = 1.0
    return result


def log_loss(probabilities, y):
    chosen = probabilities[np.arange(len(y)), y]
    return float(-np.mean(np.log(np.clip(chosen, 1e-12, 1.0))))


def brier_score(probabilities, y):
    truth = one_hot(y)
    return float(np.mean(np.sum((probabilities - truth) ** 2, axis=1)))


def accuracy(probabilities, y):
    return float(np.mean(np.argmax(probabilities, axis=1) == y))


def fit_softmax(x, y, *, epochs=1800, learning_rate=0.035, l2=0.002):
    n, p = x.shape
    weights = np.zeros((3, p), dtype=float)
    bias = np.zeros(3, dtype=float)
    truth = one_hot(y)

    for _ in range(epochs):
        logits = x @ weights.T + bias
        probabilities = softmax(logits)
        error = probabilities - truth
        grad_w = (error.T @ x) / n + l2 * weights
        grad_b = np.mean(error, axis=0)
        weights -= learning_rate * grad_w
        bias -= learning_rate * grad_b

    return weights, bias


def probabilities(x, weights, bias, temperature=1.0):
    logits = (x @ weights.T + bias) / temperature
    return softmax(logits)


def fit_temperature(x, y, weights, bias):
    candidates = np.geomspace(0.45, 3.0, 90)
    losses = [log_loss(probabilities(x, weights, bias, value), y) for value in candidates]
    return float(candidates[int(np.argmin(losses))])


def class_index(series):
    mapping = {label: index for index, label in enumerate(CLASSES)}
    normalized = series.astype(str).str.upper().str.strip()
    return normalized.map(mapping)


def prepare_frame(frame, target):
    label_column = f"label_{target}"
    required = ["session_date", "snapshot_at", *FEATURE_NAMES, label_column]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns for {target}: {', '.join(missing)}")

    work = frame[required].copy()
    work["snapshot_at"] = pd.to_datetime(work["snapshot_at"], utc=True, errors="coerce")
    work["session_date"] = pd.to_datetime(work["session_date"], errors="coerce").dt.date
    for feature in FEATURE_NAMES:
        work[feature] = pd.to_numeric(work[feature], errors="coerce")
    work["y"] = class_index(work[label_column])
    # Labels/timestamps must exist. Feature NaNs are allowed and are imputed
    # strictly from the training split later.
    work = work.dropna(subset=["session_date", "snapshot_at", "y"])
    work["y"] = work["y"].astype(int)
    work = work.sort_values(["session_date", "snapshot_at"]).reset_index(drop=True)
    return work


def chronological_splits(work):
    if len(work) < 500:
        raise ValueError(f"Need at least 500 labelled observations, found {len(work)}")

    dates = sorted(work["session_date"].unique())
    if len(dates) < 40:
        raise ValueError(
            f"Need at least 40 distinct session dates for date-safe train/validation/calibration/test splits, found {len(dates)}"
        )

    n_dates = len(dates)
    train_end = max(1, int(n_dates * 0.60))
    validation_end = max(train_end + 1, int(n_dates * 0.75))
    calibration_end = max(validation_end + 1, int(n_dates * 0.875))
    calibration_end = min(calibration_end, n_dates - 1)

    train_dates = set(dates[:train_end])
    validation_dates = set(dates[train_end:validation_end])
    calibration_dates = set(dates[validation_end:calibration_end])
    test_dates = set(dates[calibration_end:])

    splits = (
        work.loc[work["session_date"].isin(train_dates)].copy(),
        work.loc[work["session_date"].isin(validation_dates)].copy(),
        work.loc[work["session_date"].isin(calibration_dates)].copy(),
        work.loc[work["session_date"].isin(test_dates)].copy(),
    )

    if any(split.empty for split in splits):
        raise ValueError("Chronological date split produced an empty partition")

    return splits


def matrix(frame, *, impute=None, mean=None, scale=None):
    x = frame[list(FEATURE_NAMES)].to_numpy(dtype=float)

    if impute is None:
        impute = np.nanmedian(x, axis=0)
        # A feature missing from the entire training partition is not usable.
        if np.isnan(impute).any():
            bad = [name for name, value in zip(FEATURE_NAMES, impute) if np.isnan(value)]
            raise ValueError(
                "Training partition has no finite observations for: " + ", ".join(bad)
            )

    x = np.where(np.isnan(x), impute, x)

    if mean is None:
        mean = np.mean(x, axis=0)
    if scale is None:
        scale = np.std(x, axis=0)
        scale = np.where(scale < 1e-9, 1.0, scale)

    return (x - mean) / scale, impute, mean, scale


def evaluate(x, y, weights, bias, temperature):
    p = probabilities(x, weights, bias, temperature)
    counts = {label: int(np.sum(y == index)) for index, label in enumerate(CLASSES)}
    return {
        "samples": int(len(y)),
        "accuracy": round(accuracy(p, y), 6),
        "log_loss": round(log_loss(p, y), 6),
        "brier": round(brier_score(p, y), 6),
        "class_counts": counts,
    }


def train_target(frame, target):
    work = prepare_frame(frame, target)
    train, validation, calibration, test = chronological_splits(work)

    x_train, impute, mean, scale = matrix(train)
    x_validation, _, _, _ = matrix(validation, impute=impute, mean=mean, scale=scale)
    x_calibration, _, _, _ = matrix(calibration, impute=impute, mean=mean, scale=scale)
    x_test, _, _, _ = matrix(test, impute=impute, mean=mean, scale=scale)

    y_train = train["y"].to_numpy(dtype=int)
    y_validation = validation["y"].to_numpy(dtype=int)
    y_calibration = calibration["y"].to_numpy(dtype=int)
    y_test = test["y"].to_numpy(dtype=int)

    weights, bias = fit_softmax(x_train, y_train)
    temperature = fit_temperature(x_calibration, y_calibration, weights, bias)

    baseline_class = int(np.bincount(y_train, minlength=3).argmax())
    baseline_accuracy = float(np.mean(y_test == baseline_class))

    missing_rates = {
        name: round(float(train[name].isna().mean()), 6)
        for name in FEATURE_NAMES
    }

    metrics = {
        "train": evaluate(x_train, y_train, weights, bias, 1.0),
        "validation": evaluate(x_validation, y_validation, weights, bias, 1.0),
        "calibration_before": evaluate(x_calibration, y_calibration, weights, bias, 1.0),
        "calibration_after": evaluate(x_calibration, y_calibration, weights, bias, temperature),
        "test": evaluate(x_test, y_test, weights, bias, temperature),
        "majority_baseline_test_accuracy": round(baseline_accuracy, 6),
        "temperature": round(temperature, 8),
        "first_snapshot": str(work["snapshot_at"].iloc[0]),
        "last_snapshot": str(work["snapshot_at"].iloc[-1]),
        "distinct_session_dates": int(work["session_date"].nunique()),
        "train_feature_missing_rates": missing_rates,
    }

    return {
        "feature_names": list(FEATURE_NAMES),
        "impute": impute.tolist(),
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "weights": weights.tolist(),
        "bias": bias.tolist(),
        "temperature": temperature,
        "metrics": metrics,
    }


def main():
    parser = argparse.ArgumentParser(description="Train Orion premarket predictive models from a leakage-safe feature dataset.")
    parser.add_argument("dataset", type=Path, help="CSV containing snapshot_at, feature columns and label_<target> columns")
    parser.add_argument("--output", type=Path, default=Path("backend/data/models/premarket_predictive_v2.json"))
    parser.add_argument("--targets", nargs="*", choices=TARGETS, default=list(TARGETS))
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    artifact = {
        "model_version": MODEL_VERSION,
        "classes": list(CLASSES),
        "metadata": {
            "training_rows_raw": int(len(frame)),
            "split_policy": "date_safe_chronological_60_train_15_validation_12.5_calibration_12.5_test",
            "calibration": "held_out_temperature_scaling",
            "missing_features": "train_only_median_imputation",
            "probability_semantics": "Empirical three-class directional probabilities; never use a rule score as probability.",
        },
        "targets": {},
    }

    for target in args.targets:
        print(f"Training {target}...")
        artifact["targets"][target] = train_target(frame, target)
        print(json.dumps(artifact["targets"][target]["metrics"]["test"], indent=2))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"Saved calibrated model artifact to {args.output}")


if __name__ == "__main__":
    main()
