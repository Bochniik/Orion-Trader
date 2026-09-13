from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    path = ROOT / "scripts/summarize_long_horizon_v5_collection_health.py"
    spec = importlib.util.spec_from_file_location("long_horizon_collection_health", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


health = _load_module()


def _payload(*, status="degraded", forward=True, expected=4, observed=2, failures=None):
    return {
        "contract": health.CONTRACT,
        "status": status,
        "acquisition_provenance": {"forward_eligible": forward},
        "coverage": {
            "expected_pair_count": expected,
            "observed_pair_count": observed,
            "complete": expected == observed,
        },
        "failures": failures or {},
        "paired_predictions": [
            {
                "symbol": "AAPL",
                "challenger": {"probability_up": 0.999999},
                "incumbent": {"probability_up": 0.000001},
            }
        ],
    }


def test_summary_aggregates_only_score_blind_collection_health():
    result = health.summarize_payloads(
        [
            _payload(
                failures={
                    "AAPL": "prediction_bar_not_closed:240s",
                    "MSFT": "stale_prediction_timestamp:901s",
                }
            ),
            _payload(
                status="completed",
                expected=4,
                observed=4,
                failures={"NVDA": "prediction_bar_not_closed:120s"},
            ),
        ]
    )

    assert result["score_blind"] is True
    assert result["run_count"] == 2
    assert result["forward_eligible_run_count"] == 2
    assert result["complete_run_count"] == 1
    assert result["status_counts"] == {"completed": 1, "degraded": 1}
    assert result["coverage"] == {
        "expected_pair_count": 8,
        "observed_pair_count": 6,
        "observed_pair_rate": 0.75,
    }
    assert result["failure_reason_counts"] == {
        "prediction_bar_not_closed": 2,
        "stale_prediction_timestamp": 1,
    }
    assert result["affected_symbols_by_reason"] == {
        "prediction_bar_not_closed": ["AAPL", "NVDA"],
        "stale_prediction_timestamp": ["MSFT"],
    }
    rendered = str(result)
    assert "0.999999" not in rendered
    assert "0.000001" not in rendered


def test_dynamic_failure_details_are_not_preserved():
    result = health.summarize_payloads(
        [_payload(failures={"AAPL": "paired_timestamp_mismatch:secret-a!=secret-b"})]
    )
    assert result["failure_reason_counts"] == {"paired_timestamp_mismatch": 1}
    assert "secret-a" not in str(result)
    assert "secret-b" not in str(result)


def test_summary_rejects_non_mapping_failures():
    payload = _payload()
    payload["failures"] = ["bad"]
    with pytest.raises(ValueError, match="failures must be a JSON object"):
        health.summarize_payloads([payload])


def test_file_loader_rejects_wrong_contract(tmp_path):
    path = tmp_path / "prediction.json"
    path.write_text('{"contract":"wrong"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected contract"):
        health.summarize_files([path])
