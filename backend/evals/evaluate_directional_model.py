"""Measure the deployed directional model without treating in-sample data as evidence.

This evaluator intentionally uses only settled live predictions linked to a saved
model. It never turns training/holdout summary fields into new observations.
Benchmarks that influence the headline comparison are computable at prediction
time; evaluation-set label statistics are retained only as diagnostics.
"""
from __future__ import annotations

import argparse
import hashlib
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


def _improvement_interval(values, *, seed):
    """Add a fail-closed verdict to a paired baseline-minus-model interval."""
    interval = _moving_block_mean_interval(values, seed=seed)
    if interval["status"] != "estimated":
        interval["verdict"] = "insufficient_sample"
    elif interval["lower"] > 0.0:
        interval["verdict"] = "better"
    elif interval["upper"] < 0.0:
        interval["verdict"] = "worse"
    else:
        interval["verdict"] = "inconclusive"
    interval["positive_means"] = "model_has_lower_loss_than_chronological_prior"
    return interval


def _combined_improvement_verdict(brier_interval, log_loss_interval):
    """Require both proper scoring rules to agree before a directional verdict."""
    metric_verdicts = {
        "brier_score": brier_interval["verdict"],
        "log_loss": log_loss_interval["verdict"],
    }
    verdicts = tuple(metric_verdicts.values())
    if "insufficient_sample" in verdicts:
        verdict = "insufficient_sample"
    elif all(value == "better" for value in verdicts):
        verdict = "better"
    elif all(value == "worse" for value in verdicts):
        verdict = "worse"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "metric_verdicts": metric_verdicts,
        "policy": "brier_and_log_loss_must_agree",
    }


def _aggregate_horizon_verdict(by_horizon):
    """Prevent one strong horizon from hiding weak or unverified horizons."""
    horizon_verdicts = {
        horizon: metrics["score_improvement_uncertainty"][
            "overall_probabilistic_verdict"
        ]["verdict"]
        for horizon, metrics in sorted(by_horizon.items())
    }
    verdicts = tuple(horizon_verdicts.values())
    if not verdicts or "insufficient_sample" in verdicts:
        verdict = "insufficient_sample"
    elif all(value == "better" for value in verdicts):
        verdict = "better"
    elif all(value == "worse" for value in verdicts):
        verdict = "worse"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "horizon_verdicts": horizon_verdicts,
        "policy": "all_horizons_must_agree",
    }


def _aggregate_direction_verdict(by_direction):
    """Prevent a dominant predicted class from hiding weak minority classes."""
    direction_verdicts = {
        direction: metrics["score_improvement_uncertainty"][
            "overall_probabilistic_verdict"
        ]["verdict"]
        for direction, metrics in sorted(by_direction.items())
    }
    verdicts = tuple(direction_verdicts.values())
    if not verdicts or "insufficient_sample" in verdicts:
        verdict = "insufficient_sample"
    elif all(value == "better" for value in verdicts):
        verdict = "better"
    elif all(value == "worse" for value in verdicts):
        verdict = "worse"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "direction_verdicts": direction_verdicts,
        "policy": "all_predicted_directions_must_agree",
    }


def _extract_liquidity_tier(row):
    """Read only an explicitly persisted A-D tier; never infer one at evaluation."""
    features = row.get("feature_snapshot") or {}
    liquidity = features.get("liquidity")
    candidates = (
        row.get("liquidity_tier"),
        features.get("liquidity_tier"),
        features.get("liquidity_bucket"),
        liquidity.get("tier") if isinstance(liquidity, dict) else None,
    )
    for value in candidates:
        normalized = str(value or "").strip().upper()
        if normalized in {"A", "B", "C", "D"}:
            return normalized
    return None


def _aggregate_liquidity_verdict(by_tier, *, total_count, missing_count):
    """Fail closed when any settled row lacks an explicitly persisted tier."""
    tier_verdicts = {
        tier: metrics["score_improvement_uncertainty"][
            "overall_probabilistic_verdict"
        ]["verdict"]
        for tier, metrics in sorted(by_tier.items())
    }
    verdicts = tuple(tier_verdicts.values())
    if total_count <= 0 or missing_count > 0 or not verdicts:
        verdict = "insufficient_sample"
    elif "insufficient_sample" in verdicts:
        verdict = "insufficient_sample"
    elif all(value == "better" for value in verdicts):
        verdict = "better"
    elif all(value == "worse" for value in verdicts):
        verdict = "worse"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "tier_verdicts": tier_verdicts,
        "tier_coverage": round((total_count - missing_count) / total_count, 8)
                         if total_count else None,
        "missing_tier_count": missing_count,
        "policy": "all_rows_tiered_and_all_liquidity_tiers_must_agree",
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


def _chronological_prior_loss_series(rows, alpha=1.0):
    """Per-row expanding-prior losses aligned with chronological model losses."""
    counts = Counter()
    correct = 0
    brier_losses = []
    log_losses = []

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
        brier_losses.append(sum((probs[name] - (actual == name)) ** 2 for name in CLASSES))
        log_losses.append(-math.log(max(1e-12, probs[actual])))
        counts[actual] += 1

    return {
        "sample_count": len(brier_losses),
        "correct": correct,
        "brier_losses": brier_losses,
        "log_losses": log_losses,
    }


def _chronological_prior_baseline(rows, alpha=1.0):
    """Expanding class-prior benchmark using only outcomes known before each row."""
    series = _chronological_prior_loss_series(rows, alpha=alpha)
    used = series["sample_count"]
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
        "multiclass_accuracy": round(series["correct"] / used, 8),
        "brier_score": round(sum(series["brier_losses"]) / used, 8),
        "log_loss": round(sum(series["log_losses"]) / used, 8),
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
                "score_improvement_uncertainty": {
                    "brier_improvement_ci_95": _improvement_interval([], seed=3141),
                    "log_loss_improvement_ci_95": _improvement_interval([], seed=5772),
                    "overall_probabilistic_verdict": _combined_improvement_verdict(
                        _improvement_interval([], seed=3141),
                        _improvement_interval([], seed=5772),
                    ),
                },
                "calibration_error": None, "maximum_calibration_error": None,
                "calibration_sample_count": 0, "calibration_coverage": None,
                "calibration_min_bucket_size": MIN_CALIBRATION_BUCKET_SIZE,
                "class_distribution": {}, "confidence_buckets": [],
                "horizon_probabilistic_verdict": _aggregate_horizon_verdict({}),
                "direction_probabilistic_verdict": _aggregate_direction_verdict({}),
                "liquidity_probabilistic_verdict": _aggregate_liquidity_verdict(
                    {}, total_count=0, missing_count=0
                ),
                "by_direction": {}, "by_horizon": {}, "by_liquidity_tier": {},
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
    prior_losses = _chronological_prior_loss_series(rows)
    brier_improvements = [baseline - model for baseline, model in
                          zip(prior_losses["brier_losses"], brier_losses)]
    log_loss_improvements = [baseline - model for baseline, model in
                             zip(prior_losses["log_losses"], log_losses)]
    brier_improvement_interval = _improvement_interval(brier_improvements, seed=3141)
    log_loss_improvement_interval = _improvement_interval(log_loss_improvements, seed=5772)

    def grouped(key):
        groups = defaultdict(list)
        for row in rows:
            groups[str(key(row) or "unknown")].append(row)
        return {name: _metrics(group, include_groups=False) for name, group in sorted(groups.items())}

    by_direction = (grouped(lambda row: row.get("model_direction") or
                            max(CLASSES, key=lambda n: row[f"p_{n.lower()}"]))
                    if include_groups else {})
    by_horizon = grouped(lambda row: row.get("horizon")) if include_groups else {}
    liquidity_groups = defaultdict(list)
    missing_liquidity_tier = 0
    if include_groups:
        for row in rows:
            tier = _extract_liquidity_tier(row)
            if tier is None:
                missing_liquidity_tier += 1
            else:
                liquidity_groups[tier].append(row)
    by_liquidity_tier = {
        tier: _metrics(group, include_groups=False)
        for tier, group in sorted(liquidity_groups.items())
    }

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
        "score_improvement_uncertainty": {
            "brier_improvement_ci_95": brier_improvement_interval,
            "log_loss_improvement_ci_95": log_loss_improvement_interval,
            "overall_probabilistic_verdict": _combined_improvement_verdict(
                brier_improvement_interval, log_loss_improvement_interval
            ),
        },
        "log_loss_improvement_vs_chronological_prior": round(chronological["log_loss"] - log_loss, 8),
        "calibration_error": round(calibration_error, 8),
        "maximum_calibration_error": round(maximum_calibration_error, 8),
        "calibration_sample_count": calibration_sample_count,
        "calibration_coverage": round(calibration_sample_count / len(rows), 8),
        "calibration_min_bucket_size": MIN_CALIBRATION_BUCKET_SIZE,
        "class_distribution": dict(Counter(actual)),
        "confidence_buckets": buckets,
        "horizon_probabilistic_verdict": (_aggregate_horizon_verdict(by_horizon)
                                            if include_groups else None),
        "direction_probabilistic_verdict": (_aggregate_direction_verdict(by_direction)
                                              if include_groups else None),
        "liquidity_probabilistic_verdict": (
            _aggregate_liquidity_verdict(
                by_liquidity_tier,
                total_count=len(rows),
                missing_count=missing_liquidity_tier,
            ) if include_groups else None
        ),
        "by_direction": by_direction,
        "by_horizon": by_horizon,
        "by_liquidity_tier": by_liquidity_tier,
    }


def _stored_prediction_fingerprint(row):
    payload = json.dumps({
        "model_id": row.get("model_id"),
        "ticker": str(row.get("ticker") or "").upper(),
        "model_version": row.get("model_version"),
        "horizon": row.get("horizon"),
        "source_observation_timestamp": row.get("source_observation_timestamp"),
        "feature_json": row.get("feature_json"),
        "result_json": row.get("result_json"),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _registry_integrity(rows, columns):
    if not rows:
        return {"status": "empty", "verified_count": 0, "corrupted_count": 0,
                "unverifiable_count": 0, "policy": "fail_closed_no_backfill"}
    if "prediction_fingerprint" not in columns:
        return {"status": "unverifiable", "verified_count": 0, "corrupted_count": 0,
                "unverifiable_count": len(rows), "policy": "fail_closed_no_backfill"}
    verified = corrupted = unverifiable = 0
    for raw_row in rows:
        row = dict(raw_row)
        fingerprint = row.get("prediction_fingerprint")
        if not fingerprint:
            unverifiable += 1
        elif fingerprint == _stored_prediction_fingerprint(row):
            verified += 1
        else:
            corrupted += 1
    status = ("corrupted" if corrupted else
              "unverifiable" if unverifiable else "verified")
    return {"status": status, "verified_count": verified,
            "corrupted_count": corrupted, "unverifiable_count": unverifiable,
            "policy": "fail_closed_no_backfill"}


def load_settled_predictions(database_path):
    path = Path(database_path)
    if not path.exists():
        return [], {"database_exists": False, "model_runs": 0, "live_predictions": 0,
                    "settled_predictions": 0,
                    "registry_integrity": _registry_integrity([], set())}
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        model_runs = db.execute("SELECT COUNT(*) FROM predictive_model_runs").fetchone()[0] if "predictive_model_runs" in tables else 0
        total = db.execute("SELECT COUNT(*) FROM live_predictions").fetchone()[0] if "live_predictions" in tables else 0
        columns = ({row[1] for row in db.execute("PRAGMA table_info(live_predictions)")}
                   if "live_predictions" in tables else set())
        rows = db.execute("SELECT * FROM live_predictions WHERE outcome_status='settled' ORDER BY id").fetchall() if "live_predictions" in tables else []
    integrity = _registry_integrity(rows, columns)
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
                    "live_predictions": total, "settled_predictions": len(parsed),
                    "registry_integrity": integrity}


def _model_evidence_verdict(metrics, integrity):
    """Require registry integrity and agreement across every audited model slice."""
    if not metrics["sample_count"]:
        return {"verdict": "no_evidence", "reason": "no_settled_predictions"}
    if integrity["status"] != "verified":
        return {
            "verdict": "insufficient_evidence",
            "reason": "prediction_registry_integrity_not_verified",
            "registry_status": integrity["status"],
        }
    components = {
        "overall": metrics["score_improvement_uncertainty"][
            "overall_probabilistic_verdict"
        ]["verdict"],
        "horizons": metrics["horizon_probabilistic_verdict"]["verdict"],
        "directions": metrics["direction_probabilistic_verdict"]["verdict"],
        "liquidity_tiers": metrics["liquidity_probabilistic_verdict"]["verdict"],
    }
    values = tuple(components.values())
    if "insufficient_sample" in values:
        verdict = "insufficient_evidence"
        reason = "one_or_more_audited_slices_lack_evidence"
    elif all(value == "better" for value in values):
        verdict = "better"
        reason = "all_audited_slices_agree"
    elif all(value == "worse" for value in values):
        verdict = "worse"
        reason = "all_audited_slices_agree"
    else:
        verdict = "inconclusive"
        reason = "audited_slice_verdicts_do_not_agree"
    return {
        "verdict": verdict,
        "reason": reason,
        "registry_status": "verified",
        "component_verdicts": components,
        "policy": "integrity_and_all_audited_slices_must_agree",
    }


def evaluate(database_path):
    rows, inventory = load_settled_predictions(database_path)
    metrics = _metrics(rows)
    integrity = inventory["registry_integrity"]
    evidence_verdict = _model_evidence_verdict(metrics, integrity)
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
        "model_evidence_verdict": evidence_verdict,
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
