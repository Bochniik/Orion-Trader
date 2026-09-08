from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.services.premarket_hierarchical_runtime import (
    MODEL_VERSION,
    predict_gated_hierarchical_outlook,
)
from app.services.premarket_predictive_engine import FEATURE_NAMES


def _frame():
    index = pd.date_range("2026-09-04T12:00:00Z", periods=90, freq="1min")
    close = np.linspace(100.0, 101.5, len(index))
    return pd.DataFrame(
        {
            "Open": close - 0.05,
            "High": close + 0.10,
            "Low": close - 0.10,
            "Close": close,
            "Volume": np.full(len(index), 10000.0),
        },
        index=index,
    )


def _artifact(path: Path):
    n = len(FEATURE_NAMES)
    payload = {
        "model_version": MODEL_VERSION,
        "metadata": {"test": True},
        "targets": {
            "open_5m": {
                "feature_names": list(FEATURE_NAMES),
                "impute": [0.0] * n,
                "mean": [0.0] * n,
                "scale": [1.0] * n,
                "edge_stage": {
                    "weights": [0.0] * n,
                    "bias": 1.0,
                    "temperature": 1.0,
                },
                "direction_stage": {
                    "weights": [0.0] * n,
                    "bias": 1.0,
                    "temperature": 1.0,
                },
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_rejects_iex_domain(tmp_path):
    artifact = tmp_path / "model.json"
    _artifact(artifact)
    result = predict_gated_hierarchical_outlook(
        _frame(),
        previous_close=99.5,
        feed="iex",
        model_path=artifact,
    )
    assert result["available"] is False
    assert result["actionable"] is False
    assert result["reason"] == "training_feed_mismatch_requires_sip"


def test_sip_can_emit_open_5m_signal(tmp_path):
    artifact = tmp_path / "model.json"
    _artifact(artifact)
    result = predict_gated_hierarchical_outlook(
        _frame(),
        previous_close=99.5,
        feed="sip",
        model_path=artifact,
    )
    assert result["available"] is True
    signal = result["signals"]["open_5m"]
    assert signal["actionable"] is True
    assert signal["direction"] == "UP"
    assert signal["edge_probability"] > 0.55
    assert signal["direction_confidence"] > 0.55
