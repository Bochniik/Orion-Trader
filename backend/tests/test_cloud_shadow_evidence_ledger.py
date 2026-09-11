from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "accumulate_cloud_shadow_evidence.py"
SPEC = importlib.util.spec_from_file_location("shadow_evidence_ledger", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def record(*, symbol="AAPL", probability=0.8, actual=1, outcome=102.0, lineage=None):
    probability = float(probability)
    actual = int(actual)
    brier = (probability - actual) ** 2
    return {
        "source_file": "prediction.json",
        "engine": "regular_hours_v3_1",
        "symbol": symbol,
        "horizon": "30m",
        "horizon_minutes": 30,
        "prediction_time_utc": "2026-09-10T14:00:00+00:00",
        "target_time_utc": "2026-09-10T14:30:00+00:00",
        "probability_up": probability,
        "predicted_direction": "bullish" if probability >= 0.5 else "bearish",
        "actual_up": actual,
        "base_price": 100.0,
        "outcome_price": outcome,
        "realized_return_pct": outcome - 100.0,
        "correct_direction": bool((probability >= 0.5) == bool(actual)),
        "brier": brier,
        "log_loss": 0.2231435513,
        "lineage": lineage or {"git_sha": "abc", "model_artifact_sha256": "model"},
        "reliability_profile_source": "ticker_specific_walk_forward_60d_5m",
        "profile_validated_for_symbol": True,
    }


def evaluation(records):
    return {
        "contract": module.EVALUATION_CONTRACT,
        "created_at_utc": "2026-09-10T15:00:00+00:00",
        "evaluation_cutoff_utc": "2026-09-10T15:00:00+00:00",
        "leakage_safe": True,
        "records": records,
    }


def test_record_id_is_stable_across_source_file_paths():
    first = record()
    second = dict(first)
    second["source_file"] = "/tmp/downloaded/run-123/prediction.json"
    assert module.record_id(first) == module.record_id(second)
    assert module.material_fingerprint(first) == module.material_fingerprint(second)


def test_merge_is_idempotent_for_repeated_evidence():
    row = record()
    merged = module.merge_records([row], [dict(row), dict(row)])
    assert len(merged) == 1
    assert merged[0]["record_id"] == module.record_id(row)


def test_merge_fails_closed_on_conflicting_outcome_for_same_identity():
    first = record(outcome=102.0)
    conflicting = record(outcome=99.0)
    with pytest.raises(ValueError, match="Conflicting settled evidence"):
        module.merge_records([first], [conflicting])


def test_lineage_change_creates_distinct_evidence_identity():
    first = record(lineage={"git_sha": "abc", "model_artifact_sha256": "model-a"})
    second = record(lineage={"git_sha": "abc", "model_artifact_sha256": "model-b"})
    merged = module.merge_records([first], [second])
    assert len(merged) == 2
    assert merged[0]["record_id"] != merged[1]["record_id"]


def test_summary_reports_cumulative_metrics_and_distinct_sessions():
    first = record(symbol="AAPL", probability=0.8, actual=1)
    second = record(symbol="MSFT", probability=0.2, actual=0, outcome=98.0)
    second["prediction_time_utc"] = "2026-09-11T14:00:00+00:00"
    second["target_time_utc"] = "2026-09-11T14:30:00+00:00"
    summary = module.summarize([first, second])
    assert summary["observations"] == 2
    assert summary["distinct_sessions"] == 2
    assert summary["directional_accuracy"] == 1.0
    assert summary["brier_score"] == 0.04


def test_score_blind_summary_exposes_coverage_only_and_is_outcome_invariant():
    favorable = [record(symbol="AAPL", probability=0.95, actual=1, outcome=105.0)]
    unfavorable = [record(symbol="AAPL", probability=0.95, actual=0, outcome=95.0)]

    favorable_summary = module.summarize(favorable, score_blind=True)
    unfavorable_summary = module.summarize(unfavorable, score_blind=True)

    assert favorable_summary == unfavorable_summary
    assert favorable_summary == {
        "observations": 1,
        "distinct_sessions": 1,
        "score_blind": True,
        "metrics_exposed": False,
    }
    for forbidden in ("brier_score", "log_loss", "directional_accuracy", "ece_10_bin"):
        assert forbidden not in favorable_summary


def test_load_evaluation_rejects_non_leakage_safe_payload(tmp_path):
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps({"contract": module.EVALUATION_CONTRACT, "leakage_safe": False, "records": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="not marked leakage_safe"):
        module.load_evaluation(path)


def test_build_ledger_preserves_prior_records_and_deduplicates_new_inputs(tmp_path):
    prior = record(symbol="AAPL")
    new = record(symbol="MSFT", probability=0.3, actual=0, outcome=99.0)
    new["prediction_time_utc"] = "2026-09-10T15:00:00+00:00"
    new["target_time_utc"] = "2026-09-10T15:30:00+00:00"

    evaluation_path = tmp_path / "evaluation.json"
    payload = evaluation([prior, new])
    evaluation_path.write_text(json.dumps(payload), encoding="utf-8")

    existing = {"contract": module.CONTRACT, "records": [prior], "source_evaluations": []}
    ledger = module.build_ledger(existing, [(evaluation_path, payload)])
    assert ledger["append_only_semantics"] is True
    assert ledger["summary"]["observations"] == 2
    assert len(ledger["records"]) == 2
    assert len(ledger["source_evaluations"]) == 1


def test_build_ledger_score_blind_mode_hides_interim_performance_metrics(tmp_path):
    row = record(symbol="AAPL", probability=0.9, actual=1)
    evaluation_path = tmp_path / "evaluation.json"
    payload = evaluation([row])
    evaluation_path.write_text(json.dumps(payload), encoding="utf-8")

    ledger = module.build_ledger(
        {"contract": module.CONTRACT, "records": [], "source_evaluations": []},
        [(evaluation_path, payload)],
        score_blind_summary=True,
    )

    assert ledger["score_blind_summary"] is True
    assert ledger["summary"]["metrics_exposed"] is False
    assert ledger["by_engine_horizon"]["regular_hours_v3_1:30m"]["metrics_exposed"] is False
    serialized_summary = json.dumps({"summary": ledger["summary"], "by_engine_horizon": ledger["by_engine_horizon"]})
    for forbidden in ("brier_score", "log_loss", "directional_accuracy", "ece_10_bin"):
        assert forbidden not in serialized_summary
