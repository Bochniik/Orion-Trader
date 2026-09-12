from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from evals.benchmark_industry_specialist_v1 import evaluate_records, load_prereg

PREREG_PATH = Path(__file__).resolve().parents[1] / "evals" / "industry_specialist_prereg_v1.json"


def _prereg():
    payload = load_prereg(PREREG_PATH)
    payload = deepcopy(payload)
    payload.update(
        {
            "minimum_global_observations": 4,
            "minimum_global_sessions": 2,
            "minimum_industry_observations": 2,
            "minimum_industry_sessions": 2,
            "minimum_evaluation_observations": 8,
            "minimum_evaluation_sessions": 4,
            "bootstrap_samples": 100,
            "ridge": 1.0,
        }
    )
    payload["industry_symbols"] = ["NVDA", "AMD"]
    payload["control_symbols"] = ["AAPL", "MSFT"]
    return payload


def _rows(days=12):
    rows = []
    start = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    for day in range(days):
        stamp = (start + timedelta(days=day)).isoformat()
        for symbol in ("NVDA", "AMD"):
            rows.append({"timestamp": stamp, "symbol": symbol, "sector": "Semiconductors", "p_up": 50.0, "actual_up": 1})
        for symbol in ("AAPL", "MSFT"):
            rows.append({"timestamp": stamp, "symbol": symbol, "sector": "Control", "p_up": 50.0, "actual_up": 0})
    return rows


def test_preregistration_is_frozen_to_three_hour_screen():
    prereg = load_prereg(PREREG_PATH)
    assert prereg["candidate_id"] == "semiconductor-specialist-3h-v1"
    assert prereg["target_horizon"] == "3h"
    assert prereg["decisive_holdout_assigned"] is False
    assert prereg["promotion_authorized"] is False
    assert "NVDA" in prereg["industry_symbols"]
    assert "5h" not in prereg["target_horizon"]


def test_semiconductor_evaluation_uses_active_rows_only_and_cannot_promote():
    result = evaluate_records(_rows(), _prereg())
    assert result["target_horizon"] == "3h"
    assert result["screening_only"] is True
    assert result["decisive_holdout"] is False
    assert result["promotion_authorized"] is False
    assert result["candidate_rows_active"] > 0
    assert result["result"]["paired_observations"] == result["candidate_rows_active"]


def test_control_rows_are_not_scored_as_semiconductor_evidence():
    result = evaluate_records(_rows(days=10), _prereg())
    assert result["candidate_rows_total"] == 20
    assert result["generation_coverage"]["symbols"] == 4


def test_invalid_preregistration_fails_closed(tmp_path):
    payload = _prereg()
    payload["target_horizon"] = "5h"
    path = tmp_path / "bad.json"
    import json
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="target only 3h"):
        load_prereg(path)
