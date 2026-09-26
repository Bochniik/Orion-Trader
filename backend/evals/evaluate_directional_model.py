"""Measure the deployed directional model without treating in-sample data as evidence.

This evaluator intentionally uses only settled live predictions linked to a saved
model. It never turns training/holdout summary fields into new observations.
Benchmarks that influence the headline comparison are computable at prediction
time; evaluation-set label statistics are retained only as diagnostics.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

CLASSES = ("DOWN", "NEUTRAL", "UP")
BUCKETS = ((0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01))
MIN_CALIBRATION_BUCKET_SIZE = 30
MIN_BOOTSTRAP_SAMPLE_SIZE = 30
BOOTSTRAP_RESAMPLES = 1000


def _percentile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _moving_block_mean_interval(values, *, seed):
    """Deterministic moving-block bootstrap interval for chronological losses."""
    count = len(values)
    if count < MIN_BOOTSTRAP_SAMPLE_SIZE:
        return {
            "status": "insufficient_sample",
            "sample_count": count,
            "minimum_sample_size": MIN_BOOTSTRAP_SAMPLE_SIZE,
            "lower": None,
            "upper": None,
            "block_size": None,
            "resamples": 0,
        }

    block_size = max(2, round(math.sqrt(count)))
    rng = random.Random(seed)
    means = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sampled = []
        while len(sampled) < count:
            start = rng.randrange(count)
            sampled.extend(values[(start + offset) % count] for offset in range(block_size))
        means.append(sum(sampled[:count]) / count)

    return {
        "status": "estimated",
        "sample_count": count,
        "minimum_sample_size": MIN_BOOTSTRAP_SAMPLE_SIZE,
        "lower": round(_percentile(means, 0.025), 8),
        "upper": round(_percentile(means, 0.975), 8),
        "block_size": block_size,
        "resamples": BOOTSTRAP_RESAMPLES,
        "method": "circular_moving_block_bootstrap",
    }


def _wilson_interval(successes, total, z=1.959963984540054):
    """Return a two-sided Wilson score interval for a binomial success rate."""
    if total <= 0:
        return None
    proportion = successes / total
    denominator = 1.0 + (z * z / total)
    centre = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt((proportion * (1.0 - proportion) / total) + (z * z / (4.0 * total * total)))
        / denominator
    )
    return {"lower": round(max(0.0, centre - margin), 8),
            "upper": round(min(1.0, centre + margin), 8)}


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _accuracy_baseline(rows, mode):
    actual = [row["actual_direction"] for row in rows]
    if not actual:
        return None
    if mode == "evaluation_set_oracle_majority":
        return max(Counter(actual).values()) / len(actual)
    if mode == "always_up":
        return sum(value == "UP" for value in actual) / len(actual)
    correct = 0
    usable = 0
    for row in rows:
        features = row.get("feature_snapshot") or {}
        value = _finite(features.get("return_1m"))
        if value is None:
            continue
        predicted = "UP" if value > 0 else "DOWN" if value < 0 else "NEUTRAL"
        usable += 1
        correct += predicted == row["actual_direction"]
    return (correct / usable if usable else None)


def _chronological_prior_baseline(rows, alpha=1.0):
    """Expanding class-prior benchmark using only outcomes known before each row.

    Laplace smoothing gives the first prediction a uniform prior and avoids
    peeking at the eventual evaluation-set class balance. Rows are expected in
    persistence order, which is the chronological settlement order used by the
    prediction store evaluator.
    """
    if not rows:
        return {
            "sample_count": 0,
            "multiclass_accuracy": None,
            "brier_score": None,
            "log_loss": None,
            "alpha": float(alpha),
        }

    counts = Counter()
    correct = 0
    brier_total = 0.0
    log_loss_total = 0.0
    used = 0

    for row in rows:
        actual = str(row.get("actual_direction") or "").upper()
        if actual not in CLASSES:
            continue
        denominator = sum(counts.values()) + float(alpha) * len(CLASSES)
        probs = {
            name: (counts[name] + float(alpha)) / denominator
            for name in CLASSES
        }
        predicted = max(CLASSES, key=lambda name: (probs[name], -CLASSES.index(name)))
        correct += predicted == actual
        brier_total += sum((probs[name] - (actual == name)) ** 2 for name in CLASSES)
        log_loss_total += -math.log(max(1e-12, probs[actual]))
        used += 1
        counts[actual] += 1

    if not used:
        return {
            "sample_count": 0,
            "multiclass_accuracy": None,
            "brier_score": None,
            "log_loss": None,
            "alpha": float(alpha),
        }
    return {
        "sample_count": used,
        "multiclass_accuracy": round(correct / used, 8),
        "brier_score": round(brier_total / used, 8),
        "log_loss": round(log_loss_total / used, 8),
        "alpha": float(alpha),
    }


def _valid_rows(rows):
    valid = []
    rejected = 0
    for row in rows:
        actual = str(row.get("actual_direction") or "").upper()
        probs = [_finite(row.get(f"p_{name.lower()}")) for name in CLASSES]
        if actual not in CLASSES or any(value is None or value < 0 for value in probs):
            rejected += 1
            continue
        total = sum(probs)
        if total <= 0 or abs(total - 1.0) > 1e-6:
            rejected += 1
            continue
        item = dict(row)
        item["actual_direction"] = actual
        valid.append(item)
    return valid, rejected


def _metrics(rows, include_groups=True):
    rows, rejected = _valid_rows(rows)
    if not rows:
        return {"sample_count": 0, "rejected_malformed_rows": rejected,
                "directional_accuracy": None, "multiclass_accuracy": None,
                "baseline_accuracy": None, "brier_score": None, "log_loss": None,
                "score_uncertainty": {
                    "brier_score_ci_95": _moving_block_mean_interval([], seed=1729),
                    "log_loss_ci_95": _moving_block_mean_interval([], seed=2718),
                },
                "calibration_error": None, "maximum_calibration_error": None,
                "calibration_sample_count": 0, "calibration_coverage": None,
                "calibration_min_bucket_size": MIN_CALIBRATION_BUCKET_SIZE,
                "class_distribution": {}, "confidence_buckets": [],
                "by_direction": {}, "by_horizon": {},
                "baselines": {"chronological_prior": _chronological_prior_baseline([])}}
    actual = [row["actual_direction"] for row in rows]
    probs = [[float(row[f"p_{name.lower()}"]) for name in CLASSES] for row in rows]
    predicted = [CLASSES[max(range(3), key=lambda i: values[i])] for values in probs]
    multiclass = sum(p == a for p, a in zip(predicted, actual)) / len(rows)
    directional_rows = [(p, a, v) for p, a, v in zip(predicted, actual, probs)
                        if p != "NEUTRAL" and a != "NEUTRAL"]
    directional_accuracy = (sum(p == a for p, a, _ in directional_rows) / len(directional_rows)
                            if directional_rows else None)
    brier_losses = [sum((v[i] - (a == CLASSES[i])) ** 2 for i in range(3))
                    for v, a in zip(probs, actual)]
    log_losses = [-math.log(max(1e-12, v[CLASSES.index(a)]))
                  for v, a in zip(probs, actual)]
    brier = sum(brier_losses) / len(rows)
    log_loss = sum(log_losses) / len(rows)
    confidence = [max(v) for v in probs]
    calibration_error = 0.0
    maximum_calibration_error = 0.0
    calibration_sample_count = 0
    buckets = []
    for lower, upper in BUCKETS:
        selected = [(c, p == a) for c, p, a in zip(confidence, predicted, actual)
                    if lower <= c < upper]
        if not selected:
            continue
        mean_conf = sum(c for c, _ in selected) / len(selected)
        successes = sum(ok for _, ok in selected)
        success = successes / len(selected)
        bucket_error = abs(mean_conf - success)
        calibration_error += bucket_error * len(selected) / len(rows)
        maximum_calibration_error = max(maximum_calibration_error, bucket_error)
        calibration_sample_count += len(selected)
        buckets.append({"lower": lower, "upper": min(1.0, upper),
                        "count": len(selected), "mean_predicted_probability": round(mean_conf, 8),
                        "observed_success_rate": round(success, 8),
                        "absolute_calibration_error": round(bucket_error, 8),
                        "observed_success_ci_95": _wilson_interval(successes, len(selected)),
                        "reliability": ("estimated" if len(selected) >= MIN_CALIBRATION_BUCKET_SIZE
                                        else "insufficient_sample")})

    chronological = _chronological_prior_baseline(rows)

    def grouped(key):
        groups = defaultdict(list)
        for row in rows:
            groups[str(key(row) or "unknown")].append(row)
        return {name: _metrics(group, include_groups=False) for name, group in sorted(groups.items())}

    return {
        "sample_count": len(rows),
        "rejected_malformed_rows": rejected,
        "directional_accuracy": round(directional_accuracy, 8) if directional_accuracy is not None else None,
        "multiclass_accuracy": round(multiclass, 8),
        "baseline_accuracy": chronological["multiclass_accuracy"],
        "baselines": {
            "chronological_prior": chronological,
            "always_up_accuracy": round(_accuracy_baseline(rows, "always_up"), 8),
            "previous_return_accuracy": _accuracy_baseline(rows, "previous_return"),
            "evaluation_set_oracle_majority_accuracy": round(_accuracy_baseline(rows, "evaluation_set_oracle_majority"), 8),
            "evaluation_set_oracle_majority_use": "diagnostic_only_not_a_deployable_baseline",
        },
        "brier_score": round(brier, 8),
        "brier_improvement_vs_chronological_prior": round(chronological["brier_score"] - brier, 8),
        "log_loss": round(log_loss, 8),
        "score_uncertainty": {
            "brier_score_ci_95": _moving_block_mean_interval(brier_losses, seed=1729),
            "log_loss_ci_95": _moving_block_mean_interval(log_losses, seed=2718),
        },
        "log_loss_improvement_vs_chronological_prior": round(chronological["log_loss"] - log_loss, 8),
        "calibration_error": round(calibration_error, 8),
        "maximum_calibration_error": round(maximum_calibration_error, 8),
        "calibration_sample_count": calibration_sample_count,
        "calibration_coverage": round(calibration_sample_count / len(rows), 8),
        "calibration_min_bucket_size": MIN_CALIBRATION_BUCKET_SIZE,
        "class_distribution": dict(Counter(actual)),
        "confidence_buckets": buckets,
        "by_direction": grouped(lambda row: row.get("model_direction") or max(CLASSES, key=lambda n: row[f"p_{n.lower()}"])) if include_groups else {},
        "by_horizon": grouped(lambda row: row.get("horizon")) if include_groups else {},
    }


def load_settled_predictions(database_path):
    path = Path(database_path)
    if not path.exists():
        return [], {"database_exists": False, "model_runs": 0, "live_predictions": 0, "settled_predictions": 0}
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        model_runs = db.execute("SELECT COUNT(*) FROM predictive_model_runs").fetchone()[0] if "predictive_model_runs" in tables else 0
        total = db.execute("SELECT COUNT(*) FROM live_predictions").fetchone()[0] if "live_predictions" in tables else 0
        rows = db.execute("SELECT * FROM live_predictions WHERE outcome_status='settled' ORDER BY id").fetchall() if "live_predictions" in tables else []
    parsed = []
    for row in rows:
        item = dict(row)
        try:
            result = json.loads(item.get("result_json") or "{}")
            features = json.loads(item.get("feature_json") or "{}")
        except json.JSONDecodeError:
            continue
        item.update(result)
        item["feature_snapshot"] = features
        parsed.append(item)
    return parsed, {"database_exists": True, "model_runs": model_runs,
                    "live_predictions": total, "settled_predictions": len(parsed)}


def evaluate(database_path):
    rows, inventory = load_settled_predictions(database_path)
    metrics = _metrics(rows)
    calibration = {"status": "not_evaluable", "reason": "No persisted raw and calibrated probability pairs are available."}
    if rows:
        calibration = {"status": "not_evaluable", "reason": "The prediction store persists calibrated probabilities but not raw pre-temperature probabilities."}
    return {
        "report_version": "orion-directional-validation-v2",
        "status": "evaluable" if metrics["sample_count"] else "not_evaluable",
        "data_inventory": inventory,
        "out_of_sample_definition": "Settled live predictions linked to a saved model; no training or calibration rows are counted.",
        "benchmark_semantics": (
            "Headline baseline metrics use an expanding Laplace-smoothed class prior computed only from outcomes "
            "available before each evaluated prediction. Evaluation-set majority accuracy is diagnostic only because "
            "using the final holdout class balance as a deployable benchmark would leak future labels into the baseline."
        ),
        "metrics": metrics,
        "temperature_calibration": calibration,
        "conclusion": "No measurable predictive value can be established from this repository because zero truly out-of-sample settled predictions are available." if not metrics["sample_count"] else "Evaluate only with the leakage-safe metrics above; reliability requires a materially sized chronological holdout.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="backend/data/orion.db")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = evaluate(args.database)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
