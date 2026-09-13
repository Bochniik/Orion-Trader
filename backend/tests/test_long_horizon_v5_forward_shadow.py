from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import pytest

from app.services import intraday_probability_ensemble_engine as ensemble

ROOT = Path(__file__).resolve().parents[2]
HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = _load("long_horizon_shadow_runner", "scripts/run_long_horizon_v5_paired_cloud_shadow.py")
settler = _load("long_horizon_shadow_settler", "scripts/settle_long_horizon_v5_shadow.py")


def test_session_gate_is_score_blind_and_horizon_aware():
    both = runner.session_gate(datetime(2026, 9, 11, 14, 5, tzinfo=timezone.utc))
    assert both["allowed"] is True
    assert both["window_et"] == "10:00-13:30"
    assert both["regular_close_et"] == "16:00"
    assert both["eligible_horizons"] == ["3h", "5h"]

    three_hour_only = runner.session_gate(datetime(2026, 9, 11, 15, 5, tzinfo=timezone.utc))
    assert three_hour_only["allowed"] is True
    assert three_hour_only["eligible_horizons"] == ["3h"]

    no_settleable_horizon = runner.session_gate(datetime(2026, 9, 11, 17, 5, tzinfo=timezone.utc))
    assert no_settleable_horizon["allowed"] is False
    assert no_settleable_horizon["eligible_horizons"] == []
    assert no_settleable_horizon["reason"] == "no_settleable_horizon_before_regular_close"

    outside_window = runner.session_gate(datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc))
    assert outside_window["allowed"] is False
    assert outside_window["reason"] == "outside_long_horizon_shadow_window"


def _challenger_fixture():
    return {
        "available": True,
        "as_of": "2026-09-11T14:05:00+00:00",
        "horizons": {
            "3h": {"available": True, "probability_up": 0.61, "direction": "bullish", "target_time_utc": "2026-09-11T17:05:00+00:00", "training_samples": 900, "training_cutoff": "2026-09-11T11:05:00+00:00", "max_training_timestamp": "2026-09-11T11:05:00+00:00"},
            "5h": {"available": True, "probability_up": 0.57, "direction": "bullish", "target_time_utc": "2026-09-11T19:05:00+00:00", "training_samples": 800, "training_cutoff": "2026-09-11T09:05:00+00:00", "max_training_timestamp": "2026-09-11T09:05:00+00:00"},
        },
    }


def _incumbent_fixture(as_of="2026-09-11T10:05:00-04:00"):
    return {
        "as_of": as_of,
        "horizons": {
            "3h": {"probability_up": 58.0, "direction": "bullish", "suppressed": False},
            "5h": {"probability_up": None, "suppressed_probability_up": 54.0, "direction": "neutral", "suppressed": True},
        },
    }


def _source_model(as_of: str):
    return {
        "available": True,
        "as_of": as_of,
        "horizons": {
            horizon: {
                "available": True,
                "probability_up": 56.0,
                "evidence_quality": 70.0,
                "training_samples": 1200,
            }
            for horizon in ("30m", "1h", "3h", "5h")
        },
    }


def test_v3_exposes_as_of_only_when_source_timestamps_match(monkeypatch):
    monkeypatch.setattr(ensemble, "estimate_intraday_probabilities", lambda symbol: _source_model("2026-09-11T10:05:00-04:00"))
    monkeypatch.setattr(ensemble, "estimate_intraday_probabilities_v2", lambda symbol: _source_model("2026-09-11T14:05:00+00:00"))
    aligned = ensemble.estimate_intraday_probabilities_v3("AAPL")
    assert aligned["source_timestamp_aligned"] is True
    assert aligned["as_of"] == "2026-09-11T14:05:00+00:00"

    monkeypatch.setattr(ensemble, "estimate_intraday_probabilities_v2", lambda symbol: _source_model("2026-09-11T14:10:00+00:00"))
    mismatched = ensemble.estimate_intraday_probabilities_v3("AAPL")
    assert mismatched["source_timestamp_aligned"] is False
    assert mismatched["as_of"] is None
    assert any("timestamps" in warning.lower() for warning in mismatched["warnings"])


def test_atomic_runner_pairs_incumbent_and_challenger_on_exact_timestamp(monkeypatch):
    monkeypatch.setattr(runner, "estimate_long_horizon_v5", lambda symbol: _challenger_fixture())
    monkeypatch.setattr(runner, "estimate_intraday_probabilities_v3_1", lambda symbol: _incumbent_fixture())
    rows, error = runner.run_symbol("AAPL")
    assert error is None
    assert len(rows) == 2
    assert {row["horizon"] for row in rows} == {"3h", "5h"}
    assert {row["prediction_time_utc"] for row in rows} == {"2026-09-11T14:05:00+00:00"}
    assert all(row["timestamp_pair_verified"] is True for row in rows)
    five_hour = next(row for row in rows if row["horizon"] == "5h")
    assert five_hour["incumbent"]["probability_up"] == 0.54
    assert five_hour["incumbent"]["was_runtime_suppressed"] is True


def test_atomic_runner_only_emits_horizons_expected_for_slot(monkeypatch):
    monkeypatch.setattr(runner, "estimate_long_horizon_v5", lambda symbol: _challenger_fixture())
    monkeypatch.setattr(runner, "estimate_intraday_probabilities_v3_1", lambda symbol: _incumbent_fixture())
    rows, error = runner.run_symbol("AAPL", ["3h"])
    assert error is None
    assert [row["horizon"] for row in rows] == ["3h"]


def test_atomic_runner_fails_closed_on_timestamp_mismatch(monkeypatch):
    monkeypatch.setattr(runner, "estimate_long_horizon_v5", lambda symbol: _challenger_fixture())
    monkeypatch.setattr(
        runner,
        "estimate_intraday_probabilities_v3_1",
        lambda symbol: _incumbent_fixture("2026-09-11T10:00:00-04:00"),
    )
    rows, error = runner.run_symbol("AAPL")
    assert rows == []
    assert error and error.startswith("paired_timestamp_mismatch:")


def test_atomic_runner_fails_closed_when_incumbent_alignment_is_unknown(monkeypatch):
    monkeypatch.setattr(runner, "estimate_long_horizon_v5", lambda symbol: _challenger_fixture())
    incumbent = _incumbent_fixture()
    incumbent["as_of"] = None
    monkeypatch.setattr(runner, "estimate_intraday_probabilities_v3_1", lambda symbol: incumbent)
    rows, error = runner.run_symbol("AAPL")
    assert rows == []
    assert error == "incumbent_source_timestamp_unaligned_or_missing"


def test_source_freshness_guard_rejects_stale_future_wrong_session_and_mixed_timestamps():
    reference = "2026-09-11T10:05:00-04:00"
    assert runner._prediction_freshness_error(
        [{"prediction_time_utc": "2026-09-11T13:50:00+00:00"}], reference
    ) is None
    assert runner._prediction_freshness_error(
        [{"prediction_time_utc": "2026-09-11T13:49:59+00:00"}], reference
    ).startswith("stale_prediction_timestamp:")
    assert runner._prediction_freshness_error(
        [{"prediction_time_utc": "2026-09-11T14:06:01+00:00"}], reference
    ) == "prediction_timestamp_in_future"
    assert runner._prediction_freshness_error(
        [{"prediction_time_utc": "2026-09-10T20:00:00+00:00"}], reference
    ) == "prediction_timestamp_wrong_market_session"
    assert runner._prediction_freshness_error(
        [
            {"prediction_time_utc": "2026-09-11T14:05:00+00:00"},
            {"prediction_time_utc": "2026-09-11T14:04:00+00:00"},
        ],
        reference,
    ) == "symbol_prediction_timestamps_disagree"


def test_payload_degrades_instead_of_recording_stale_forward_evidence(monkeypatch):
    monkeypatch.setattr(runner, "lineage", lambda: {"git_commit": "abc", "design_id": runner.DESIGN_ID, "files_sha256": {}})

    def fake_run(symbol, expected_horizons):
        return [
            {
                "symbol": symbol,
                "horizon": horizon,
                "prediction_time_utc": "2026-09-11T13:45:00+00:00",
            }
            for horizon in expected_horizons
        ], None

    monkeypatch.setattr(runner, "run_symbol", fake_run)
    payload = runner.build_payload(["AAPL"], datetime(2026, 9, 11, 14, 5, tzinfo=timezone.utc))
    assert payload["status"] == "degraded"
    assert payload["paired_predictions"] == []
    assert payload["coverage"]["observed_pair_count"] == 0
    assert payload["failures"]["AAPL"] == "stale_prediction_timestamp:1200s"
    assert payload["source_freshness"] == {
        "enforced": True,
        "score_blind": True,
        "max_age_minutes": 15,
        "future_tolerance_minutes": 1,
        "reference_time_et": "2026-09-11T10:05:00-04:00",
    }


def test_scheduled_acquisition_is_bound_to_exact_run_attempt_and_commit(monkeypatch):
    monkeypatch.setattr(runner, "lineage", lambda: {"git_commit": HEAD_SHA, "design_id": runner.DESIGN_ID, "files_sha256": {}})
    payload = runner.build_payload(
        ["AAPL"],
        datetime(2026, 9, 11, 17, 5, tzinfo=timezone.utc),
        event_name="schedule",
        run_id="123456",
        run_attempt=2,
        github_head_sha=HEAD_SHA,
    )
    provenance = payload["acquisition_provenance"]
    assert provenance["contract"] == runner.ACQUISITION_CONTRACT
    assert provenance["github_run_id"] == "123456"
    assert provenance["github_run_attempt"] == 2
    assert provenance["github_head_sha"] == HEAD_SHA
    assert provenance["workflow_commit_verified"] is True
    assert provenance["forward_eligible"] is True
    assert provenance["eligibility_reason"] == "scheduled_exact_workflow_commit"


def test_scheduled_acquisition_fails_closed_on_invalid_or_mismatched_identity(monkeypatch):
    lineage = {"git_commit": HEAD_SHA, "design_id": runner.DESIGN_ID, "files_sha256": {}}
    monkeypatch.setattr(runner, "lineage", lambda: lineage)
    common = {
        "event_name": "schedule",
        "run_id": "123456",
        "run_attempt": 1,
        "github_head_sha": HEAD_SHA,
    }
    with pytest.raises(ValueError, match="positive GitHub run ID"):
        runner.build_payload(["AAPL"], event_name="schedule", run_id=None, run_attempt=1, github_head_sha=HEAD_SHA)
    with pytest.raises(ValueError, match="positive GitHub run attempt"):
        runner.build_payload(["AAPL"], **{**common, "run_attempt": 0})
    with pytest.raises(ValueError, match="40-character GitHub head SHA"):
        runner.build_payload(["AAPL"], **{**common, "github_head_sha": "bad"})
    with pytest.raises(ValueError, match="does not match checked-out commit"):
        runner.build_payload(["AAPL"], **{**common, "github_head_sha": OTHER_SHA})


def test_manual_acquisition_is_explicitly_not_forward_eligible(monkeypatch):
    monkeypatch.setattr(runner, "lineage", lambda: {"git_commit": HEAD_SHA, "design_id": runner.DESIGN_ID, "files_sha256": {}})
    payload = runner.build_payload(
        ["AAPL"],
        datetime(2026, 9, 11, 17, 5, tzinfo=timezone.utc),
        event_name="workflow_dispatch",
        run_id="123456",
        run_attempt=1,
        github_head_sha=HEAD_SHA,
    )
    provenance = payload["acquisition_provenance"]
    assert provenance["forward_eligible"] is False
    assert provenance["workflow_commit_verified"] is False
    assert provenance["eligibility_reason"] == "non_scheduled_diagnostic_run"


def test_payload_skips_scheduled_slot_when_no_horizon_can_settle(monkeypatch):
    monkeypatch.setattr(runner, "lineage", lambda: {"git_commit": "abc", "design_id": runner.DESIGN_ID, "files_sha256": {}})
    payload = runner.build_payload(["AAPL", "MSFT"], datetime(2026, 9, 11, 17, 5, tzinfo=timezone.utc))
    assert payload["status"] == "skipped"
    assert payload["session_gate"]["reason"] == "no_settleable_horizon_before_regular_close"
    assert payload["coverage"] == {
        "score_blind": True,
        "expected_pair_count": 0,
        "observed_pair_count": 0,
        "complete": True,
        "missing_pairs": [],
    }


def test_payload_marks_missing_expected_symbol_horizon_coverage_degraded(monkeypatch):
    monkeypatch.setattr(runner, "lineage", lambda: {"git_commit": "abc", "design_id": runner.DESIGN_ID, "files_sha256": {}})

    def fake_run(symbol, expected_horizons):
        rows = [
            {
                "symbol": symbol,
                "horizon": horizon,
                "prediction_time_utc": "2026-09-11T14:05:00+00:00",
            }
            for horizon in expected_horizons
            if not (symbol == "MSFT" and horizon == "5h")
        ]
        return rows, None

    monkeypatch.setattr(runner, "run_symbol", fake_run)
    payload = runner.build_payload(["AAPL", "MSFT"], datetime(2026, 9, 11, 14, 5, tzinfo=timezone.utc))
    assert payload["status"] == "degraded"
    assert payload["coverage"]["score_blind"] is True
    assert payload["coverage"]["expected_pair_count"] == 4
    assert payload["coverage"]["observed_pair_count"] == 3
    assert payload["coverage"]["missing_pairs"] == [{"symbol": "MSFT", "horizon": "5h"}]
    assert payload["failures"]["MSFT"] == "missing_expected_horizons:5h"


def test_settlement_expansion_preserves_pair_identity_model_names_and_acquisition_provenance():
    acquisition = {
        "contract": runner.ACQUISITION_CONTRACT,
        "event_name": "schedule",
        "github_run_id": "123456",
        "github_run_attempt": 1,
        "github_head_sha": HEAD_SHA,
        "workflow_commit_verified": True,
        "forward_eligible": True,
    }
    payload = {
        "contract": settler.CONTRACT,
        "lineage": {"git_commit": HEAD_SHA, "design_id": "long-horizon-v5-20260911-a"},
        "acquisition_provenance": acquisition,
        "paired_predictions": [{
            "symbol": "AAPL",
            "horizon": "3h",
            "prediction_time_utc": "2026-09-11T14:05:00+00:00",
            "incumbent": {"engine": "regular_hours_v3_1", "probability_up": 0.55, "direction": "bullish"},
            "challenger": {"engine": "long-horizon-v5-20260911-a", "probability_up": 0.60, "direction": "bullish"},
        }],
    }
    forecasts = settler.expand_payload(payload, "prediction.json")
    assert len(forecasts) == 2
    assert {row["engine"] for row in forecasts} == {"regular_hours_v3_1", "long-horizon-v5-20260911-a"}
    assert {row["prediction_time"] for row in forecasts} == {"2026-09-11T14:05:00+00:00"}
    assert {row["lineage"]["paired_role"] for row in forecasts} == {"incumbent", "challenger"}
    assert all(row["lineage"]["acquisition_provenance"] == acquisition for row in forecasts)


def test_workflows_are_research_only_and_do_not_expose_write_permissions():
    for relative in (
        ".github/workflows/long-horizon-v5-cloud-shadow.yml",
        ".github/workflows/long-horizon-v5-evidence-cycle.yml",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "contents: write" not in text
        assert "orders" not in text.lower()
        assert "actions: write" not in text
    prediction = (ROOT / ".github/workflows/long-horizon-v5-cloud-shadow.yml").read_text(encoding="utf-8")
    assert "retention-days: 45" in prediction
    assert "run_long_horizon_v5_paired_cloud_shadow.py" in prediction
    assert '--event-name "$GITHUB_EVENT_NAME"' in prediction
    assert '--run-id "$GITHUB_RUN_ID"' in prediction
    assert '--run-attempt "$GITHUB_RUN_ATTEMPT"' in prediction
    assert '--github-head-sha "$GITHUB_SHA"' in prediction
