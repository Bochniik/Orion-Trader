from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from premarket_directional_v4_common import (
    PREMARKET_TARGETS,
    REGIMES,
    apply_transform,
    fit_transform,
    prepare_v4_frame,
)
from train_premarket_hierarchical import (
    binary_probabilities,
    fit_binary_logistic,
    fit_binary_temperature,
)


THRESHOLDS = (
    (0.50, 0.50),
    (0.55, 0.55),
    (0.60, 0.55),
    (0.60, 0.60),
    (0.65, 0.60),
    (0.65, 0.65),
    (0.70, 0.60),
    (0.70, 0.65),
)


def fit_stage(x_train, y_train, x_cal, y_cal):
    weights, bias = fit_binary_logistic(x_train, y_train)
    temperature = fit_binary_temperature(x_cal, y_cal, weights, bias)
    return weights, bias, temperature


def stage_probability(stage, x):
    w, b, t = stage
    return binary_probabilities(x, w, b, t)


def fit_fold_models(train, cal, x_train, x_cal):
    edge_train = (train["label"].to_numpy() != "NO_EDGE").astype(int)
    edge_cal = (cal["label"].to_numpy() != "NO_EDGE").astype(int)
    global_edge = fit_stage(x_train, edge_train, x_cal, edge_cal)

    train_dir = train["label"].to_numpy() != "NO_EDGE"
    cal_dir = cal["label"].to_numpy() != "NO_EDGE"
    if int(train_dir.sum()) < 300 or int(cal_dir.sum()) < 50:
        raise ValueError("insufficient directional observations")
    global_direction = fit_stage(
        x_train[train_dir],
        (train.loc[train_dir, "label"].to_numpy() == "UP").astype(int),
        x_cal[cal_dir],
        (cal.loc[cal_dir, "label"].to_numpy() == "UP").astype(int),
    )

    regimes = {}
    for regime in REGIMES:
        train_regime = train["regime"].to_numpy() == regime
        cal_regime = cal["regime"].to_numpy() == regime
        train_regime_dir = train_regime & train_dir
        cal_regime_dir = cal_regime & cal_dir
        if int(train_regime.sum()) < 500 or int(cal_regime.sum()) < 100:
            continue
        if int(train_regime_dir.sum()) < 250 or int(cal_regime_dir.sum()) < 50:
            continue
        regimes[regime] = {
            "edge": fit_stage(
                x_train[train_regime], edge_train[train_regime],
                x_cal[cal_regime], edge_cal[cal_regime],
            ),
            "direction": fit_stage(
                x_train[train_regime_dir],
                (train.loc[train_regime_dir, "label"].to_numpy() == "UP").astype(int),
                x_cal[cal_regime_dir],
                (cal.loc[cal_regime_dir, "label"].to_numpy() == "UP").astype(int),
            ),
        }
    return global_edge, global_direction, regimes


def predict_fold(test, x_test, global_edge, global_direction, regimes):
    p_edge_global = stage_probability(global_edge, x_test)
    p_dir_global = stage_probability(global_direction, x_test)
    p_edge = p_edge_global.copy()
    p_dir = p_dir_global.copy()
    test_regime = test["regime"].to_numpy()
    for regime, stages in regimes.items():
        mask = test_regime == regime
        if not mask.any():
            continue
        p_edge[mask] = 0.65 * stage_probability(stages["edge"], x_test[mask]) + 0.35 * p_edge_global[mask]
        p_dir[mask] = 0.65 * stage_probability(stages["direction"], x_test[mask]) + 0.35 * p_dir_global[mask]
    return p_edge, p_dir


def metrics_for_mask(mask, p_dir, truth):
    n = int(mask.sum())
    if not n:
        return {"samples": 0, "accuracy": None, "up_precision": None, "down_precision": None}
    pred = np.where(p_dir[mask] >= 0.5, "UP", "DOWN")
    y = truth[mask]
    up = pred == "UP"
    down = pred == "DOWN"
    return {
        "samples": n,
        "accuracy": round(float(np.mean(pred == y)), 6),
        "up_precision": round(float(np.mean(y[up] == "UP")), 6) if up.any() else None,
        "down_precision": round(float(np.mean(y[down] == "DOWN")), 6) if down.any() else None,
    }


def threshold_metrics(p_edge, p_dir, truth, regimes):
    confidence = np.maximum(p_dir, 1.0 - p_dir)
    rows = []
    total = len(truth)
    for edge_threshold, direction_threshold in THRESHOLDS:
        mask = (p_edge >= edge_threshold) & (confidence >= direction_threshold)
        base = metrics_for_mask(mask, p_dir, truth)
        regime_rows = {}
        for regime in REGIMES:
            regime_mask = mask & (regimes == regime)
            regime_rows[regime] = metrics_for_mask(regime_mask, p_dir, truth)
        rows.append({
            "edge_threshold": edge_threshold,
            "direction_threshold": direction_threshold,
            "samples": base["samples"],
            "coverage": round(base["samples"] / total, 6),
            "accuracy": base["accuracy"],
            "up_precision": base["up_precision"],
            "down_precision": base["down_precision"],
            "regimes": regime_rows,
        })
    return rows


def fold_stability(folds, edge_threshold, direction_threshold, min_calls=20):
    rows = []
    for fold in folds:
        selected = next(
            row for row in fold["thresholds"]
            if row["edge_threshold"] == edge_threshold and row["direction_threshold"] == direction_threshold
        )
        if selected["samples"] >= min_calls and selected["accuracy"] is not None:
            rows.append(selected["accuracy"])
    if not rows:
        return {
            "evaluable_folds": 0,
            "positive_folds": 0,
            "median_accuracy": None,
            "mean_accuracy": None,
            "min_accuracy": None,
            "max_accuracy": None,
        }
    arr = np.asarray(rows, dtype=float)
    return {
        "evaluable_folds": len(rows),
        "positive_folds": int(np.sum(arr > 0.50)),
        "median_accuracy": round(float(np.median(arr)), 6),
        "mean_accuracy": round(float(np.mean(arr)), 6),
        "min_accuracy": round(float(np.min(arr)), 6),
        "max_accuracy": round(float(np.max(arr)), 6),
    }


def validate_target(frame, target, min_train_days=40, calibration_days=10, test_days=5):
    work = prepare_v4_frame(frame, target)
    dates = sorted(work["session_date"].unique())
    if len(dates) < min_train_days + calibration_days + test_days:
        raise ValueError(f"{target}: not enough dates ({len(dates)})")

    folds = []
    all_edge, all_dir, all_truth, all_regimes, all_tickers = [], [], [], [], []
    test_start = min_train_days + calibration_days
    fold_index = 0
    while test_start < len(dates):
        test_end = min(len(dates), test_start + test_days)
        history = dates[:test_start]
        train_dates = history[:-calibration_days]
        cal_dates = history[-calibration_days:]
        test_dates = dates[test_start:test_end]
        train = work[work["session_date"].isin(train_dates)].copy()
        cal = work[work["session_date"].isin(cal_dates)].copy()
        test = work[work["session_date"].isin(test_dates)].copy()
        if len(train) < 500 or cal.empty or test.empty:
            test_start = test_end
            continue

        x_train, impute, mean, scale = fit_transform(train)
        x_cal = apply_transform(cal, impute, mean, scale)
        x_test = apply_transform(test, impute, mean, scale)
        try:
            global_edge, global_direction, regime_models = fit_fold_models(train, cal, x_train, x_cal)
        except ValueError:
            test_start = test_end
            continue
        p_edge, p_dir = predict_fold(test, x_test, global_edge, global_direction, regime_models)
        truth = test["label"].to_numpy()
        regimes = test["regime"].to_numpy()
        thresholds = threshold_metrics(p_edge, p_dir, truth, regimes)
        folds.append({
            "fold": fold_index,
            "test_first": str(test_dates[0]),
            "test_last": str(test_dates[-1]),
            "samples": int(len(test)),
            "regime_models": sorted(regime_models),
            "thresholds": thresholds,
        })
        all_edge.append(p_edge)
        all_dir.append(p_dir)
        all_truth.append(truth)
        all_regimes.append(regimes)
        all_tickers.append(test["ticker"].to_numpy(dtype=str))
        fold_index += 1
        test_start = test_end

    if not folds:
        raise ValueError(f"{target}: no valid folds")

    p_edge = np.concatenate(all_edge)
    p_dir = np.concatenate(all_dir)
    truth = np.concatenate(all_truth)
    regimes = np.concatenate(all_regimes)
    tickers = np.concatenate(all_tickers)
    aggregate = threshold_metrics(p_edge, p_dir, truth, regimes)

    for row in aggregate:
        row["fold_stability"] = fold_stability(
            folds, row["edge_threshold"], row["direction_threshold"]
        )

    robust = []
    for row in aggregate:
        stability = row["fold_stability"]
        if row["samples"] < 100 or row["accuracy"] is None:
            continue
        if stability["evaluable_folds"] < 4:
            continue
        if stability["median_accuracy"] is None or stability["median_accuracy"] < 0.55:
            continue
        if stability["positive_folds"] / stability["evaluable_folds"] < 2 / 3:
            continue
        robust.append(row)
    best = max(robust, key=lambda r: (r["accuracy"], r["samples"])) if robust else None

    per_ticker = []
    if best:
        confidence = np.maximum(p_dir, 1.0 - p_dir)
        mask = (p_edge >= best["edge_threshold"]) & (confidence >= best["direction_threshold"])
        pred = np.where(p_dir >= 0.5, "UP", "DOWN")
        for ticker in sorted(set(tickers.tolist())):
            tmask = mask & (tickers == ticker)
            n = int(tmask.sum())
            if n < 20:
                continue
            per_ticker.append({
                "ticker": ticker,
                "samples": n,
                "accuracy": round(float(np.mean(pred[tmask] == truth[tmask])), 6),
            })

    return {
        "target": target,
        "samples": int(len(truth)),
        "fold_count": len(folds),
        "thresholds": aggregate,
        "robust_best": best,
        "per_ticker_at_robust_best": per_ticker,
        "folds": folds,
    }


def fmt(value):
    return "NA" if value is None else f"{value:.1%}"


def main():
    parser = argparse.ArgumentParser(description="Walk-forward validate Orion Premarket Directional Engine v4.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--targets", nargs="*", choices=PREMARKET_TARGETS, default=list(PREMARKET_TARGETS))
    parser.add_argument("--output", type=Path, default=Path("backend/data/models/premarket_directional_v4_walkforward.json"))
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    report = {"architecture": "premarket_directional_v4", "targets": {}}
    for target in args.targets:
        print(f"Validating v4 {target}...", flush=True)
        result = validate_target(frame, target)
        report["targets"][target] = result
        print(f"  samples={result['samples']} folds={result['fold_count']}")
        for row in result["thresholds"]:
            if not row["samples"]:
                continue
            s = row["fold_stability"]
            print(
                f"    edge>={row['edge_threshold']:.2f} dir>={row['direction_threshold']:.2f}: "
                f"n={row['samples']} coverage={row['coverage']:.1%} acc={fmt(row['accuracy'])} "
                f"UP={fmt(row['up_precision'])} DOWN={fmt(row['down_precision'])} "
                f"folds={s['positive_folds']}/{s['evaluable_folds']} median={fmt(s['median_accuracy'])}"
            )
            regime_text = []
            for regime in REGIMES:
                r = row["regimes"][regime]
                if r["samples"] >= 20:
                    regime_text.append(f"{regime}:n={r['samples']} acc={fmt(r['accuracy'])}")
            if regime_text:
                print("      " + " | ".join(regime_text))
        best = result["robust_best"]
        if best:
            s = best["fold_stability"]
            print(
                f"  ROBUST: edge>={best['edge_threshold']:.2f} dir>={best['direction_threshold']:.2f} "
                f"n={best['samples']} coverage={best['coverage']:.1%} acc={best['accuracy']:.1%} "
                f"median_fold={s['median_accuracy']:.1%} positive_folds={s['positive_folds']}/{s['evaluable_folds']}"
            )
        else:
            print("  ROBUST: none")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved v4 walk-forward report to {args.output}")


if __name__ == "__main__":
    main()
