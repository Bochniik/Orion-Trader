from __future__ import annotations

from copy import deepcopy

import pytest

from evals.audit_intraday_calibration_v3_1 import (
    audit_backtest_result,
    audit_horizon,
)


def _records(count: int = 240, *, evaluation_flip: bool = False):
    rows = []
    split = int(count * 0.60)
    for i in range(count):
        # Deliberately overconfident probabilities. Direction is right about
        # 60% of the time, so 80/20 probabilities are materially overconfident.
        bullish = (i % 10) < 6
        probability = 80.0 if bullish else 20.0
        actual = 1 if bullish else 0
        if i % 5 in (0, 1):
            actual = 1 - actual
        if evaluation_flip and i >= split:
            actual = 1 - actual
        rows.append({
            "timestamp": f"2026-01-{1 + i // 24:02d}T{9 + (i % 8):02d}:{(i * 5) % 60:02d}:00-05:00",
            "p_up": probability,
            "actual_up": actual,
        })
    return rows


def test_horizon_audit_uses_earlier_records_for_reliability_fit_only():
    normal = audit_horizon("1h", _records())
    changed_future = audit_horizon("1h", _records(evaluation_flip=True))

    assert normal["available"] is True
    assert normal["calibration_end_timestamp"] < normal["evaluation_start_timestamp"]
    assert normal["reliability_fit"] == changed_future["reliability_fit"]
    assert normal["v3_1_evaluation"] != changed_future["v3_1_evaluation"]


def test_overconfident_holdout_is_improved_by_shrinkage():
    result = audit_horizon("1h", _records())

    assert result["brier_improvement"] > 0
    assert result["log_loss_improvement"] > 0
    assert result["verdict"] == "improves_proper_scores"


def test_invalid_or_short_inputs_fail_closed():
    short = audit_horizon("30m", _records(100))
    assert short["available"] is False
    assert "Need at least" in short["reason"]

    with pytest.raises(ValueError):
        audit_horizon("2h", _records())
    with pytest.raises(ValueError):
        audit_horizon("1h", _records(), calibration_fraction=0.90)


def test_malformed_records_are_excluded_from_evidence():
    records = _records()
    records.extend([
        {"timestamp": "2026-02-01T10:00:00-05:00", "p_up": 120, "actual_up": 1},
        {"timestamp": "2026-02-01T10:05:00-05:00", "p_up": 50, "actual_up": 3},
        {"timestamp": None, "p_up": 50, "actual_up": 1},
    ])

    result = audit_horizon("3h", records)
    assert result["record_count"] == len(_records())


def test_backtest_audit_does_not_mutate_source_and_never_modifies_runtime():
    source = {
        "symbol": "aapl",
        "prediction_records": {h: _records() for h in ("30m", "1h", "3h", "5h")},
    }
    before = deepcopy(source)

    result = audit_backtest_result(source)

    assert source == before
    assert result["contract"] == "orion-intraday-v3-1-calibration-audit-v1"
    assert result["runtime_modified"] is False
    assert result["evaluable_horizons"] == 4
    assert set(result["horizons"]) == {"30m", "1h", "3h", "5h"}


def test_missing_prediction_records_are_reported_not_invented():
    result = audit_backtest_result({"symbol": "MSFT"})

    assert result["available"] is False
    assert result["research_conclusion"] == "heuristic_not_demonstrated_across_all_evaluable_horizons"
    assert all(not row["available"] for row in result["horizons"].values())
