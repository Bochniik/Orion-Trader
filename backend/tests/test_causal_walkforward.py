from datetime import timedelta

import pytest

from backend.evals.causal_walkforward import WalkForwardConfig, four_stage_walk_forward


def _rows(n=40):
    rows = []
    for i in range(n):
        rows.append({
            "symbol": "X",
            "timestamp": f"2026-01-01T00:{i:02d}:00+00:00",
            "outcome_timestamp": f"2026-01-01T00:{i+1:02d}:00+00:00",
        })
    return rows


def test_four_stage_split_is_ordered_and_untouched():
    folds = four_stage_walk_forward(_rows(), WalkForwardConfig(12, 6, 6, 6, 5))
    first = folds[0]
    assert first["status"] == "READY"
    assert max(r["outcome_timestamp"] for r in first["train"]) < min(r["timestamp"] for r in first["validation"])
    assert max(r["outcome_timestamp"] for r in first["validation"]) < min(r["timestamp"] for r in first["calibration"])
    assert max(r["outcome_timestamp"] for r in first["calibration"]) < min(r["timestamp"] for r in first["untouched_test"])


def test_rolling_window_is_bounded_while_expanding_grows():
    rows = _rows(50)
    rolling = four_stage_walk_forward(rows, WalkForwardConfig(10, 5, 5, 5, 5, mode="rolling", max_train=12))
    expanding = four_stage_walk_forward(rows, WalkForwardConfig(10, 5, 5, 5, 5, mode="expanding"))
    assert len(rolling[-1]["train"]) <= 12
    assert len(expanding[-1]["train"]) > len(expanding[0]["train"])


def test_purge_and_embargo_fail_closed_when_they_remove_evidence():
    folds = four_stage_walk_forward(
        _rows(),
        WalkForwardConfig(12, 6, 6, 6, 5, purge=timedelta(minutes=20), embargo=timedelta(minutes=20)),
    )
    assert folds[0]["status"] == "NO_TRADE"


def test_invalid_config_is_rejected():
    with pytest.raises(ValueError):
        WalkForwardConfig(10, 5, 5, 5, 5, mode="rolling")
    with pytest.raises(ValueError):
        WalkForwardConfig(10, 5, 5, 5, 5, purge=timedelta(seconds=-1))
