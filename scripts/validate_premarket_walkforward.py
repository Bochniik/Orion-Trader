from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from train_premarket_predictive import (
    CLASSES,
    FEATURE_NAMES,
    TARGETS,
    class_index,
    fit_softmax,
    fit_temperature,
    matrix,
    probabilities,
)


def prepare(frame: pd.DataFrame, target: str) -> pd.DataFrame:
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
    work["y"] = class_index(work[label])
    work = work.dropna(subset=["ticker", "session_date", "snapshot_at", "y"])
    work["y"] = work["y"].astype(int)
    return work.sort_values(["session_date", "snapshot_at", "ticker"]).reset_index(drop=True)


def multiclass_log_loss(p: np.ndarray, y: np.ndarray) -> float:
    chosen = p[np.arange(len(y)), y]
    return float(-np.mean(np.log(np.clip(chosen, 1e-12, 1.0))))


def brier(p: np.ndarray, y: np.ndarray) -> float:
    truth = np.zeros_like(p)
    truth[np.arange(len(y)), y] = 1.0
    return float(np.mean(np.sum((p - truth) ** 2, axis=1)))


def confidence_buckets(confidence: np.ndarray, correct: np.ndarray) -> list[dict]:
    edges = [(0.0, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.000001)]
    rows = []
    total = len(confidence)
    for low, high in edges:
        mask = (confidence >= low) & (confidence < high)
        n = int(mask.sum())
        if not n:
            continue
        rows.append({
            "bucket": f"{low:.2f}-{min(high, 1.0):.2f}",
            "samples": n,
            "coverage": round(n / total, 6),
            "accuracy": round(float(correct[mask].mean()), 6),
            "mean_confidence": round(float(confidence[mask].mean()), 6),
        })
    return rows


def per_ticker_metrics(tickers: np.ndarray, correct: np.ndarray, min_samples: int = 50) -> list[dict]:
    rows = []
    for ticker in sorted(set(tickers.tolist())):
        mask = tickers == ticker
        n = int(mask.sum())
        if n < min_samples:
            continue
        rows.append({"ticker": ticker, "samples": n, "accuracy": round(float(correct[mask].mean()), 6)})
    return sorted(rows, key=lambda row: (-row["samples"], row["ticker"]))


def validate_target(frame: pd.DataFrame, target: str, *, min_train_days: int, calibration_days: int, test_days: int) -> dict:
    work = prepare(frame, target)
    dates = sorted(work["session_date"].unique())
    if len(dates) < min_train_days + calibration_days + test_days:
        raise ValueError(f"{target}: not enough session dates ({len(dates)})")

    fold_rows = []
    all_probabilities = []
    all_y = []
    all_tickers = []
    all_dates = []

    test_start = min_train_days + calibration_days
    fold_index = 0
    while test_start < len(dates):
        test_end = min(len(dates), test_start + test_days)
        history_dates = dates[:test_start]
        train_dates = history_dates[:-calibration_days]
        calibration_dates = history_dates[-calibration_days:]
        test_dates_fold = dates[test_start:test_end]
        if not train_dates or not calibration_dates or not test_dates_fold:
            break

        train = work[work["session_date"].isin(train_dates)].copy()
        calibration = work[work["session_date"].isin(calibration_dates)].copy()
        test = work[work["session_date"].isin(test_dates_fold)].copy()
        if len(train) < 500 or calibration.empty or test.empty:
            test_start = test_end
            continue

        x_train, impute, mean, scale = matrix(train)
        x_cal, _, _, _ = matrix(calibration, impute=impute, mean=mean, scale=scale)
        x_test, _, _, _ = matrix(test, impute=impute, mean=mean, scale=scale)
        y_train = train["y"].to_numpy(dtype=int)
        y_cal = calibration["y"].to_numpy(dtype=int)
        y_test = test["y"].to_numpy(dtype=int)

        weights, bias = fit_softmax(x_train, y_train)
        temperature = fit_temperature(x_cal, y_cal, weights, bias)
        p = probabilities(x_test, weights, bias, temperature)
        pred = np.argmax(p, axis=1)
        correct = pred == y_test
        baseline_class = int(np.bincount(y_train, minlength=3).argmax())
        baseline_accuracy = float(np.mean(y_test == baseline_class))

        fold_rows.append({
            "fold": fold_index,
            "train_first": str(train_dates[0]),
            "train_last": str(train_dates[-1]),
            "calibration_first": str(calibration_dates[0]),
            "calibration_last": str(calibration_dates[-1]),
            "test_first": str(test_dates_fold[0]),
            "test_last": str(test_dates_fold[-1]),
            "samples": int(len(test)),
            "accuracy": round(float(correct.mean()), 6),
            "baseline_accuracy": round(baseline_accuracy, 6),
            "lift": round(float(correct.mean()) - baseline_accuracy, 6),
            "log_loss": round(multiclass_log_loss(p, y_test), 6),
            "brier": round(brier(p, y_test), 6),
            "temperature": round(float(temperature), 6),
        })

        all_probabilities.append(p)
        all_y.append(y_test)
        all_tickers.append(test["ticker"].to_numpy(dtype=str))
        all_dates.append(test["session_date"].astype(str).to_numpy())
        fold_index += 1
        test_start = test_end

    if not fold_rows:
        raise ValueError(f"{target}: no valid walk-forward folds")

    p = np.vstack(all_probabilities)
    y = np.concatenate(all_y)
    tickers = np.concatenate(all_tickers)
    pred = np.argmax(p, axis=1)
    correct = pred == y
    confidence = np.max(p, axis=1)
    fold_lifts = np.asarray([row["lift"] for row in fold_rows], dtype=float)

    return {
        "target": target,
        "samples": int(len(y)),
        "folds": fold_rows,
        "aggregate": {
            "accuracy": round(float(correct.mean()), 6),
            "log_loss": round(multiclass_log_loss(p, y), 6),
            "brier": round(brier(p, y), 6),
            "positive_lift_folds": int(np.sum(fold_lifts > 0)),
            "total_folds": int(len(fold_lifts)),
            "median_fold_lift": round(float(np.median(fold_lifts)), 6),
            "mean_fold_lift": round(float(np.mean(fold_lifts)), 6),
        },
        "confidence_buckets": confidence_buckets(confidence, correct),
        "per_ticker": per_ticker_metrics(tickers, correct),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Expanding walk-forward validation for Orion premarket models.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--targets", nargs="*", choices=TARGETS, default=list(TARGETS))
    parser.add_argument("--min-train-days", type=int, default=40)
    parser.add_argument("--calibration-days", type=int, default=10)
    parser.add_argument("--test-days", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("backend/data/models/premarket_walkforward_report.json"))
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    report = {
        "dataset": str(args.dataset),
        "rows": int(len(frame)),
        "policy": {
            "type": "expanding_walk_forward",
            "min_train_days": args.min_train_days,
            "calibration_days": args.calibration_days,
            "test_days": args.test_days,
        },
        "targets": {},
    }

    for target in args.targets:
        print(f"Validating {target}...", flush=True)
        result = validate_target(
            frame,
            target,
            min_train_days=args.min_train_days,
            calibration_days=args.calibration_days,
            test_days=args.test_days,
        )
        report["targets"][target] = result
        agg = result["aggregate"]
        print(
            f"  samples={result['samples']} folds={agg['total_folds']} "
            f"accuracy={agg['accuracy']:.4f} mean_lift={agg['mean_fold_lift']:+.4f} "
            f"median_lift={agg['median_fold_lift']:+.4f} "
            f"positive_folds={agg['positive_lift_folds']}/{agg['total_folds']} "
            f"logloss={agg['log_loss']:.4f} brier={agg['brier']:.4f}"
        )
        for bucket in result["confidence_buckets"]:
            if bucket["samples"] >= 100:
                print(
                    f"    conf {bucket['bucket']}: n={bucket['samples']} "
                    f"coverage={bucket['coverage']:.1%} accuracy={bucket['accuracy']:.1%} "
                    f"mean_conf={bucket['mean_confidence']:.1%}"
                )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved walk-forward report to {args.output}")


if __name__ == "__main__":
    main()
