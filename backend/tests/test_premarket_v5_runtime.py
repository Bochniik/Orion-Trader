from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app.services.premarket_v5_runtime import (
    DEFAULT_PROVENANCE_PATH,
    MODEL_VERSION,
    PREMARKET_TARGETS,
    predict_premarket_v5_outlook,
)


def _frame():
    index = pd.date_range("2026-10-05T12:00:00Z", periods=76, freq="1min")
    base = np.linspace(100.0, 101.2, len(index))
    wave = np.sin(np.linspace(0.0, 8.0, len(index))) * 0.08
    close = base + wave
    return pd.DataFrame(
        {
            "Open": close - 0.03,
            "High": close + 0.08,
            "Low": close - 0.08,
            "Close": close,
            "Volume": np.linspace(8000.0, 18000.0, len(index)),
        },
        index=index,
    )


def test_default_deployed_v5_artifact_emits_research_forecasts():
    result = predict_premarket_v5_outlook(
        _frame(),
        previous_close=99.7,
        feed="sip",
        as_of=pd.Timestamp("2026-10-05T13:15:00Z"),
    )

    assert result["available"] is True
    assert result["actionable"] is False
    assert result["research_only"] is True
    assert result["forecast_scope"] == "premarket_short_horizon"
    assert result["model_version"] == MODEL_VERSION
    assert set(result["signals"]) == set(PREMARKET_TARGETS)
    assert len(result["model_artifact_sha256"]) == 64

    for target, signal in result["signals"].items():
        assert signal["research_only"] is True
        assert signal["actionable"] is False
        assert signal["forecast_scope"] == "premarket_short_horizon"
        assert "PREMARKET" in signal["window_label"]
        assert "OPEN" not in signal["window_label"]
        assert 0.0 <= signal["probability_up"] <= 1.0
        assert 0.0 <= signal["probability_down"] <= 1.0
        assert 0.5 <= signal["direction_confidence"] <= 1.0
        assert np.isfinite(signal["predicted_return_pct"])
        assert signal["test_metrics"] is not None
        assert signal["direction"] in {"UP", "DOWN", "NO_TRADE"}

    assert result["signals"]["premarket_30m"]["test_metrics"]["default_gate"]["directional_accuracy"] == 0.5


def test_v5_runtime_rejects_iex_for_model_inference():
    result = predict_premarket_v5_outlook(
        _frame(),
        previous_close=99.7,
        feed="iex",
        as_of=pd.Timestamp("2026-10-05T13:15:00Z"),
    )

    assert result["available"] is False
    assert result["actionable"] is False
    assert result["research_only"] is True
    assert result["reason"] == "training_feed_mismatch_requires_sip"
    assert result["signals"] == {}


def test_deployed_model_provenance_is_explicit_and_not_opening_eligible():
    provenance = json.loads(DEFAULT_PROVENANCE_PATH.read_text(encoding="utf-8"))

    assert provenance["source_workflow_run_id"] == 36711771100
    assert provenance["source_artifact_id"] == 11094555618
    assert provenance["source_artifact_digest"] == "sha256:52f0a11c2c631063224b4912ff523efc0820e0c6df01c26bb97fb49ab4327e0a"
    assert provenance["model_version"] == MODEL_VERSION
    assert provenance["training_rows_raw"] == 2545
    assert provenance["opening_forecast_eligible"] is False
    assert provenance["deployment_semantics"] == "research_only_premarket_short_horizon_forecast"
