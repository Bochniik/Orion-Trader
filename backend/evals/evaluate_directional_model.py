"""Measure the deployed directional model without treating in-sample data as evidence.

This evaluator intentionally uses only settled live predictions linked to a saved
model.  It never turns training/holdout summary fields into new observations.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

CLASSES = ("DOWN", "NEUTRAL", "UP")
BUCKETS = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01))


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _baseline(rows, mode):
    actual = [row["actual_direction"] for row in rows]
    if not actual:
        return None
    if mode == "majority":
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


def _metrics(rows, include_groups=True):
    if not rows:
        return {"sample_count": 0, "directional_accuracy": None,
                "multiclass_accuracy": None, "baseline_accuracy": None,
                "brier_score": None, "log_loss": None,
                "calibration_error": None, "class_distribution": {},
                "confidence_buckets": [], "by_direction": {}, "by_horizon": {}}
    actual = [str(row.get("actual_direction") or "").upper() for row in rows]
    probs = [[float(row[f"p_{name.lower()}"]) for name in CLASSES] for row in rows]
    predicted = [CLASSES[max(range(3), key=lambda i: values[i])] for values in probs]
    multiclass = sum(p == a for p, a in zip(predicted, actual)) / len(rows)
    directional_rows = [(p, a, v) for p, a, v in zip(predicted, actual, probs)
                        if p != "NEUTRAL" and a != "NEUTRAL"]
    directional_accuracy = (sum(p == a for p, a, _ in directional_rows) / len(directional_rows)
                            if directional_rows else None)
    brier = sum(sum((v[i] - (a == CLASSES[i])) ** 2 for i in range(3))
                for v, a in zip(probs, actual)) / len(rows)
    log_loss = sum(-math.log(max(1e-12, v[CLASSES.index(a)]))
                   for v, a in zip(probs, actual) if a in CLASSES) / len(rows)
    confidence = [max(v) for v in probs]
    calibration_error = 0.0
    buckets = []
    for lower, upper in BUCKETS:
        selected = [(c, p == a) for c, p, a in zip(confidence, predicted, actual)
                    if lower <= c < upper]
        if not selected:
            continue
        mean_conf = sum(c for c, _ in selected) / len(selected)
        success = sum(ok for _, ok in selected) / len(selected)
        calibration_error += abs(mean_conf - success) * len(selected) / len(rows)
        buckets.append({"lower": lower, "upper": min(1.0, upper),
                        "count": len(selected), "mean_predicted_probability": round(mean_conf, 8),
                        "observed_success_rate": round(success, 8)})
    def grouped(key):
        groups = defaultdict(list)
        for row in rows:
            groups[str(key(row) or "unknown")].append(row)
        return {name: _metrics(group, include_groups=False) for name, group in sorted(groups.items())}
    return {
        "sample_count": len(rows),
        "directional_accuracy": round(directional_accuracy, 8) if directional_accuracy is not None else None,
        "multiclass_accuracy": round(multiclass, 8),
        "baseline_accuracy": round(_baseline(rows, "majority"), 8),
        "baselines": {"majority": round(_baseline(rows, "majority"), 8),
                      "always_up": round(_baseline(rows, "always_up"), 8),
                      "previous_return": _baseline(rows, "previous_return")},
        "brier_score": round(brier, 8), "log_loss": round(log_loss, 8),
        "calibration_error": round(calibration_error, 8),
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
        "report_version": "orion-directional-validation-v1",
        "status": "evaluable" if rows else "not_evaluable",
        "data_inventory": inventory,
        "out_of_sample_definition": "Settled live predictions linked to a saved model; no training or calibration rows are counted.",
        "metrics": metrics,
        "temperature_calibration": calibration,
        "conclusion": "No measurable predictive value can be established from this repository because zero truly out-of-sample settled predictions are available." if not rows else "Evaluate only with the metrics above; reliability requires a materially sized chronological holdout.",
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
