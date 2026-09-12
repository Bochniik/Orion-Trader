from pathlib import Path
import copy
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from evaluate_premarket_v5_research_gate import (
    DEFAULT_TARGETS,
    GATE_SOURCE_RELATIVE,
    canonical_json_sha256,
    evaluate_bound_report,
    evaluate_report,
    file_sha256,
    verify_validation_manifest,
)
from premarket_directional_v4_common import PREMARKET_TARGETS


def _passing_target():
    return {
        "fold_count": 5,
        "evaluable_folds": 5,
        "positive_accuracy_folds": 4,
        "positive_signed_return_folds": 4,
        "events": 80,
        "directional_quality": {
            "samples": 1000,
            "brier_improvement": 0.006,
            "log_loss_improvement": 0.012,
        },
        "pooled": {
            "directional_accuracy": 0.56,
            "mean_signed_return_pct": 0.08,
        },
    }


def _passing_report():
    return {"targets": {target: _passing_target() for target in DEFAULT_TARGETS}}


def _write_bound_evidence(tmp_path: Path):
    report_path = tmp_path / "validation.json"
    report_path.write_text(json.dumps(_passing_report()), encoding="utf-8")
    gate_source = tmp_path / "gate.py"
    gate_source.write_text("gate-v3\n", encoding="utf-8")
    sources = {
        GATE_SOURCE_RELATIVE: file_sha256(gate_source),
        "scripts/run_premarket_v5_validation.py": "a" * 64,
    }
    material = {
        "runner_version": "premarket-v5-validation-lineage-5",
        "validator": "validate_premarket_directional_v5_event_nested.py",
        "targets": list(DEFAULT_TARGETS),
        "source_sha256": dict(sorted(sources.items())),
    }
    manifest = {
        **material,
        "decision_grade": True,
        "target_contract": "shared_PREMARKET_TARGETS_exact",
        "supported_targets": list(DEFAULT_TARGETS),
        "validation_report_sha256": file_sha256(report_path),
        "execution_identity_sha256": canonical_json_sha256(material),
    }
    manifest_path = tmp_path / "validation.json.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return report_path, manifest_path, gate_source


def test_gate_required_targets_share_the_validator_contract():
    assert DEFAULT_TARGETS == tuple(PREMARKET_TARGETS)
    assert DEFAULT_TARGETS == ("premarket_5m", "premarket_15m", "premarket_30m")


def test_all_required_targets_can_become_research_review_eligible():
    decision = evaluate_report(_passing_report())

    assert decision["eligible"] is True
    assert decision["decision"] == "eligible_for_research_promotion_review"
    assert decision["scope"] == "research_only_no_live_deployment"
    assert decision["required_targets"] == list(PREMARKET_TARGETS)
    assert decision["reasons"] == []


def test_missing_required_target_fails_closed():
    report = _passing_report()
    missing = DEFAULT_TARGETS[-1]
    del report["targets"][missing]

    decision = evaluate_report(report)

    assert decision["eligible"] is False
    assert f"{missing}:required_target_missing" in decision["reasons"]


def test_probability_metrics_must_beat_train_only_baseline():
    report = _passing_report()
    report["targets"]["premarket_15m"]["directional_quality"]["brier_improvement"] = 0.0
    report["targets"]["premarket_15m"]["directional_quality"]["log_loss_improvement"] = -0.001

    decision = evaluate_report(report)

    assert decision["eligible"] is False
    reasons = decision["reasons"]
    assert "premarket_15m:brier_not_better_than_train_prevalence_baseline" in reasons
    assert "premarket_15m:log_loss_not_better_than_train_prevalence_baseline" in reasons


def test_fold_stability_requires_strict_majority():
    report = _passing_report()
    result = report["targets"]["premarket_30m"]
    result["evaluable_folds"] = 4
    result["positive_accuracy_folds"] = 2
    result["positive_signed_return_folds"] = 2

    decision = evaluate_report(report)

    assert decision["eligible"] is False
    assert "premarket_30m:directional_accuracy_not_positive_in_majority_of_evaluable_folds" in decision["reasons"]
    assert "premarket_30m:signed_return_not_positive_in_majority_of_evaluable_folds" in decision["reasons"]


def test_missing_or_non_finite_metrics_fail_closed():
    report = _passing_report()
    result = report["targets"]["premarket_5m"]
    result["directional_quality"]["brier_improvement"] = float("nan")
    result["pooled"]["directional_accuracy"] = None

    decision = evaluate_report(report)

    assert decision["eligible"] is False
    assert "premarket_5m:brier_improvement_missing_or_non_finite" in decision["reasons"]
    assert "premarket_5m:pooled_directional_accuracy_missing_or_non_finite" in decision["reasons"]


def test_gate_does_not_mutate_validation_report():
    report = _passing_report()
    original = copy.deepcopy(report)

    evaluate_report(report)

    assert report == original


def test_bound_gate_accepts_exact_report_manifest_and_execution_identity(tmp_path):
    report, manifest, gate_source = _write_bound_evidence(tmp_path)

    decision = evaluate_bound_report(report, manifest, gate_source_path=gate_source)

    assert decision["eligible"] is True
    evidence = decision["validation_evidence"]
    assert evidence["validation_report_sha256"] == file_sha256(report)
    assert evidence["validation_manifest_sha256"] == file_sha256(manifest)
    assert len(evidence["decision_evidence_identity_sha256"]) == 64


def test_bound_gate_rejects_report_changed_after_validation_manifest(tmp_path):
    report, manifest, gate_source = _write_bound_evidence(tmp_path)
    report.write_text(json.dumps({"targets": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="report SHA-256"):
        verify_validation_manifest(report, manifest, gate_source_path=gate_source)


def test_bound_gate_rejects_tampered_execution_identity(tmp_path):
    report, manifest, gate_source = _write_bound_evidence(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["execution_identity_sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="execution identity"):
        verify_validation_manifest(report, manifest, gate_source_path=gate_source)


def test_bound_gate_rejects_target_contract_drift(tmp_path):
    report, manifest, gate_source = _write_bound_evidence(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["targets"] = list(DEFAULT_TARGETS[:-1])
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="target set/order"):
        verify_validation_manifest(report, manifest, gate_source_path=gate_source)


def test_bound_gate_rejects_different_gate_source_than_validation_fingerprinted(tmp_path):
    report, manifest, gate_source = _write_bound_evidence(tmp_path)
    gate_source.write_text("changed-gate-code\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Research gate source SHA-256"):
        verify_validation_manifest(report, manifest, gate_source_path=gate_source)
