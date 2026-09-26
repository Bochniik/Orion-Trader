from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from premarket_directional_v4_common import PREMARKET_TARGETS
from premarket_directional_v5_common import (
    evaluate_gate,
    fit_hybrid_model,
    prepare_v5_frame,
)


EVIDENCE_ROLE = "development_threshold_search"
PROMOTION_ELIGIBLE = False

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


def validate_target(frame: pd.DataFrame, target: str, *, min_train_days=40, calibration_days=10, test_days=5):
    work = prepare_v5_frame(frame, target)
    dates = sorted(work["session_date"].unique())
    if len(dates) < min_train_days + calibration_days + test_days:
        raise ValueError(f"{target}: not enough dates ({len(dates)})")

    folds = []
    pooled = {threshold: [] for threshold in THRESHOLDS}
    test_start = min_train_days + calibration_days
    fold_index = 0

    while test_start < len(dates):
        test_end = min(len(dates), test_start + test_days)
        history_dates = dates[:test_start]
        train_dates = history_dates[:-calibration_days]
        cal_dates = history_dates[-calibration_days:]
        test_dates_fold = dates[test_start:test_end]
        if not train_dates or not cal_dates or not test_dates_fold:
            break

        train = work[work["session_date"].isin(train_dates)].copy()
        calibration = work[work["session_date"].isin(cal_dates)].copy()
        test = work[work["session_date"].isin(test_dates_fold)].copy()
        if len(train) < 500 or len(calibration) < 100 or test.empty:
            test_start = test_end
            continue

        model = fit_hybrid_model(train, calibration)
        predicted_return, p_up = model.predict(test)

        fold_rows = []
        for threshold in THRESHOLDS:
            move_threshold, confidence_threshold = threshold
            row = evaluate_gate(
                test,
                predicted_return,
                p_up,
                normalized_move_threshold=move_threshold,
                direction_confidence_threshold=confidence_threshold,
            )
            row.update({
                "normalized_move_threshold": move_threshold,
                "direction_confidence_threshold": confidence_threshold,
            })
            fold_rows.append(row)
            if row["samples"]:
                pooled[threshold].append(row)

        folds.append({
            "fold": fold_index,
            "test_first": str(test_dates_fold[0]),
            "test_last": str(test_dates_fold[-1]),
            "samples": int(len(test)),
            "thresholds": fold_rows,
        })
        fold_index += 1
        test_start = test_end

    summaries = []
    for threshold in THRESHOLDS:
        rows = pooled[threshold]
        total_samples = int(sum(row["samples"] for row in rows))
        if total_samples == 0:
            summaries.append({
                "normalized_move_threshold": threshold[0],
                "direction_confidence_threshold": threshold[1],
                "samples": 0,
                "folds_evaluable": 0,
                "median_fold_accuracy": None,
                "min_fold_accuracy": None,
                "positive_folds": 0,
                "weighted_accuracy": None,
                "weighted_mean_signed_return_pct": None,
            })
            continue

        accuracies = [row["directional_accuracy"] for row in rows if row["directional_accuracy"] is not None]
        positive_folds = sum(1 for value in accuracies if value > 0.5)
        weighted_accuracy = sum(row["directional_accuracy"] * row["samples"] for row in rows) / total_samples
        weighted_signed_return = sum(row["mean_signed_return_pct"] * row["samples"] for row in rows) / total_samples
        summaries.append({
            "normalized_move_threshold": threshold[0],
            "direction_confidence_threshold": threshold[1],
            "samples": total_samples,
            "folds_evaluable": len(accuracies),
            "median_fold_accuracy": round(float(np.median(accuracies)), 6) if accuracies else None,
            "min_fold_accuracy": round(float(np.min(accuracies)), 6) if accuracies else None,
            "positive_folds": positive_folds,
            "weighted_accuracy": round(float(weighted_accuracy), 6),
            "weighted_mean_signed_return_pct": round(float(weighted_signed_return), 6),
        })

    robust = [
        row for row in summaries
        if row["samples"] >= 200
        and row["folds_evaluable"] >= 4
        and row["median_fold_accuracy"] is not None
        and row["median_fold_accuracy"] >= 0.55
        and row["positive_folds"] >= max(3, int(np.ceil(row["folds_evaluable"] * 2 / 3)))
        and row["weighted_mean_signed_return_pct"] is not None
        and row["weighted_mean_signed_return_pct"] > 0
    ]
    best = max(
        robust,
        key=lambda row: (row["weighted_accuracy"], row["samples"]),
        default=None,
    )

    return {
        "evidence_role": EVIDENCE_ROLE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "selection_warning": (
            "Threshold candidates and robust_gate are selected using outcomes from these "
            "walk-forward test folds. Treat this report as development evidence only; "
            "freeze a gate before evaluating an untouched or forward promotion holdout."
        ),
        "target": target,
        "samples": int(sum(fold["samples"] for fold in folds)),
        "fold_count": len(folds),
        "thresholds": summaries,
        "robust_gate": best,
        "folds": folds,
    }


def main():
    parser = argparse.ArgumentParser(description="Walk-forward validation for Orion Premarket Directional Engine v5 hybrid return model.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--targets", nargs="*", choices=PREMARKET_TARGETS, default=list(PREMARKET_TARGETS))
    parser.add_argument("--output", type=Path, default=Path("backend/data/models/premarket_directional_v5_walkforward.json"))
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    report = {
        "contract": "orion-premarket-v5-threshold-search-v2",
        "evidence_role": EVIDENCE_ROLE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "selection_warning": (
            "This report searches threshold candidates on observed walk-forward outcomes. "
            "It must not be used as promotion evidence for the selected gate."
        ),
        "dataset": str(args.dataset),
        "rows": int(len(frame)),
        "targets": {},
    }

    for target in args.targets:
        print(f"Validating v5 {target}...", flush=True)
        result = validate_target(frame, target)
        report["targets"][target] = result
        print(f"  samples={result['samples']} folds={result['fold_count']}")
        for row in result["thresholds"]:
            acc = "NA" if row["weighted_accuracy"] is None else f"{row['weighted_accuracy']:.1%}"
            median = "NA" if row["median_fold_accuracy"] is None else f"{row['median_fold_accuracy']:.1%}"
            signed = "NA" if row["weighted_mean_signed_return_pct"] is None else f"{row['weighted_mean_signed_return_pct']:+.4f}%"
            print(
                f"    move>={row['normalized_move_threshold']:.2f}sigma conf>={row['direction_confidence_threshold']:.2f}: "
                f"n={row['samples']} acc={acc} median={median} folds={row['positive_folds']}/{row['folds_evaluable']} signed={signed}"
            )
        robust = result["robust_gate"]
        if robust:
            print(
                f"  ROBUST: move>={robust['normalized_move_threshold']:.2f}sigma "
                f"conf>={robust['direction_confidence_threshold']:.2f} "
                f"n={robust['samples']} acc={robust['weighted_accuracy']:.1%} "
                f"median={robust['median_fold_accuracy']:.1%} "
                f"signed={robust['weighted_mean_signed_return_pct']:+.4f}%"
            )
        else:
            print("  ROBUST: none")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved v5 walk-forward report to {args.output}")


if __name__ == "__main__":
    main()
