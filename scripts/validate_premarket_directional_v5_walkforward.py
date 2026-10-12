from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from backend.evals.causal_walk_forward import build_expanding_walk_forward, fold_manifest
from premarket_directional_v4_common import PREMARKET_TARGETS
from premarket_directional_v5_common import (
    evaluate_gate,
    fit_hybrid_model,
    prepare_v5_frame,
)


THRESHOLDS = (
    (0.10, 0.52),
    (0.15, 0.52),
    (0.20, 0.52),
    (0.20, 0.55),
    (0.25, 0.55),
    (0.30, 0.55),
    (0.30, 0.60),
    (0.40, 0.60),
)


def _selection_key(row):
    samples = int(row.get("samples") or 0)
    accuracy = row.get("directional_accuracy")
    signed_return = row.get("mean_signed_return_pct")
    return (
        samples > 0,
        float(accuracy) if accuracy is not None else -1.0,
        float(signed_return) if signed_return is not None else float("-inf"),
        samples,
    )


def _evaluate_thresholds(frame, predicted_return, p_up):
    rows = []
    for move_threshold, confidence_threshold in THRESHOLDS:
        row = evaluate_gate(
            frame,
            predicted_return,
            p_up,
            normalized_move_threshold=move_threshold,
            direction_confidence_threshold=confidence_threshold,
        )
        row.update(
            {
                "normalized_move_threshold": move_threshold,
                "direction_confidence_threshold": confidence_threshold,
            }
        )
        rows.append(row)
    return rows


def validate_target(
    frame: pd.DataFrame,
    target: str,
    *,
    min_train_days=40,
    validation_days=10,
    calibration_days=10,
    test_days=5,
):
    work = prepare_v5_frame(frame, target)
    dates = sorted(work["session_date"].unique())
    minimum_days = min_train_days + validation_days + calibration_days + test_days
    if len(dates) < minimum_days:
        raise ValueError(f"{target}: not enough dates ({len(dates)}; need {minimum_days})")

    timestamps = pd.to_datetime(pd.Series(dates), utc=True).dt.to_pydatetime().tolist()
    causal_folds = build_expanding_walk_forward(
        timestamps,
        train_size=min_train_days,
        validation_size=validation_days,
        calibration_size=calibration_days,
        test_size=test_days,
        step_size=test_days,
    )

    folds = []
    selected_test_rows = []
    selection_counts = Counter()

    for causal_fold in causal_folds:
        train_dates = [dates[index] for index in causal_fold.train]
        validation_dates = [dates[index] for index in causal_fold.validation]
        calibration_dates = [dates[index] for index in causal_fold.calibration]
        test_dates_fold = [dates[index] for index in causal_fold.test]

        train = work[work["session_date"].isin(train_dates)].copy()
        validation = work[work["session_date"].isin(validation_dates)].copy()
        calibration = work[work["session_date"].isin(calibration_dates)].copy()
        test = work[work["session_date"].isin(test_dates_fold)].copy()
        if len(train) < 500 or len(validation) < 100 or len(calibration) < 100 or test.empty:
            continue

        model = fit_hybrid_model(train, calibration)
        validation_return, validation_p_up = model.predict(validation)
        validation_rows = _evaluate_thresholds(validation, validation_return, validation_p_up)
        selected = max(validation_rows, key=_selection_key)
        selected_threshold = (
            selected["normalized_move_threshold"],
            selected["direction_confidence_threshold"],
        )
        selection_counts[selected_threshold] += 1

        predicted_return, p_up = model.predict(test)
        test_row = evaluate_gate(
            test,
            predicted_return,
            p_up,
            normalized_move_threshold=selected_threshold[0],
            direction_confidence_threshold=selected_threshold[1],
        )
        test_row.update(
            {
                "normalized_move_threshold": selected_threshold[0],
                "direction_confidence_threshold": selected_threshold[1],
            }
        )
        selected_test_rows.append(test_row)

        folds.append(
            {
                "fold": causal_fold.fold,
                "train_first": str(train_dates[0]),
                "train_last": str(train_dates[-1]),
                "validation_first": str(validation_dates[0]),
                "validation_last": str(validation_dates[-1]),
                "calibration_first": str(calibration_dates[0]),
                "calibration_last": str(calibration_dates[-1]),
                "test_first": str(test_dates_fold[0]),
                "test_last": str(test_dates_fold[-1]),
                "train_samples": int(len(train)),
                "validation_samples": int(len(validation)),
                "calibration_samples": int(len(calibration)),
                "test_samples": int(len(test)),
                "selected_on_validation": {
                    "normalized_move_threshold": selected_threshold[0],
                    "direction_confidence_threshold": selected_threshold[1],
                    "samples": int(selected.get("samples") or 0),
                    "directional_accuracy": selected.get("directional_accuracy"),
                    "mean_signed_return_pct": selected.get("mean_signed_return_pct"),
                },
                "untouched_test": test_row,
            }
        )

    total_samples = int(sum(row.get("samples") or 0 for row in selected_test_rows))
    accuracies = [
        float(row["directional_accuracy"])
        for row in selected_test_rows
        if row.get("directional_accuracy") is not None
    ]
    positive_folds = sum(value > 0.5 for value in accuracies)
    weighted_accuracy = (
        sum(float(row["directional_accuracy"]) * int(row["samples"]) for row in selected_test_rows)
        / total_samples
        if total_samples
        else None
    )
    weighted_signed_return = (
        sum(float(row["mean_signed_return_pct"]) * int(row["samples"]) for row in selected_test_rows)
        / total_samples
        if total_samples
        else None
    )
    untouched_test = {
        "samples": total_samples,
        "folds_evaluable": len(accuracies),
        "median_fold_accuracy": round(float(np.median(accuracies)), 6) if accuracies else None,
        "min_fold_accuracy": round(float(np.min(accuracies)), 6) if accuracies else None,
        "positive_folds": positive_folds,
        "weighted_accuracy": round(float(weighted_accuracy), 6) if weighted_accuracy is not None else None,
        "weighted_mean_signed_return_pct": (
            round(float(weighted_signed_return), 6) if weighted_signed_return is not None else None
        ),
    }
    robust = (
        total_samples >= 200
        and len(accuracies) >= 4
        and untouched_test["median_fold_accuracy"] is not None
        and untouched_test["median_fold_accuracy"] >= 0.55
        and positive_folds >= max(3, int(np.ceil(len(accuracies) * 2 / 3)))
        and weighted_signed_return is not None
        and weighted_signed_return > 0
    )

    selection_frequency = [
        {
            "normalized_move_threshold": threshold[0],
            "direction_confidence_threshold": threshold[1],
            "folds_selected": count,
        }
        for threshold, count in sorted(selection_counts.items())
    ]

    return {
        "contract": "orion-premarket-v5-causal-walk-forward-v1",
        "target": target,
        "protocol": {
            "split_contract": "orion-causal-walk-forward-v1",
            "threshold_selection_block": "validation",
            "probability_calibration_block": "calibration",
            "final_scoring_block": "untouched_test",
            "shuffling_allowed": False,
            "automatic_deployment_allowed": False,
        },
        "samples": total_samples,
        "fold_count": len(folds),
        "threshold_selection_frequency": selection_frequency,
        "untouched_test": untouched_test,
        "robust_research_result": robust,
        "split_manifest": fold_manifest(causal_folds, timestamps),
        "folds": folds,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Leakage-safe walk-forward validation for Orion Premarket Directional Engine v5."
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--targets", nargs="*", choices=PREMARKET_TARGETS, default=list(PREMARKET_TARGETS))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/models/premarket_directional_v5_walkforward.json"),
    )
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    report = {
        "contract": "orion-premarket-v5-causal-walk-forward-v1",
        "dataset": str(args.dataset),
        "rows": int(len(frame)),
        "targets": {},
    }

    for target in args.targets:
        print(f"Validating v5 {target}...", flush=True)
        result = validate_target(frame, target)
        report["targets"][target] = result
        test = result["untouched_test"]
        accuracy = "NA" if test["weighted_accuracy"] is None else f"{test['weighted_accuracy']:.1%}"
        signed = (
            "NA"
            if test["weighted_mean_signed_return_pct"] is None
            else f"{test['weighted_mean_signed_return_pct']:+.4f}%"
        )
        print(
            f"  untouched-test samples={test['samples']} folds={test['folds_evaluable']} "
            f"accuracy={accuracy} signed={signed} robust={result['robust_research_result']}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved causal v5 walk-forward report to {args.output}")


if __name__ == "__main__":
    main()
