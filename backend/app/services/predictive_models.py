"""Interpretable, deterministic multi-class predictive baselines.

The implementation intentionally avoids neural networks and random splits.  A
multinomial logistic model and gradient-boosted decision-stump model are fitted
chronologically, calibrated on a later block, and evaluated on the final block.
"""

import hashlib
import json
import math
from datetime import datetime, timezone

import numpy as np

from app.services.predictive_features import MODEL_FEATURES


CLASSES = ("DOWN", "NEUTRAL", "UP")
CLASS_INDEX = {name: index for index, name in enumerate(CLASSES)}

SUPPORTED_HORIZONS = ("30s", "1m", "3m", "5m", "15m", "30m", "1h", "1D")


def _stable_hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dataset_hash(samples):
    material = [
        {
            "symbol": sample.get("symbol"),
            "timestamp": sample.get("timestamp"),
            "outcome_timestamp": sample.get("outcome_timestamp"),
            "horizon": sample.get("horizon"),
            "actual_direction": sample.get("actual_direction"),
            "actual_return": sample.get("actual_return"),
            "features": {
                feature: (sample.get("features") or {}).get(feature)
                for feature in MODEL_FEATURES
            },
        }
        for sample in sorted(
            samples,
            key=lambda sample: (
                str(sample.get("timestamp") or ""),
                str(sample.get("symbol") or ""),
                str(sample.get("horizon") or ""),
            ),
        )
    ]
    return _stable_hash(material)


def _softmax(logits):
    values = np.asarray(logits, dtype=float)
    values = values - np.max(values, axis=1, keepdims=True)
    exponent = np.exp(np.clip(values, -50, 50))
    return exponent / np.maximum(exponent.sum(axis=1, keepdims=True), 1e-12)


def _json_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 10) if math.isfinite(number) else None


def _matrix(samples, medians=None, scales=None):
    raw = np.asarray([
        [
            float(sample.get("features", {}).get(feature))
            if sample.get("features", {}).get(feature) is not None else np.nan
            for feature in MODEL_FEATURES
        ]
        for sample in samples
    ], dtype=float)
    if medians is None:
        medians = np.asarray([
            np.median(column[np.isfinite(column)]) if np.isfinite(column).any() else 0.0
            for column in raw.T
        ])
    else:
        medians = np.asarray(medians, dtype=float)
    filled = np.where(np.isfinite(raw), raw, medians)
    if scales is None:
        scales = np.std(filled, axis=0)
        scales = np.where(np.isfinite(scales) & (scales > 1e-12), scales, 1.0)
    else:
        scales = np.asarray(scales, dtype=float)
    standardized = np.clip((filled - medians) / scales, -12, 12)
    return standardized, medians, scales


def _fit_logistic(x, y, *, epochs=60, learning_rate=0.06, regularization=0.01):
    rows, columns = x.shape
    weights = np.zeros((columns, len(CLASSES)), dtype=float)
    counts = np.bincount(y, minlength=len(CLASSES)).astype(float) + 1
    bias = np.log(counts / counts.sum())
    one_hot = np.eye(len(CLASSES))[y]
    for epoch in range(max(20, int(epochs))):
        probabilities = _softmax(x @ weights + bias)
        error = probabilities - one_hot
        rate = learning_rate / math.sqrt(1 + epoch / 30)
        weights -= rate * ((x.T @ error) / rows + regularization * weights)
        bias -= rate * error.mean(axis=0)
    return {"weights": weights, "bias": bias}


def _predict_logistic(model, x):
    return _softmax(x @ model["weights"] + model["bias"])


def _fit_boosted_stumps(x, y, *, iterations=6, learning_rate=0.12):
    counts = np.bincount(y, minlength=len(CLASSES)).astype(float) + 1
    base = np.log(counts / counts.sum())
    logits = np.tile(base, (len(x), 1))
    stumps = []
    one_hot = np.eye(len(CLASSES))[y]
    quantiles = np.asarray([0.25, 0.5, 0.75])
    thresholds = np.quantile(x, quantiles, axis=0)
    for _ in range(max(1, int(iterations))):
        residuals = one_hot - _softmax(logits)
        round_stumps = []
        for class_index in range(len(CLASSES)):
            residual = residuals[:, class_index]
            correlations = np.abs(x.T @ residual)
            candidate_features = np.argsort(correlations)[-min(8, x.shape[1]):]
            best = None
            for feature_index in candidate_features:
                values = x[:, feature_index]
                for threshold in thresholds[:, feature_index]:
                    left = values <= threshold
                    if left.sum() < 10 or (~left).sum() < 10:
                        continue
                    left_value = float(residual[left].mean())
                    right_value = float(residual[~left].mean())
                    predicted = np.where(left, left_value, right_value)
                    loss = float(np.mean((residual - predicted) ** 2))
                    candidate = (loss, int(feature_index), float(threshold), left_value, right_value)
                    if best is None or candidate[0] < best[0]:
                        best = candidate
            if best is None:
                best = (float(np.mean(residual ** 2)), 0, 0.0, 0.0, 0.0)
            _, feature_index, threshold, left_value, right_value = best
            update = np.where(x[:, feature_index] <= threshold, left_value, right_value)
            logits[:, class_index] += learning_rate * update
            round_stumps.append({
                "class_index": class_index,
                "feature_index": feature_index,
                "threshold": threshold,
                "left_value": left_value,
                "right_value": right_value,
            })
        stumps.extend(round_stumps)
    return {"base": base, "learning_rate": learning_rate, "stumps": stumps}


def _predict_boosted_stumps(model, x):
    logits = np.tile(np.asarray(model["base"], dtype=float), (len(x), 1))
    rate = float(model["learning_rate"])
    for stump in model["stumps"]:
        feature = int(stump["feature_index"])
        update = np.where(
            x[:, feature] <= float(stump["threshold"]),
            float(stump["left_value"]),
            float(stump["right_value"]),
        )
        logits[:, int(stump["class_index"])] += rate * update
    return _softmax(logits)


def _fit_pair(samples):
    x, medians, scales = _matrix(samples)
    y = np.asarray([CLASS_INDEX[sample["actual_direction"]] for sample in samples], dtype=int)
    logistic = _fit_logistic(x, y)
    boosted = _fit_boosted_stumps(x, y)
    return logistic, boosted, medians, scales


def _pair_probabilities(logistic, boosted, x):
    return (_predict_logistic(logistic, x) + _predict_boosted_stumps(boosted, x)) / 2


def _temperature(probabilities, temperature):
    logits = np.log(np.clip(probabilities, 1e-9, 1)) / float(temperature)
    return _softmax(logits)


def _select_temperature(probabilities, y):
    one_hot = np.eye(len(CLASSES))[y]
    best = (float("inf"), 1.0)
    for temperature in np.linspace(0.55, 2.5, 40):
        calibrated = _temperature(probabilities, temperature)
        brier = float(np.mean(np.sum((calibrated - one_hot) ** 2, axis=1)))
        if brier < best[0]:
            best = (brier, float(temperature))
    return best[1]


def _class_metrics(y, probabilities):
    predicted = probabilities.argmax(axis=1)
    one_hot = np.eye(len(CLASSES))[y]
    accuracy = float(np.mean(predicted == y)) if len(y) else 0
    precision, recall, f1 = {}, {}, {}
    confusion = np.zeros((len(CLASSES), len(CLASSES)), dtype=int)
    for actual, guess in zip(y, predicted):
        confusion[int(actual), int(guess)] += 1
    for index, name in enumerate(CLASSES):
        true_positive = int(np.sum((predicted == index) & (y == index)))
        false_positive = int(np.sum((predicted == index) & (y != index)))
        false_negative = int(np.sum((predicted != index) & (y == index)))
        precision[name] = true_positive / (true_positive + false_positive) if true_positive + false_positive else None
        recall[name] = true_positive / (true_positive + false_negative) if true_positive + false_negative else None
        if precision[name] is not None and recall[name] is not None and precision[name] + recall[name] > 0:
            f1[name] = 2 * precision[name] * recall[name] / (precision[name] + recall[name])
        else:
            f1[name] = None
    valid_recalls = [value for value in recall.values() if value is not None]
    balanced_accuracy = float(np.mean(valid_recalls)) if valid_recalls else None
    brier = float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))
    selected = np.clip(probabilities[np.arange(len(y)), y], 1e-12, 1.0)
    log_loss = float(-np.mean(np.log(selected))) if len(y) else None
    confidence = probabilities.max(axis=1)
    correct = (predicted == y).astype(float)
    buckets = []
    ece = 0.0
    for lower in np.arange(0, 1, 0.1):
        upper = min(1.0, lower + 0.1)
        mask = (confidence >= lower) & (confidence < upper if upper < 1 else confidence <= upper)
        if not mask.any():
            continue
        bucket_accuracy = float(correct[mask].mean())
        bucket_confidence = float(confidence[mask].mean())
        weight = float(mask.mean())
        ece += abs(bucket_accuracy - bucket_confidence) * weight
        buckets.append({
            "lower": round(float(lower), 2), "upper": round(float(upper), 2),
            "count": int(mask.sum()), "accuracy": round(bucket_accuracy, 6),
            "average_confidence": round(bucket_confidence, 6),
        })
    prevalence = np.bincount(y, minlength=len(CLASSES)) / max(1, len(y))
    baseline_accuracy = float(prevalence.max())
    return {
        "observations": int(len(y)), "accuracy": round(accuracy, 6),
        "balanced_accuracy": _json_number(balanced_accuracy),
        "baseline_majority_accuracy": round(baseline_accuracy, 6),
        "precision": {name: _json_number(value) for name, value in precision.items()},
        "recall": {name: _json_number(value) for name, value in recall.items()},
        "f1": {name: _json_number(value) for name, value in f1.items()},
        "confusion_matrix": {
            "labels": list(CLASSES),
            "rows_actual_columns_predicted": confusion.tolist(),
        },
        "brier_score": round(brier, 8),
        "log_loss": _json_number(log_loss),
        "expected_calibration_error": round(ece, 8),
        "calibration_buckets": buckets,
        "class_prevalence": {
            name: round(float(prevalence[index]), 6)
            for index, name in enumerate(CLASSES)
        },
    }


def _simulated_after_cost_edge(samples, probabilities, cost_bps=5.0):
    returns = np.asarray([float(sample["actual_return"]) for sample in samples])
    predicted = probabilities.argmax(axis=1)
    directional = predicted != CLASS_INDEX["NEUTRAL"]
    if not directional.any():
        return None
    signed = np.where(predicted == CLASS_INDEX["UP"], returns, -returns)
    after_cost = signed[directional] - float(cost_bps) / 10_000
    return float(after_cost.mean() * 10_000)


def _serialize_pair(logistic, boosted):
    return {
        "logistic_regression": {
            "weights": np.asarray(logistic["weights"]).round(10).tolist(),
            "bias": np.asarray(logistic["bias"]).round(10).tolist(),
        },
        "gradient_boosted_stumps": {
            "base": np.asarray(boosted["base"]).round(10).tolist(),
            "learning_rate": boosted["learning_rate"],
            "stumps": [
                {key: _json_number(value) if key not in {"class_index", "feature_index"} else int(value)
                 for key, value in stump.items()}
                for stump in boosted["stumps"]
            ],
        },
    }


def _deserialize_pair(artifact):
    logistic_data = artifact["models"]["logistic_regression"]
    boosted_data = artifact["models"]["gradient_boosted_stumps"]
    logistic = {
        "weights": np.asarray(logistic_data["weights"], dtype=float),
        "bias": np.asarray(logistic_data["bias"], dtype=float),
    }
    boosted = {
        "base": np.asarray(boosted_data["base"], dtype=float),
        "learning_rate": float(boosted_data["learning_rate"]),
        "stumps": boosted_data["stumps"],
    }
    return logistic, boosted


def _bounded_samples(samples, maximum=6_000):
    ordered = sorted(samples, key=lambda sample: (sample["timestamp"], sample["symbol"]))
    if len(ordered) <= maximum:
        return ordered
    indexes = np.linspace(0, len(ordered) - 1, maximum, dtype=int)
    return [ordered[index] for index in indexes]


def _purge_before(samples, boundary):
    # Remove labels whose future window reaches the next partition, across ALL
    # symbols. A chronological sort alone does not prevent label leakage.
    return [s for s in samples if s["timestamp"] < boundary and s["outcome_timestamp"] < boundary]


def train_horizon_model(samples, horizon, *, checkpoint=lambda: None):
    checkpoint()
    horizon_samples = _bounded_samples([
        sample for sample in samples if sample.get("horizon") == horizon
    ])
    if len(horizon_samples) < 120:
        return {
            "horizon": horizon, "status": "insufficient_training_data",
            "sample_count": len(horizon_samples), "required_samples": 120,
            "probabilities_available": False, "reliable": False,
        }

    total = len(horizon_samples)
    train_end = max(72, int(total * 0.55))
    validation_end = max(train_end + 24, int(total * 0.70))
    calibration_end = max(validation_end + 24, int(total * 0.85))
    calibration_end = min(calibration_end, total - 24)
    validation_end = min(validation_end, calibration_end - 24)
    train_end = min(train_end, validation_end - 24)

    train_boundary = horizon_samples[train_end]["timestamp"]
    calibration_boundary = horizon_samples[validation_end]["timestamp"]
    test_boundary = horizon_samples[calibration_end]["timestamp"]

    train = _purge_before(horizon_samples[:train_end], train_boundary)
    validation = _purge_before(
        [s for s in horizon_samples[train_end:validation_end] if s["timestamp"] >= train_boundary],
        calibration_boundary,
    )
    calibration = _purge_before(
        [s for s in horizon_samples[validation_end:calibration_end] if s["timestamp"] >= calibration_boundary],
        test_boundary,
    )
    test = [s for s in horizon_samples if s["timestamp"] >= test_boundary]

    if len(train) < 72 or len(validation) < 24 or len(calibration) < 24 or len(test) < 24:
        return {
            "horizon": horizon, "status": "insufficient_purged_data",
            "sample_count": total, "probabilities_available": False, "reliable": False,
            "split_counts": {
                "train": len(train), "validation": len(validation),
                "calibration": len(calibration), "test": len(test),
            },
        }

    logistic, boosted, medians, scales = _fit_pair(train)

    validation_x, _, _ = _matrix(validation, medians, scales)
    validation_y = np.asarray([CLASS_INDEX[item["actual_direction"]] for item in validation])
    validation_probabilities = _pair_probabilities(logistic, boosted, validation_x)
    validation_metrics = _class_metrics(validation_y, validation_probabilities)

    calibration_x, _, _ = _matrix(calibration, medians, scales)
    calibration_y = np.asarray([CLASS_INDEX[item["actual_direction"]] for item in calibration])
    raw_calibration = _pair_probabilities(logistic, boosted, calibration_x)
    temperature = _select_temperature(raw_calibration, calibration_y)

    test_x, _, _ = _matrix(test, medians, scales)
    test_y = np.asarray([CLASS_INDEX[item["actual_direction"]] for item in test])
    raw_test_probabilities = _pair_probabilities(logistic, boosted, test_x)
    calibrated_test_probabilities = _temperature(raw_test_probabilities, temperature)
    raw_test_metrics = _class_metrics(test_y, raw_test_probabilities)
    metrics = _class_metrics(test_y, calibrated_test_probabilities)
    after_cost_edge = _simulated_after_cost_edge(test, calibrated_test_probabilities)
    metrics["simulated_after_cost_edge_bps"] = _json_number(after_cost_edge)

    folds = []
    for train_fraction, test_fraction in ((0.3, 0.1), (0.45, 0.1), (0.55, 0.1)):
        checkpoint()
        fold_train_end = int(total * train_fraction)
        fold_test_end = min(validation_end, fold_train_end + max(24, int(total * test_fraction)))
        if fold_train_end <= 0 or fold_test_end <= fold_train_end:
            continue
        boundary = horizon_samples[fold_train_end]["timestamp"]
        fold_train = _purge_before(horizon_samples[:fold_train_end], boundary)
        fold_test = _purge_before(horizon_samples[fold_train_end:fold_test_end], calibration_boundary)
        if len(fold_train) < 72 or len(fold_test) < 24:
            continue
        fold_logistic, fold_boosted, fold_medians, fold_scales = _fit_pair(fold_train)
        fold_x, _, _ = _matrix(fold_test, fold_medians, fold_scales)
        fold_y = np.asarray([CLASS_INDEX[item["actual_direction"]] for item in fold_test])
        fold_probabilities = _pair_probabilities(fold_logistic, fold_boosted, fold_x)
        fold_metrics = _class_metrics(fold_y, fold_probabilities)
        folds.append({
            "train_end": fold_train[-1]["timestamp"],
            "train_outcome_end": max(s["outcome_timestamp"] for s in fold_train),
            "test_start": fold_test[0]["timestamp"],
            "test_end": fold_test[-1]["timestamp"],
            "test_outcome_end": max(s["outcome_timestamp"] for s in fold_test),
            **{key: fold_metrics[key] for key in (
                "observations", "accuracy", "balanced_accuracy", "brier_score",
                "log_loss", "expected_calibration_error"
            )},
        })

    reliable = bool(
        metrics["observations"] >= 500
        and len(folds) >= 3
        and metrics["brier_score"] < 0.65
        and metrics["expected_calibration_error"] <= 0.10
        and metrics["accuracy"] >= metrics["baseline_majority_accuracy"]
        and after_cost_edge is not None and after_cost_edge > 0
    )

    return_stats = {}
    for class_name in CLASSES:
        values = [
            float(sample["actual_return"])
            for sample in train if sample["actual_direction"] == class_name
        ]
        return_stats[class_name] = {
            "count": len(values),
            "mean": _json_number(np.mean(values)) if values else None,
            "mean_absolute": _json_number(np.mean(np.abs(values))) if values else None,
        }

    return {
        "horizon": horizon,
        "status": "validated_baseline" if reliable else "experimental_baseline",
        "sample_count": total,
        "sample_count_before_cap": len([
            sample for sample in samples if sample.get("horizon") == horizon
        ]),
        "probabilities_available": True,
        "reliable": reliable,
        "features": list(MODEL_FEATURES),
        "feature_set_hash": _stable_hash(list(MODEL_FEATURES)),
        "dataset_hash": _dataset_hash(horizon_samples),
        "medians": np.asarray(medians).round(10).tolist(),
        "scales": np.asarray(scales).round(10).tolist(),
        "models": _serialize_pair(logistic, boosted),
        "validation": validation_metrics,
        "calibration": {
            "method": "held-out temperature scaling",
            "temperature": round(temperature, 8),
            "observations": len(calibration),
        },
        "test_before_calibration": raw_test_metrics,
        "holdout": metrics,
        "untouched_test": metrics,
        "walk_forward_folds": folds,
        "conditional_return_statistics": return_stats,
        "split_counts": {
            "train": len(train), "validation": len(validation),
            "calibration": len(calibration), "test": len(test),
        },
        "training_window": {
            "start": horizon_samples[0]["timestamp"],
            "train_end": train[-1]["timestamp"],
            "train_outcome_end": max(s["outcome_timestamp"] for s in train),
            "validation_start": validation[0]["timestamp"],
            "validation_end": validation[-1]["timestamp"],
            "validation_outcome_end": max(s["outcome_timestamp"] for s in validation),
            "calibration_start": calibration[0]["timestamp"],
            "calibration_end": calibration[-1]["timestamp"],
            "calibration_outcome_end": max(s["outcome_timestamp"] for s in calibration),
            "holdout_start": test[0]["timestamp"],
            "test_start": test[0]["timestamp"],
            "end": horizon_samples[-1]["outcome_timestamp"],
        },
        "split_contract": "train -> validation -> calibration -> untouched test; label windows purged before every later block",
        "reliability_message": (
            "Passed the minimum out-of-sample baseline gates. Continue shadow validation."
            if reliable else
            "Experimental only: one or more sample, calibration, baseline or after-cost gates failed."
        ),
    }


def train_predictive_model(samples, *, name="Orion baseline", checkpoint=lambda: None):
    horizons = sorted({sample.get("horizon") for sample in samples if sample.get("horizon")})
    artifacts = {horizon: train_horizon_model(samples, horizon, checkpoint=checkpoint) for horizon in horizons}
    # Keep unsupported horizons visible rather than silently omitting them.
    for horizon in SUPPORTED_HORIZONS:
        artifacts.setdefault(horizon, {
            "horizon": horizon, "status": "insufficient_training_data",
            "sample_count": 0, "required_samples": 120,
            "probabilities_available": False, "reliable": False,
        })
    return {
        "version": "orion-predictive-model-v3",
        "validation_contract": "four-stage-purged-cross-symbol-v3",
        "name": str(name)[:80],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classes": list(CLASSES),
        "model_family": "calibrated ensemble: multinomial logistic regression + gradient-boosted decision stumps",
        "compute_contract": "At most 6000 chronological samples per horizon; deterministic even-spacing preserves the full time span.",
        "split_contract": "chronological train/validation/calibration/untouched-test; overlapping outcome windows purged across symbols; walk-forward folds end before calibration and final test",
        "random_split_used": False,
        "neural_network_used": False,
        "dataset_hash": _dataset_hash(samples),
        "feature_set_hash": _stable_hash(list(MODEL_FEATURES)),
        "random_seed": None,
        "horizons": artifacts,
        "reliable_horizons": [
            horizon for horizon, artifact in artifacts.items() if artifact.get("reliable")
        ],
        "safety_boundary": "Research probabilities only; the artifact has no broker or order capability.",
    }


def predict_probabilities(horizon_artifact, feature_snapshot):
    if not horizon_artifact or not horizon_artifact.get("probabilities_available"):
        raise ValueError("This horizon has no trained probability baseline")
    sample = {"features": feature_snapshot.get("features") or feature_snapshot}
    x, _, _ = _matrix(
        [sample], horizon_artifact["medians"], horizon_artifact["scales"]
    )
    logistic, boosted = _deserialize_pair(horizon_artifact)
    logistic_probabilities = _predict_logistic(logistic, x)
    boosted_probabilities = _predict_boosted_stumps(boosted, x)
    raw = (logistic_probabilities + boosted_probabilities) / 2
    calibrated = _temperature(
        raw, horizon_artifact["calibration"]["temperature"]
    )[0]
    values = {
        class_name: round(float(calibrated[index]), 8)
        for index, class_name in enumerate(CLASSES)
    }
    # Floating-point rounding is corrected without changing ordering.
    difference = round(1 - sum(values.values()), 8)
    values[CLASSES[int(np.argmax(calibrated))]] = round(
        values[CLASSES[int(np.argmax(calibrated))]] + difference, 8
    )
    standardized = x[0]
    logistic_weights = np.asarray(logistic["weights"])
    predicted_class = int(np.argmax(calibrated))
    contributions = standardized * logistic_weights[:, predicted_class]
    strongest = np.argsort(np.abs(contributions))[-5:][::-1]
    return {
        "P_DOWN": values["DOWN"],
        "P_NEUTRAL": values["NEUTRAL"],
        "P_UP": values["UP"],
        "predicted_class": CLASSES[predicted_class],
        "strongest_logistic_contributors": [
            {
                "feature": MODEL_FEATURES[index],
                "contribution": round(float(contributions[index]), 8),
                "direction": "supports" if contributions[index] >= 0 else "contradicts",
            }
            for index in strongest
        ],
        "calibration_status": horizon_artifact["status"],
        "model_reliable": bool(horizon_artifact.get("reliable")),
        "raw_probabilities": {
            "P_DOWN": round(float(raw[0, CLASS_INDEX["DOWN"]]), 8),
            "P_NEUTRAL": round(float(raw[0, CLASS_INDEX["NEUTRAL"]]), 8),
            "P_UP": round(float(raw[0, CLASS_INDEX["UP"]]), 8),
        },
        "logistic_probabilities": {
            "P_DOWN": round(float(logistic_probabilities[0, CLASS_INDEX["DOWN"]]), 8),
            "P_NEUTRAL": round(float(logistic_probabilities[0, CLASS_INDEX["NEUTRAL"]]), 8),
            "P_UP": round(float(logistic_probabilities[0, CLASS_INDEX["UP"]]), 8),
        },
        "boosted_stump_probabilities": {
            "P_DOWN": round(float(boosted_probabilities[0, CLASS_INDEX["DOWN"]]), 8),
            "P_NEUTRAL": round(float(boosted_probabilities[0, CLASS_INDEX["NEUTRAL"]]), 8),
            "P_UP": round(float(boosted_probabilities[0, CLASS_INDEX["UP"]]), 8),
        },
        "calibration_temperature": float(horizon_artifact["calibration"]["temperature"]),
    }
