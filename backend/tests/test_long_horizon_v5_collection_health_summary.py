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


def _payload(
    *,
    status="degraded",
    forward=True,
    symbols=None,
    horizons=None,
    missing=None,
    failures=None,
):
    symbols = list(symbols or ["AAPL", "MSFT"])
    horizons = list(horizons or ["3h", "5h"])
    missing = list(missing if missing is not None else [{"symbol": "MSFT", "horizon": "5h"}])
    expected = len(symbols) * len(horizons)
    observed = expected - len(missing)
    if status == "completed":
        missing = []
        observed = expected
    if status == "skipped":
        horizons = []
        missing = []
        expected = 0
        observed = 0
    return {
        "contract": health.CONTRACT,
        "status": status,
        "acquisition_provenance": {"forward_eligible": forward},
        "symbols_requested": symbols,
        "session_gate": {"eligible_horizons": horizons},
        "coverage": {
            "score_blind": True,
            "expected_pair_count": expected,
            "observed_pair_count": observed,
            "complete": not missing,
            "missing_pairs": missing,
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


def test_summary_aggregates_only_score_blind_forward_collection_health():
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
                failures={"AAPL": "prediction_bar_not_closed:120s"},
            ),
        ]
    )

    assert result["contract"] == "orion-long-horizon-v5-collection-health-v4"
    assert result["score_blind"] is True
    assert result["population"] == "forward_eligible_only"
    assert result["input_run_count"] == 2
    assert result["forward_eligible_run_count"] == 2
    assert result["ignored_non_forward_run_count"] == 0
    assert result["complete_run_count"] == 1
    assert result["status_counts"] == {"completed": 1, "degraded": 1}
    assert result["coverage"]["expected_pair_count"] == 8
    assert result["coverage"]["observed_pair_count"] == 7
    assert result["coverage"]["observed_pair_rate"] == 0.875
    assert result["coverage"]["by_horizon"] == {
        "3h": {
            "eligible_run_count": 2,
            "complete_run_count": 2,
            "expected_pair_count": 4,
            "observed_pair_count": 4,
            "missing_pair_count": 0,
            "observed_pair_rate": 1.0,
        },
        "5h": {
            "eligible_run_count": 2,
            "complete_run_count": 1,
            "expected_pair_count": 4,
            "observed_pair_count": 3,
            "missing_pair_count": 1,
            "observed_pair_rate": 0.75,
        },
    }
    assert result["critical_5h"] == result["coverage"]["by_horizon"]["5h"]
    assert result["failure_reason_counts"] == {
        "prediction_bar_not_closed": 2,
        "stale_prediction_timestamp": 1,
    }
    assert result["affected_symbols_by_reason"] == {
        "prediction_bar_not_closed": ["AAPL"],
        "stale_prediction_timestamp": ["MSFT"],
    }
    rendered = str(result)
    assert "0.999999" not in rendered
    assert "0.000001" not in rendered


def test_horizon_breakdown_exposes_critical_5h_loss_hidden_by_aggregate_coverage():
    payloads = [
        _payload(status="completed", horizons=["3h"], symbols=["AAPL", "MSFT"])
        for _ in range(9)
    ]
    payloads.append(
        _payload(
            status="degraded",
            horizons=["3h", "5h"],
            symbols=["AAPL", "MSFT"],
            missing=[
                {"symbol": "AAPL", "horizon": "5h"},
                {"symbol": "MSFT", "horizon": "5h"},
            ],
        )
    )

    result = health.summarize_payloads(payloads)

    assert result["coverage"]["observed_pair_rate"] == pytest.approx(20 / 22, abs=1e-6)
    assert result["coverage"]["by_horizon"]["3h"]["observed_pair_rate"] == 1.0
    assert result["critical_5h"]["eligible_run_count"] == 1
    assert result["critical_5h"]["expected_pair_count"] == 2
    assert result["critical_5h"]["observed_pair_count"] == 0
    assert result["critical_5h"]["observed_pair_rate"] == 0.0


def test_non_forward_runs_are_counted_but_excluded_before_projection_validation():
    diagnostic = _payload(forward=False)
    diagnostic["coverage"] = "intentionally malformed diagnostic coverage"
    diagnostic["failures"] = ["also malformed"]

    result = health.summarize_payloads(
        [
            _payload(status="completed"),
            diagnostic,
        ]
    )

    assert result["input_run_count"] == 2
    assert result["forward_eligible_run_count"] == 1
    assert result["ignored_non_forward_run_count"] == 1
    assert result["complete_run_count"] == 1
    assert result["status_counts"] == {"completed": 1}
    assert result["coverage"]["expected_pair_count"] == 4
    assert result["coverage"]["observed_pair_count"] == 4
    assert result["coverage"]["observed_pair_rate"] == 1.0
    assert result["coverage"]["by_horizon"]["3h"]["observed_pair_rate"] == 1.0
    assert result["coverage"]["by_horizon"]["5h"]["observed_pair_rate"] == 1.0
    assert result["failure_reason_counts"] == {}
    assert result["affected_symbols_by_reason"] == {}


def test_zero_eligible_horizon_keeps_horizon_rates_null():
    result = health.summarize_payloads([_payload(status="skipped")])

    assert result["coverage"]["observed_pair_rate"] is None
    assert result["coverage"]["by_horizon"]["3h"]["observed_pair_rate"] is None
    assert result["critical_5h"]["observed_pair_rate"] is None
    assert result["critical_5h"]["eligible_run_count"] == 0


def test_dynamic_failure_details_are_not_preserved():
    result = health.summarize_payloads(
        [_payload(failures={"AAPL": "paired_timestamp_mismatch:secret-a!=secret-b"})]
    )
    assert result["failure_reason_counts"] == {"paired_timestamp_mismatch": 1}
    assert "secret-a" not in str(result)
    assert "secret-b" not in str(result)


def test_summary_rejects_inconsistent_coverage_counts():
    payload = _payload()
    payload["coverage"]["observed_pair_count"] = 4
    with pytest.raises(ValueError, match="observed_pair_count disagrees"):
        health.summarize_payloads([payload])


def test_summary_rejects_expected_count_that_disagrees_with_geometry():
    payload = _payload()
    payload["coverage"]["expected_pair_count"] = 99
    with pytest.raises(ValueError, match="expected_pair_count disagrees"):
        health.summarize_payloads([payload])


def test_summary_rejects_complete_flag_that_disagrees_with_missing_pairs():
    payload = _payload()
    payload["coverage"]["complete"] = True
    with pytest.raises(ValueError, match="complete disagrees"):
        health.summarize_payloads([payload])


def test_summary_rejects_unexpected_or_duplicate_missing_pairs():
    unexpected = _payload()
    unexpected["coverage"]["missing_pairs"] = [{"symbol": "NVDA", "horizon": "5h"}]
    with pytest.raises(ValueError, match="unexpected symbol/horizon"):
        health.summarize_payloads([unexpected])

    duplicate = _payload()
    duplicate["coverage"]["missing_pairs"] = [
        {"symbol": "MSFT", "horizon": "5h"},
        {"symbol": "MSFT", "horizon": "5h"},
    ]
    duplicate["coverage"]["observed_pair_count"] = 2
    with pytest.raises(ValueError, match="missing_pairs contains duplicates"):
        health.summarize_payloads([duplicate])


def test_summary_rejects_non_score_blind_forward_coverage():
    payload = _payload()
    payload["coverage"]["score_blind"] = False
    with pytest.raises(ValueError, match="score_blind"):
        health.summarize_payloads([payload])


def test_summary_rejects_invalid_status_geometry_and_failure_symbol():
    completed = _payload(status="completed")
    completed["status"] = "degraded"
    with pytest.raises(ValueError, match="degraded run must have incomplete coverage"):
        health.summarize_payloads([completed])

    skipped = _payload(status="skipped")
    skipped["coverage"]["expected_pair_count"] = 1
    with pytest.raises(ValueError, match="expected_pair_count disagrees"):
        health.summarize_payloads([skipped])

    failure = _payload(failures={"NVDA": "provider_failure:x"})
    with pytest.raises(ValueError, match="outside symbols_requested"):
        health.summarize_payloads([failure])


def test_summary_rejects_non_mapping_failures_on_forward_run():
    payload = _payload()
    payload["failures"] = ["bad"]
    with pytest.raises(ValueError, match="failures must be a JSON object"):
        health.summarize_payloads([payload])


def test_summary_rejects_ambiguous_forward_eligibility():
    payload = _payload()
    payload["acquisition_provenance"]["forward_eligible"] = "true"
    with pytest.raises(ValueError, match="forward_eligible must be boolean"):
        health.summarize_payloads([payload])


def test_summary_rejects_missing_provenance():
    payload = _payload()
    payload.pop("acquisition_provenance")
    with pytest.raises(ValueError, match="acquisition_provenance must be a JSON object"):
        health.summarize_payloads([payload])


def test_file_loader_rejects_wrong_contract(tmp_path):
    path = tmp_path / "prediction.json"
    path.write_text('{"contract":"wrong"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected contract"):
        health.summarize_files([path])
