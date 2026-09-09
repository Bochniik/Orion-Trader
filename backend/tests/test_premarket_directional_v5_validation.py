from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from validate_premarket_directional_v5_event_nested import summarize_probability_quality


def _frame(labels):
    return pd.DataFrame(
        {
            "ticker": [f"T{i % 2}" for i in range(len(labels))],
            "session_date": pd.date_range("2026-01-01", periods=len(labels)).date,
            "direction_up": labels,
        }
    )


def test_probability_quality_rewards_informative_probabilities():
    frame = _frame([1, 1, 0, 0])
    probabilities = np.array([0.90, 0.80, 0.20, 0.10])

    result = summarize_probability_quality(
        frame,
        probabilities,
        baseline_probability=0.50,
    )

    assert result["samples"] == 4
    assert result["accuracy"] == 1.0
    assert result["brier"] < result["baseline_brier"]
    assert result["log_loss"] < result["baseline_log_loss"]
    assert result["brier_improvement"] > 0
    assert result["log_loss_improvement"] > 0
    assert result["confidence_buckets"]["80-90"]["samples"] == 1
    assert result["confidence_buckets"]["90-100"]["samples"] == 2


def test_probability_quality_uses_external_baseline_not_test_prevalence():
    frame = _frame([1, 1, 1, 0])
    probabilities = np.full(4, 0.60)

    result = summarize_probability_quality(
        frame,
        probabilities,
        baseline_probability=0.25,
    )

    assert result["up_rate"] == 0.75
    assert result["baseline_probability_up"] == 0.25
    assert result["baseline_accuracy"] == 0.25


def test_probability_quality_supports_fold_specific_baseline_vector():
    frame = _frame([1, 0, 1, 0])
    probabilities = np.array([0.70, 0.30, 0.80, 0.20])
    baseline = np.array([0.55, 0.55, 0.45, 0.45])

    result = summarize_probability_quality(
        frame,
        probabilities,
        baseline_probability=baseline,
    )

    assert result["baseline_probability_up"] == 0.50
    assert result["brier_improvement"] > 0


def test_probability_quality_rejects_invalid_probability_shape():
    frame = _frame([1, 0])

    with pytest.raises(ValueError, match="exactly one probability"):
        summarize_probability_quality(
            frame,
            np.array([0.60]),
            baseline_probability=0.50,
        )
