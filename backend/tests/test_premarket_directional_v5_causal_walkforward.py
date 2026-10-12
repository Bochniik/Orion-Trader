from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "validate_premarket_directional_v5_walkforward.py"
SPEC = importlib.util.spec_from_file_location("validate_premarket_directional_v5_walkforward", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class _FakeModel:
    def predict(self, frame):
        return np.zeros(len(frame)), np.full(len(frame), 0.6)


def _frame(days=70, rows_per_day=20):
    dates = pd.date_range("2026-01-02", periods=days, freq="D").date.astype(str)
    return pd.DataFrame(
        {
            "session_date": np.repeat(dates, rows_per_day),
            "feature": np.arange(days * rows_per_day),
        }
    )


def test_v5_validator_selects_threshold_on_validation_and_scores_one_on_test(monkeypatch):
    calls = []

    monkeypatch.setattr(MODULE, "prepare_v5_frame", lambda frame, target: frame.copy())
    monkeypatch.setattr(MODULE, "fit_hybrid_model", lambda train, calibration: _FakeModel())

    def fake_evaluate(frame, predicted_return, p_up, *, normalized_move_threshold, direction_confidence_threshold):
        threshold = (normalized_move_threshold, direction_confidence_threshold)
        calls.append((tuple(sorted(frame["session_date"].unique())), threshold))
        is_selected = threshold == (0.20, 0.55)
        return {
            "samples": int(len(frame)),
            "directional_accuracy": 0.61 if is_selected else 0.51,
            "mean_signed_return_pct": 0.1 if is_selected else -0.1,
        }

    monkeypatch.setattr(MODULE, "evaluate_gate", fake_evaluate)
    result = MODULE.validate_target(_frame(), "5m")

    assert result["contract"] == "orion-premarket-v5-causal-walk-forward-v1"
    assert result["protocol"]["threshold_selection_block"] == "validation"
    assert result["protocol"]["probability_calibration_block"] == "calibration"
    assert result["protocol"]["final_scoring_block"] == "untouched_test"
    assert result["protocol"]["shuffling_allowed"] is False
    assert result["fold_count"] == 2
    assert len(calls) == result["fold_count"] * (len(MODULE.THRESHOLDS) + 1)

    for fold in result["folds"]:
        assert fold["train_last"] < fold["validation_first"]
        assert fold["validation_last"] < fold["calibration_first"]
        assert fold["calibration_last"] < fold["test_first"]
        assert fold["selected_on_validation"]["normalized_move_threshold"] == 0.20
        assert fold["selected_on_validation"]["direction_confidence_threshold"] == 0.55
        assert fold["untouched_test"]["normalized_move_threshold"] == 0.20
        assert fold["untouched_test"]["direction_confidence_threshold"] == 0.55

    assert result["untouched_test"]["samples"] == 200
    assert result["robust_research_result"] is False


def test_v5_validator_fails_closed_without_four_distinct_time_blocks(monkeypatch):
    monkeypatch.setattr(MODULE, "prepare_v5_frame", lambda frame, target: frame.copy())
    with __import__("pytest").raises(ValueError, match="not enough dates"):
        MODULE.validate_target(_frame(days=64), "5m")
