from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from train_premarket_predictive import FEATURE_NAMES, TARGETS, matrix
from train_premarket_hierarchical import (
    binary_probabilities,
    fit_binary_logistic,
    fit_binary_temperature,
    prepare_frame,
)


LABEL_TO_IDX = {"DOWN": 0, "NO_EDGE": 1, "UP": 2}


def fit_stage(x_train, y_train, x_cal, y_cal):
    weights, bias = fit_binary_logistic(x_train, y_train)
    temperature = fit_binary_temperature(x_cal, y_cal, weights, bias)
    return weights, bias, temperature


def threshold_rows(p_edge, p_up_cond, y_true, thresholds):
    rows = []
    for edge_threshold, direction_threshold in thresholds:
        confidence = np.maximum(p_up_cond, 1.0 - p_up_cond)
        direction = np.where(p_up_cond >= 0.5, 2, 0)
        mask = (p_edge >= edge_threshold) & (confidence >= direction_threshold)
        n = int(mask.sum())
        if not n:
            rows.append({
                "edge_threshold": edge_threshold,
                "direction_threshold": direction_threshold,
                "samples": 0,
                "coverage": 0.0,
                "accuracy": None,
                "up_precision": None,
                "down_precision": None,
            })
            continue
        pred = direction[mask]
        truth = y_true[mask]
        up_mask = pred == 2
        down_mask = pred == 0
        rows.append({
            "edge_threshold": edge_threshold,
            "direction_threshold": direction_threshold,
            "samples": n,
            "coverage": round(n / len(y_true), 6),
            "accuracy": round(float(np.mean(pred == truth)), 6),
            "up_precision": round(float(np.mean(truth[up_mask] == 2)), 6) if up_mask.any() else None,
            "down_precision": round(float(np.mean(truth[down_mask] == 0)), 6) if down_mask.any() else None,
            "mean_edge_probability": round(float(np.mean(p_edge[mask])), 6),
            "mean_direction_confidence": round(float(np.mean(confidence[mask])), 6),
        })
    return rows


def validate_target(frame, target, *, min_train_days, calibration_days, test_days):
    work = prepare_frame(frame, target)
    dates = sorted(work["session_date"].unique())
    if len(dates) < min_train_days + calibration_days + test_days:
        raise ValueError(f"{target}: not enough session dates ({len(dates)})")

    thresholds = [
        (0.50, 0.50),
        (0.55, 0.55),
        (0.60, 0.55),
        (0.60, 0.60),
        (0.65, 0.60),
        (0.70, 0.60),
        (0.70, 0.65),
    ]

    folds = []
    all_edge = []
    all_up_cond = []
    all_y = []
    all_tickers = []

    test_start = min_train_days + calibration_days
    fold_idx = 0
    while test_start < len(dates):
        test_end = min(len(dates), test_start + test_days)
        history_dates = dates[:test_start]
        train_dates = history_dates[:-calibration_days]
        cal_dates = history_dates[-calibration_days:]
        test_dates_fold = dates[test_start:test_end]
        if not train_dates or not cal_dates or not test_dates_fold:
            break

        train = work[work["session_date"].isin(train_dates)].copy()
        cal = work[work["session_date"].isin(cal_dates)].copy()
        test = work[work["session_date"].isin(test_dates_fold)].copy()
        if len(train) < 500 or cal.empty or test.empty:
            test_start = test_end
            continue

        x_train, impute, mean, scale = matrix(train)
        x_cal, _, _, _ = matrix(cal, impute=impute, mean=mean, scale=scale)
        x_test, _, _, _ = matrix(test, impute=impute, mean=mean, scale=scale)

        y_edge_train = (train["label"].to_numpy() != "NO_EDGE").astype(int)
        y_edge_cal = (cal["label"].to_numpy() != "NO_EDGE").astype(int)
        edge_w, edge_b, edge_t = fit_stage(x_train, y_edge_train, x_cal, y_edge_cal)

        train_dir = train["label"].to_numpy() != "NO_EDGE"
        cal_dir = cal["label"].to_numpy() != "NO_EDGE"
        if int(train_dir.sum()) < 300 or int(cal_dir.sum()) < 50:
            test_start = test_end
            continue

        y_dir_train = (train.loc[train_dir, "label"].to_numpy() == "UP").astype(int)
        y_dir_cal = (cal.loc[cal_dir, "label"].to_numpy() == "UP").astype(int)
        dir_w, dir_b, dir_t = fit_stage(x_train[train_dir], y_dir_train, x_cal[cal_dir], y_dir_cal)

        p_edge = binary_probabilities(x_test, edge_w, edge_b, edge_t)
        p_up_cond = binary_probabilities(x_test, dir_w, dir_b, dir_t)
        y_three = np.array([LABEL_TO_IDX[v] for v in test["label"].to_numpy()], dtype=int)

        base_direction = np.where(p_up_cond >= 0.5, 2, 0)
        base_direction_accuracy = float(np.mean(base_direction == y_three))
        edge_truth = y_three != 1
        edge_pred = p_edge >= 0.5
        edge_accuracy = float(np.mean(edge_pred == edge_truth))

        folds.append({
            "fold": fold_idx,
            "train_first": str(train_dates[0]),
            "train_last": str(train_dates[-1]),
            "test_first": str(test_dates_fold[0]),
            "test_last": str(test_dates_fold[-1]),
            "samples": int(len(test)),
            "edge_accuracy": round(edge_accuracy, 6),
            "raw_direction_accuracy_all": round(base_direction_accuracy, 6),
            "thresholds": threshold_rows(p_edge, p_up_cond, y_three, thresholds),
        })

        all_edge.append(p_edge)
        all_up_cond.append(p_up_cond)
        all_y.append(y_three)
        all_tickers.append(test["ticker"].to_numpy(dtype=str))
        fold_idx += 1
        test_start = test_end

    if not folds:
        raise ValueError(f"{target}: no valid folds")

    p_edge = np.concatenate(all_edge)
    p_up_cond = np.concatenate(all_up_cond)
    y = np.concatenate(all_y)
    tickers = np.concatenate(all_tickers)

    aggregate_thresholds = threshold_rows(p_edge, p_up_cond, y, thresholds)
    chosen = [r for r in aggregate_thresholds if r["samples"] >= 100 and r["accuracy"] is not None]
    best = max(chosen, key=lambda r: (r["accuracy"], r["samples"])) if chosen else None

    per_ticker = []
    if best:
        confidence = np.maximum(p_up_cond, 1.0 - p_up_cond)
        pred = np.where(p_up_cond >= 0.5, 2, 0)
        global_mask = (p_edge >= best["edge_threshold"]) & (confidence >= best["direction_threshold"])
        for ticker in sorted(set(tickers.tolist())):
            mask = global_mask & (tickers == ticker)
            n = int(mask.sum())
            if n < 20:
                continue
            per_ticker.append({
                "ticker": ticker,
                "samples": n,
                "accuracy": round(float(np.mean(pred[mask] == y[mask])), 6),
            })

    return {
        "target": target,
        "samples": int(len(y)),
        "fold_count": len(folds),
        "folds": folds,
        "thresholds": aggregate_thresholds,
        "best_threshold_with_min_100_samples": best,
        "per_ticker_at_best_threshold": per_ticker,
    }


def main():
    parser = argparse.ArgumentParser(description="Walk-forward validation for Orion hierarchical EDGE -> DIRECTION models.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--targets", nargs="*", choices=TARGETS, default=list(TARGETS))
    parser.add_argument("--min-train-days", type=int, default=40)
    parser.add_argument("--calibration-days", type=int, default=10)
    parser.add_argument("--test-days", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("backend/data/models/premarket_hierarchical_walkforward_report.json"))
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    report = {
        "dataset": str(args.dataset),
        "rows": int(len(frame)),
        "architecture": "EDGE_vs_NO_EDGE_then_UP_vs_DOWN_given_EDGE",
        "targets": {},
    }

    for target in args.targets:
        print(f"Validating hierarchical {target}...", flush=True)
        result = validate_target(
            frame,
            target,
            min_train_days=args.min_train_days,
            calibration_days=args.calibration_days,
            test_days=args.test_days,
        )
        report["targets"][target] = result
        print(f"  samples={result['samples']} folds={result['fold_count']}")
        for row in result["thresholds"]:
            if row["samples"]:
                print(
                    f"    edge>={row['edge_threshold']:.2f} dir>={row['direction_threshold']:.2f}: "
                    f"n={row['samples']} coverage={row['coverage']:.1%} acc={row['accuracy']:.1%} "
                    f"UP={row['up_precision'] if row['up_precision'] is not None else 'NA'} "
                    f"DOWN={row['down_precision'] if row['down_precision'] is not None else 'NA'}"
                )
        best = result["best_threshold_with_min_100_samples"]
        if best:
            print(
                f"  BEST(min100): edge>={best['edge_threshold']:.2f} dir>={best['direction_threshold']:.2f} "
                f"n={best['samples']} coverage={best['coverage']:.1%} acc={best['accuracy']:.1%}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved hierarchical walk-forward report to {args.output}")


if __name__ == "__main__":
    main()
