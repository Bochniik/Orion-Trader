from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from premarket_directional_v4_common import PREMARKET_TARGETS
from premarket_directional_v5_common import fit_hybrid_model, prepare_v5_frame
from validate_premarket_directional_v5_walkforward import THRESHOLDS


MIN_CALIBRATION_EVENTS = 20
PROBABILITY_EPSILON = 1e-12
CONFIDENCE_BUCKETS = (
    (0.50, 0.60, "50-60"),
    (0.60, 0.70, "60-70"),
    (0.70, 0.80, "70-80"),
    (0.80, 0.90, "80-90"),
    (0.90, 1.00, "90-100"),
)


def gate_event_rows(
    frame: pd.DataFrame,
    predicted_return: np.ndarray,
    p_up: np.ndarray,
    *,
    normalized_move_threshold: float,
    direction_confidence_threshold: float,
) -> pd.DataFrame:
    """Return at most one actionable event per ticker/session_date.

    The earliest actionable snapshot is kept. This approximates a live policy
    that enters on the first qualifying signal and prevents repeated snapshots
    from the same ticker-day inflating the effective sample size.
    """
    if frame.empty:
        return frame.iloc[0:0].copy()

    work = frame.copy().reset_index(drop=True)
    sigma = work["expected_sigma_pct"].to_numpy(dtype=float)
    actual = work["future_return_pct"].to_numpy(dtype=float)
    predicted_return = np.asarray(predicted_return, dtype=float)
    p_up = np.asarray(p_up, dtype=float)

    predicted_norm = np.abs(predicted_return) / np.maximum(sigma, 1e-9)
    confidence = np.maximum(p_up, 1.0 - p_up)
    regression_up = predicted_return > 0
    classifier_up = p_up >= 0.5
    agreement = regression_up == classifier_up
    actionable = (
        agreement
        & (predicted_norm >= float(normalized_move_threshold))
        & (confidence >= float(direction_confidence_threshold))
    )

    work["predicted_return_pct"] = predicted_return
    work["direction_confidence"] = confidence
    work["predicted_norm"] = predicted_norm
    work["predicted_up"] = regression_up
    work["signed_return_pct"] = actual * np.where(regression_up, 1.0, -1.0)
    work["direction_correct"] = (
        np.where(actual > 0, 1.0, -1.0)
        == np.where(regression_up, 1.0, -1.0)
    )
    work = work.loc[actionable].copy()
    if work.empty:
        return work

    work = work.sort_values(["session_date", "ticker", "snapshot_at"])
    return (
        work.groupby(["session_date", "ticker"], sort=False, as_index=False)
        .first()
        .sort_values(["session_date", "snapshot_at", "ticker"])
        .reset_index(drop=True)
    )


def summarize_events(events: pd.DataFrame, denominator_ticker_days: int) -> dict:
    if events.empty:
        return {
            "events": 0,
            "coverage": 0.0,
            "directional_accuracy": None,
            "mean_signed_return_pct": None,
            "median_signed_return_pct": None,
            "positive_trade_rate": None,
            "mean_direction_confidence": None,
            "mean_predicted_abs_return_pct": None,
            "regimes": {},
        }

    regimes = {}
    for regime, part in events.groupby("regime"):
        regimes[str(regime)] = {
            "events": int(len(part)),
            "accuracy": round(float(part["direction_correct"].mean()), 6),
            "mean_signed_return_pct": round(float(part["signed_return_pct"].mean()), 6),
        }

    return {
        "events": int(len(events)),
        "coverage": round(float(len(events) / max(denominator_ticker_days, 1)), 6),
        "directional_accuracy": round(float(events["direction_correct"].mean()), 6),
        "mean_signed_return_pct": round(float(events["signed_return_pct"].mean()), 6),
        "median_signed_return_pct": round(float(events["signed_return_pct"].median()), 6),
        "positive_trade_rate": round(float((events["signed_return_pct"] > 0).mean()), 6),
        "mean_direction_confidence": round(float(events["direction_confidence"].mean()), 6),
        "mean_predicted_abs_return_pct": round(float(events["predicted_return_pct"].abs().mean()), 6),
        "regimes": regimes,
    }


def summarize_probability_quality(
    frame: pd.DataFrame,
    p_up: np.ndarray,
    *,
    baseline_probability,
) -> dict:
    """Measure directional probability quality without using the trade gate.

    The baseline probability must come from information available before the
    evaluated rows (the training prevalence in walk-forward validation).  This
    makes Brier/log-loss comparisons honest and keeps gate selection separate
    from the question of whether the classifier probabilities have predictive
    value at all.
    """
    if frame.empty:
        return {
            "samples": 0,
            "unique_ticker_days": 0,
            "up_rate": None,
            "accuracy": None,
            "brier": None,
            "log_loss": None,
            "baseline_probability_up": None,
            "baseline_accuracy": None,
            "baseline_brier": None,
            "baseline_log_loss": None,
            "brier_improvement": None,
            "log_loss_improvement": None,
            "confidence_buckets": {},
        }

    probabilities = np.asarray(p_up, dtype=float)
    if probabilities.ndim != 1 or len(probabilities) != len(frame):
        raise ValueError("p_up must contain exactly one probability per evaluated row")
    if not np.isfinite(probabilities).all():
        raise ValueError("p_up contains non-finite probabilities")

    probabilities = np.clip(probabilities, PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON)
    actual = frame["direction_up"].to_numpy(dtype=int)

    baseline = np.asarray(baseline_probability, dtype=float)
    if baseline.ndim == 0:
        baseline = np.full(len(frame), float(baseline), dtype=float)
    if baseline.ndim != 1 or len(baseline) != len(frame):
        raise ValueError("baseline_probability must be scalar or match the evaluated row count")
    if not np.isfinite(baseline).all():
        raise ValueError("baseline_probability contains non-finite values")
    baseline = np.clip(baseline, PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON)

    predicted_up = probabilities >= 0.5
    correct = predicted_up == actual.astype(bool)
    confidence = np.maximum(probabilities, 1.0 - probabilities)

    brier = float(np.mean((probabilities - actual) ** 2))
    log_loss = float(
        -np.mean(
            actual * np.log(probabilities)
            + (1 - actual) * np.log(1.0 - probabilities)
        )
    )
    baseline_brier = float(np.mean((baseline - actual) ** 2))
    baseline_log_loss = float(
        -np.mean(
            actual * np.log(baseline)
            + (1 - actual) * np.log(1.0 - baseline)
        )
    )
    baseline_predicted_up = baseline >= 0.5

    buckets = {}
    for lower, upper, label in CONFIDENCE_BUCKETS:
        if upper == 1.0:
            mask = (confidence >= lower) & (confidence <= upper)
        else:
            mask = (confidence >= lower) & (confidence < upper)
        count = int(mask.sum())
        if count == 0:
            continue
        bucket_accuracy = float(np.mean(correct[mask]))
        bucket_confidence = float(np.mean(confidence[mask]))
        buckets[label] = {
            "samples": count,
            "accuracy": round(bucket_accuracy, 6),
            "mean_confidence": round(bucket_confidence, 6),
            "calibration_gap": round(bucket_confidence - bucket_accuracy, 6),
        }

    unique_ticker_days = int(
        frame[["session_date", "ticker"]].drop_duplicates().shape[0]
        if {"session_date", "ticker"}.issubset(frame.columns)
        else len(frame)
    )

    return {
        "samples": int(len(frame)),
        "unique_ticker_days": unique_ticker_days,
        "up_rate": round(float(np.mean(actual)), 6),
        "accuracy": round(float(np.mean(correct)), 6),
        "brier": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "baseline_probability_up": round(float(np.mean(baseline)), 6),
        "baseline_accuracy": round(float(np.mean(baseline_predicted_up == actual.astype(bool))), 6),
        "baseline_brier": round(baseline_brier, 6),
        "baseline_log_loss": round(baseline_log_loss, 6),
        "brier_improvement": round(baseline_brier - brier, 6),
        "log_loss_improvement": round(baseline_log_loss - log_loss, 6),
        "confidence_buckets": buckets,
    }


def select_gate_on_calibration(calibration: pd.DataFrame, predicted_return, p_up):
    ticker_days = int(calibration[["session_date", "ticker"]].drop_duplicates().shape[0])
    candidates = []
    for move_threshold, confidence_threshold in THRESHOLDS:
        events = gate_event_rows(
            calibration,
            predicted_return,
            p_up,
            normalized_move_threshold=move_threshold,
            direction_confidence_threshold=confidence_threshold,
        )
        summary = summarize_events(events, ticker_days)
        candidates.append({
            "normalized_move_threshold": move_threshold,
            "direction_confidence_threshold": confidence_threshold,
            **summary,
        })

    eligible = [
        row for row in candidates
        if row["events"] >= MIN_CALIBRATION_EVENTS
        and row["directional_accuracy"] is not None
        and row["directional_accuracy"] >= 0.52
        and row["mean_signed_return_pct"] is not None
        and row["mean_signed_return_pct"] > 0
    ]
    selected = max(
        eligible,
        key=lambda row: (
            row["directional_accuracy"],
            row["mean_signed_return_pct"],
            row["events"],
        ),
        default=None,
    )
    return selected, candidates


def validate_target(
    frame: pd.DataFrame,
    target: str,
    *,
    min_train_days=40,
    calibration_days=10,
    test_days=5,
):
    work = prepare_v5_frame(frame, target)
    dates = sorted(work["session_date"].unique())
    if len(dates) < min_train_days + calibration_days + test_days:
        raise ValueError(f"{target}: not enough dates ({len(dates)})")

    folds = []
    pooled_events = []
    pooled_probability_rows = []
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
        train_up_rate = float(train["direction_up"].mean())
        cal_return, cal_p_up = model.predict(calibration)
        selected, calibration_candidates = select_gate_on_calibration(
            calibration,
            cal_return,
            cal_p_up,
        )

        test_return, test_p_up = model.predict(test)
        directional_quality = summarize_probability_quality(
            test,
            test_p_up,
            baseline_probability=train_up_rate,
        )
        probability_rows = test[["ticker", "session_date", "direction_up"]].copy()
        probability_rows["p_up"] = test_p_up
        probability_rows["baseline_probability_up"] = train_up_rate
        pooled_probability_rows.append(probability_rows)

        test_ticker_days = int(test[["session_date", "ticker"]].drop_duplicates().shape[0])
        if selected is None:
            test_events = test.iloc[0:0].copy()
            test_summary = summarize_events(test_events, test_ticker_days)
        else:
            test_events = gate_event_rows(
                test,
                test_return,
                test_p_up,
                normalized_move_threshold=selected["normalized_move_threshold"],
                direction_confidence_threshold=selected["direction_confidence_threshold"],
            )
            test_summary = summarize_events(test_events, test_ticker_days)
            if not test_events.empty:
                tagged = test_events.copy()
                tagged["fold"] = fold_index
                pooled_events.append(tagged)

        folds.append({
            "fold": fold_index,
            "test_first": str(test_dates_fold[0]),
            "test_last": str(test_dates_fold[-1]),
            "test_ticker_days": test_ticker_days,
            "train_up_rate": round(train_up_rate, 6),
            "direction_temperature": round(float(model.direction_temperature), 6),
            "directional_quality": directional_quality,
            "selected_gate": selected,
            "calibration_candidates": calibration_candidates,
            "test": test_summary,
        })
        fold_index += 1
        test_start = test_end

    total_test_ticker_days = int(sum(fold["test_ticker_days"] for fold in folds))
    total_events = int(sum(fold["test"]["events"] for fold in folds))

    if pooled_events:
        pooled = pd.concat(pooled_events, ignore_index=True)
        pooled_summary = summarize_events(pooled, total_test_ticker_days)
    else:
        pooled_summary = summarize_events(pd.DataFrame(), total_test_ticker_days)

    if pooled_probability_rows:
        pooled_probability = pd.concat(pooled_probability_rows, ignore_index=True)
        pooled_directional_quality = summarize_probability_quality(
            pooled_probability,
            pooled_probability["p_up"].to_numpy(dtype=float),
            baseline_probability=pooled_probability["baseline_probability_up"].to_numpy(dtype=float),
        )
    else:
        pooled_directional_quality = summarize_probability_quality(
            pd.DataFrame(),
            np.array([], dtype=float),
            baseline_probability=0.5,
        )

    evaluable = [fold for fold in folds if fold["test"]["events"] > 0]
    fold_accuracies = [fold["test"]["directional_accuracy"] for fold in evaluable]
    fold_signed = [fold["test"]["mean_signed_return_pct"] for fold in evaluable]

    return {
        "target": target,
        "fold_count": len(folds),
        "evaluable_folds": len(evaluable),
        "positive_accuracy_folds": int(sum(1 for value in fold_accuracies if value > 0.5)),
        "positive_signed_return_folds": int(sum(1 for value in fold_signed if value > 0)),
        "median_fold_accuracy": round(float(np.median(fold_accuracies)), 6) if fold_accuracies else None,
        "min_fold_accuracy": round(float(np.min(fold_accuracies)), 6) if fold_accuracies else None,
        "events": total_events,
        "unique_test_ticker_days": total_test_ticker_days,
        "event_coverage": round(total_events / max(total_test_ticker_days, 1), 6),
        "directional_quality": pooled_directional_quality,
        "pooled": pooled_summary,
        "folds": folds,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Leakage-resistant event-level validation for Orion Premarket Directional Engine v5. "
            "Thresholds are selected only on each fold's calibration period and each ticker-day "
            "can contribute at most one test trade. Directional probabilities are also scored "
            "against the train-only prevalence baseline with Brier/log-loss diagnostics."
        )
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--targets",
        nargs="*",
        choices=PREMARKET_TARGETS,
        default=list(PREMARKET_TARGETS),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/models/premarket_directional_v5_event_nested.json"),
    )
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    report = {
        "dataset": str(args.dataset),
        "rows": int(len(frame)),
        "policy": (
            "threshold selected on calibration only; earliest actionable snapshot; "
            "max one trade per ticker-day; probability metrics compared with train-only prevalence baseline"
        ),
        "targets": {},
    }

    for target in args.targets:
        print(f"Validating event-level nested v5 {target}...", flush=True)
        result = validate_target(frame, target)
        report["targets"][target] = result
        pooled = result["pooled"]
        quality = result["directional_quality"]
        acc = "NA" if pooled["directional_accuracy"] is None else f"{pooled['directional_accuracy']:.1%}"
        signed = "NA" if pooled["mean_signed_return_pct"] is None else f"{pooled['mean_signed_return_pct']:+.4f}%"
        median = "NA" if result["median_fold_accuracy"] is None else f"{result['median_fold_accuracy']:.1%}"
        minimum = "NA" if result["min_fold_accuracy"] is None else f"{result['min_fold_accuracy']:.1%}"
        print(
            f"  events={result['events']} ticker_days={result['unique_test_ticker_days']} "
            f"coverage={result['event_coverage']:.1%} acc={acc} signed={signed}"
        )
        if quality["samples"]:
            print(
                f"  probability quality: n={quality['samples']} acc={quality['accuracy']:.1%} "
                f"brier={quality['brier']:.6f} vs {quality['baseline_brier']:.6f} "
                f"logloss={quality['log_loss']:.6f} vs {quality['baseline_log_loss']:.6f}"
            )
        print(
            f"  folds: accuracy>50% {result['positive_accuracy_folds']}/{result['evaluable_folds']} "
            f"signed>0 {result['positive_signed_return_folds']}/{result['evaluable_folds']} "
            f"median={median} min={minimum}"
        )
        if pooled["regimes"]:
            print("  regimes:")
            for regime, row in pooled["regimes"].items():
                print(
                    f"    {regime}: n={row['events']} acc={row['accuracy']:.1%} "
                    f"signed={row['mean_signed_return_pct']:+.4f}%"
                )

        for fold in result["folds"]:
            gate = fold["selected_gate"]
            test = fold["test"]
            quality = fold["directional_quality"]
            quality_text = (
                f"brier_delta={quality['brier_improvement']:+.6f} "
                f"logloss_delta={quality['log_loss_improvement']:+.6f}"
            )
            if gate is None:
                print(
                    f"    fold {fold['fold']}: no calibration-approved gate; {quality_text}"
                )
                continue

            test_acc = (
                "NA"
                if test["directional_accuracy"] is None
                else f"{test['directional_accuracy']:.1%}"
            )
            test_signed = (
                "NA"
                if test["mean_signed_return_pct"] is None
                else f"{test['mean_signed_return_pct']:+.4f}%"
            )
            print(
                f"    fold {fold['fold']}: selected move>={gate['normalized_move_threshold']:.2f}sigma "
                f"conf>={gate['direction_confidence_threshold']:.2f}; "
                f"test n={test['events']} acc={test_acc} signed={test_signed}; {quality_text}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved event-level nested v5 report to {args.output}")


if __name__ == "__main__":
    main()
