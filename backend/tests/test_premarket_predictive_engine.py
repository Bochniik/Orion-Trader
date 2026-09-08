from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.services.premarket_predictive_engine import (
    FEATURE_NAMES,
    MODEL_VERSION,
    PremarketPredictiveRegistry,
    extract_predictive_features,
    predict_premarket_outlook,
)


def sample_frame():
    index = pd.date_range(
        "2026-09-08 12:00:00+00:00",
        periods=61,
        freq="1min",
    )
    close = np.linspace(10.0, 10.8, len(index))
    return pd.DataFrame(
        {
            "Open": close - 0.01,
            "High": close + 0.03,
            "Low": close - 0.03,
            "Close": close,
            "Volume": np.linspace(20_000, 90_000, len(index)),
        },
        index=index,
    )


def test_feature_snapshot_contains_multihorizon_momentum_without_future_data():
    frame = sample_frame()
    features = extract_predictive_features(frame, previous_close=9.8)

    assert tuple(features) == FEATURE_NAMES
    assert features["gap_pct"] > 0
    assert features["return_5m_pct"] > 0
    assert features["return_15m_pct"] > features["return_5m_pct"]
    assert features["return_30m_pct"] > features["return_15m_pct"]
    assert 0.0 <= features["range_location"] <= 1.0
    assert features["log_dollar_volume"] > 0


def test_missing_artifact_never_fabricates_probability(tmp_path):
    result = predict_premarket_outlook(
        sample_frame(),
        previous_close=9.8,
        model_path=tmp_path / "missing.json",
    )

    assert result["available"] is False
    assert result["reason"] == "trained_model_artifact_missing"
    assert result["forecasts"] == {}


def test_calibrated_artifact_returns_three_class_probabilities(tmp_path):
    n = len(FEATURE_NAMES)
    weights = np.zeros((3, n), dtype=float)
    weights[2, FEATURE_NAMES.index("return_5m_pct")] = 1.0
    weights[0, FEATURE_NAMES.index("return_5m_pct")] = -1.0

    artifact = {
        "model_version": MODEL_VERSION,
        "metadata": {"test_fixture": True},
        "targets": {
            "open_30m": {
                "feature_names": list(FEATURE_NAMES),
                "mean": [0.0] * n,
                "scale": [1.0] * n,
                "weights": weights.tolist(),
                "bias": [0.0, 0.0, 0.0],
                "temperature": 1.25,
                "metrics": {"test": {"samples": 1000}},
            }
        },
    }
    path = tmp_path / "model.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    registry = PremarketPredictiveRegistry(path)
    result = registry.predict(extract_predictive_features(sample_frame(), previous_close=9.8))

    assert result["available"] is True
    forecast = result["forecasts"]["open_30m"]
    total = (
        forecast["probability_down"]
        + forecast["probability_no_edge"]
        + forecast["probability_up"]
    )
    assert abs(total - 1.0) < 1e-5
    assert forecast["probability_up"] > forecast["probability_down"]
    assert forecast["calibrated"] is True
