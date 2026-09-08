from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from premarket_directional_v4_common import PREMARKET_TARGETS
from premarket_directional_v5_common import (
    MODEL_VERSION,
    V5_FEATURE_NAMES,
    evaluate_gate,
    fit_hybrid_model,
    prepare_v5_frame,
)


def chronological_splits(work: pd.DataFrame):
    dates = sorted(work["session_date"].unique())
    if len(dates) < 40:
        raise ValueError(f"Need at least 40 session dates, found {len(dates)}")
    n = len(dates)
    train_end = max(1, int(n * 0.60))
    validation_end = max(train_end + 1, int(n * 0.75))
    calibration_end = max(validation_end + 1, int(n * 0.875))
    calibration_end = min(calibration_end, n - 1)
    groups = (
        set(dates[:train_end]),
        set(dates[train_end:validation_end]),
        set(dates[validation_end:calibration_end]),
        set(dates[calibration_end:]),
    )
    parts = tuple(work[work["session_date"].isin(group)].copy() for group in groups)
    if any(part.empty for part in parts):
        raise ValueError("Chronological split produced an empty partition")
    return parts


def train_target(frame: pd.DataFrame, target: str) -> dict:
    work = prepare_v5_frame(frame, target)
    train, validation, calibration, test = chronological_splits(work)
    model = fit_hybrid_model(train, calibration)
    predicted_return, p_up = model.predict(test)

    mae = float(np.mean(np.abs(predicted_return - test["future_return_pct"].to_numpy(dtype=float))))
    corr = np.corrcoef(predicted_return, test["future_return_pct"].to_numpy(dtype=float))[0, 1]
    if not np.isfinite(corr):
        corr = 0.0
    direction_acc = float(np.mean((predicted_return > 0) == (test["future_return_pct"].to_numpy(dtype=float) > 0)))

    gate = evaluate_gate(
        test,
        predicted_return,
        p_up,
        normalized_move_threshold=0.20,
        direction_confidence_threshold=0.55,
    )

    return {
        "feature_names": list(V5_FEATURE_NAMES),
        "impute": model.impute.tolist(),
        "mean": model.mean.tolist(),
        "scale": model.scale.tolist(),
        "return_stage": {
            "weights": model.return_weights.tolist(),
            "bias": float(model.return_bias),
        },
        "direction_stage": {
            "weights": model.direction_weights.tolist(),
            "bias": float(model.direction_bias),
            "temperature": float(model.direction_temperature),
        },
        "test_metrics": {
            "samples": int(len(test)),
            "return_mae_pct": round(mae, 6),
            "return_correlation": round(float(corr), 6),
            "raw_regression_direction_accuracy": round(direction_acc, 6),
            "default_gate": gate,
        },
        "distinct_session_dates": int(work["session_date"].nunique()),
    }


def main():
    parser = argparse.ArgumentParser(description="Train Orion Premarket Directional Engine v5 hybrid return model.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--targets", nargs="*", choices=PREMARKET_TARGETS, default=list(PREMARKET_TARGETS))
    parser.add_argument("--output", type=Path, default=Path("backend/data/models/premarket_directional_v5.json"))
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    artifact = {
        "model_version": MODEL_VERSION,
        "feature_names": list(V5_FEATURE_NAMES),
        "metadata": {
            "architecture": "ridge_future_return_plus_calibrated_binary_direction",
            "target_schema": "continuous_future_return_horizon_aware_v2",
            "split_policy": "date_safe_chronological_60_train_15_validation_12.5_calibration_12.5_test",
            "training_rows_raw": int(len(frame)),
        },
        "targets": {},
    }

    for target in args.targets:
        print(f"Training v5 {target}...", flush=True)
        result = train_target(frame, target)
        artifact["targets"][target] = result
        print(json.dumps(result["test_metrics"], indent=2))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"Saved v5 model artifact to {args.output}")


if __name__ == "__main__":
    main()
