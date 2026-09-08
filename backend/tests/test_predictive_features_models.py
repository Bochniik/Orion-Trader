import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.services.predictive_features import (
    FEATURE_SCHEMA,
    build_intraday_feature_frame,
    build_training_samples,
    feature_schema_contract,
)
from app.services.predictive_models import predict_probabilities, train_predictive_model


def intraday_frame(rows=240):
    index = pd.date_range("2026-08-24 13:30", periods=rows, freq="min", tz="UTC")
    close = pd.Series(100 + np.sin(np.arange(rows) / 8) + np.arange(rows) * 0.01, index=index)
    return pd.DataFrame({
        "Open": close - 0.05,
        "High": close + 0.2,
        "Low": close - 0.2,
        "Close": close,
        "Volume": 100_000 + (np.arange(rows) % 30) * 1_000,
    }, index=index)


def test_historical_features_do_not_change_when_future_rows_are_mutated():
    source = intraday_frame()
    original = build_intraday_feature_frame(source)
    mutated = source.copy()
    mutated.iloc[180:, mutated.columns.get_loc("Close")] *= 4
    mutated.iloc[180:, mutated.columns.get_loc("High")] *= 4
    changed = build_intraday_feature_frame(mutated)

    pd.testing.assert_frame_equal(original.iloc[:180], changed.iloc[:180])
    assert original["return_30s"].isna().all()
    assert feature_schema_contract()["resolution_contract"].startswith("Unsupported sub-minute")


def test_training_targets_are_strictly_after_feature_cutoff_and_do_not_fake_30s():
    features = build_intraday_feature_frame(intraday_frame())
    samples = build_training_samples("AAPL", features, spread_bps=4)

    assert samples
    assert "30s" not in {item["horizon"] for item in samples}
    assert all(pd.Timestamp(item["outcome_timestamp"]) > pd.Timestamp(item["feature_cutoff"]) for item in samples)
    assert {item["actual_direction"] for item in samples} <= {"UP", "DOWN", "NEUTRAL"}
    assert all(item["neutral_threshold"] >= 0.0003 for item in samples)


def synthetic_samples(rows=360):
    samples = []
    for index in range(rows):
        direction = ("DOWN", "NEUTRAL", "UP")[index % 3]
        features = {
            name: math.sin(index / (position + 3)) * 0.02
            for position, name in enumerate(FEATURE_SCHEMA)
        }
        features["return_1m"] = (-0.01, 0.0, 0.01)[index % 3]
        samples.append({
            "symbol": "TEST",
            "timestamp": f"2026-01-01T{index // 60:02d}:{index % 60:02d}:00+00:00",
            "outcome_timestamp": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index + 1)).isoformat(),
            "horizon": "1m",
            "actual_direction": direction,
            "actual_return": (-0.01, 0.0, 0.01)[index % 3],
            "features": features,
        })
    return samples


def test_models_use_chronological_calibration_and_return_valid_probabilities():
    artifact = train_predictive_model(synthetic_samples(), name="Test baseline")
    horizon = artifact["horizons"]["1m"]
    probabilities = predict_probabilities(horizon, synthetic_samples(1)[0]["features"])

    assert artifact["random_split_used"] is False
    assert artifact["neural_network_used"] is False
    assert horizon["calibration"]["method"] == "held-out temperature scaling"
    assert len(horizon["walk_forward_folds"]) == 3
    assert horizon["training_window"]["train_end"] < horizon["training_window"]["holdout_start"]
    assert sum(probabilities[key] for key in ("P_UP", "P_DOWN", "P_NEUTRAL")) == 1
    assert artifact["horizons"]["30s"]["probabilities_available"] is False


def test_purging_protects_every_split_across_simultaneous_symbols():
    samples = synthetic_samples()
    samples += [{**sample, "symbol": "SECOND"} for sample in samples]
    artifact = train_predictive_model(samples)
    horizon = artifact["horizons"]["1m"]
    window = horizon["training_window"]
    assert artifact["validation_contract"] == "purged-cross-symbol-v2"
    assert window["train_outcome_end"] < window["calibration_start"]
    assert window["calibration_outcome_end"] < window["holdout_start"]
    for fold in horizon["walk_forward_folds"]:
        assert fold["train_outcome_end"] < fold["test_start"]
        assert fold["test_outcome_end"] < window["holdout_start"]


def test_long_overlapping_labels_cannot_pass_a_chronological_sort_alone():
    samples = synthetic_samples()
    for sample in samples:
        sample["outcome_timestamp"] = "2026-01-03T00:00:00+00:00"
    artifact = train_predictive_model(samples)
    assert artifact["horizons"]["1m"]["status"] == "insufficient_purged_data"
