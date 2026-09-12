from pathlib import Path

import pandas as pd

from scripts import run_premarket_v5_decision_preflight as preflight


def _write_dataset(path: Path) -> None:
    pd.DataFrame([{"x": 1}]).to_csv(path, index=False)


def test_preflight_passes_only_when_both_gates_pass(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.csv"
    _write_dataset(dataset)
    monkeypatch.setattr(preflight, "audit_dataset_provenance", lambda _: {"status": "PASS", "blockers": []})
    monkeypatch.setattr(preflight, "audit_dataset", lambda _: {"status": "PASS", "blockers": [], "warnings": []})

    report = preflight.run_preflight(dataset)

    assert report["status"] == "PASS"
    assert report["decision_grade_validation_allowed"] is True
    assert report["next_action"] == "run_premarket_v5_event_nested_validation"
    assert report["promotion_authorized"] is False
    assert report["runtime_modified"] is False


def test_provenance_failure_blocks_validation_even_when_readiness_passes(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.csv"
    _write_dataset(dataset)
    monkeypatch.setattr(preflight, "audit_dataset_provenance", lambda _: {"status": "FAIL", "blockers": ["bad lineage"]})
    monkeypatch.setattr(preflight, "audit_dataset", lambda _: {"status": "PASS", "blockers": [], "warnings": []})

    report = preflight.run_preflight(dataset)

    assert report["status"] == "FAIL"
    assert report["decision_grade_validation_allowed"] is False
    assert report["gates"]["provenance"]["passed"] is False
    assert report["gates"]["readiness"]["passed"] is True
    assert report["next_action"] == "repair_dataset_or_lineage_before_model_validation"


def test_readiness_failure_blocks_validation_even_when_provenance_passes(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.csv"
    _write_dataset(dataset)
    monkeypatch.setattr(preflight, "audit_dataset_provenance", lambda _: {"status": "PASS", "blockers": []})
    monkeypatch.setattr(preflight, "audit_dataset", lambda _: {"status": "FAIL", "blockers": ["insufficient sessions"], "warnings": []})

    report = preflight.run_preflight(dataset)

    assert report["status"] == "FAIL"
    assert report["decision_grade_validation_allowed"] is False
    assert report["gates"]["provenance"]["passed"] is True
    assert report["gates"]["readiness"]["passed"] is False


def test_unreadable_dataset_fails_closed(tmp_path, monkeypatch):
    dataset = tmp_path / "missing.csv"
    monkeypatch.setattr(preflight, "audit_dataset_provenance", lambda _: {"status": "FAIL", "blockers": ["missing dataset"]})

    report = preflight.run_preflight(dataset)

    assert report["status"] == "FAIL"
    assert report["decision_grade_validation_allowed"] is False
    assert report["gates"]["readiness"]["passed"] is False
    assert "could not be parsed" in report["gates"]["readiness"]["report"]["blockers"][0]
