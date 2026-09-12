from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_premarket_v5_validation import (
    file_sha256,
    verify_dataset_lineage,
    verify_preflight_binding,
    write_report_manifest,
    write_research_gate_decision,
)


def _write_manifest(dataset: Path, *, source_status="verified_source_manifest", dataset_sha=None):
    manifest = {
        "builder_version": "test-builder",
        "target_schema_version": "horizon_aware_continuous_v2",
        "source_lineage_status": source_status,
        "source_csv_sha256": "raw-sha",
        "source_manifest_sha256": "raw-manifest-sha",
        "dataset_csv_sha256": dataset_sha or file_sha256(dataset),
    }
    path = dataset.with_suffix(dataset.suffix + ".manifest.json")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _write_preflight(dataset: Path, *, status="PASS", allowed=True, csv_sha=None, manifest_sha=None):
    manifest = dataset.with_suffix(dataset.suffix + ".manifest.json")
    payload = {
        "contract": "orion-premarket-v5-decision-preflight-v2",
        "status": status,
        "decision_grade_validation_allowed": allowed,
        "dataset_identity": {
            "dataset_csv": {
                "path": str(dataset),
                "exists": True,
                "sha256": csv_sha or file_sha256(dataset),
            },
            "dataset_manifest": {
                "path": str(manifest),
                "exists": True,
                "sha256": manifest_sha or file_sha256(manifest),
            },
        },
    }
    path = dataset.parent / "preflight.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _passing_validation_report():
    target = {
        "fold_count": 3,
        "evaluable_folds": 3,
        "positive_accuracy_folds": 2,
        "positive_signed_return_folds": 2,
        "events": 30,
        "directional_quality": {
            "samples": 200,
            "brier_improvement": 0.004,
            "log_loss_improvement": 0.008,
        },
        "pooled": {
            "directional_accuracy": 0.54,
            "mean_signed_return_pct": 0.05,
        },
    }
    return {
        "targets": {
            name: dict(target)
            for name in ("premarket_5m", "premarket_15m", "premarket_30m", "premarket_60m")
        }
    }


def test_verify_dataset_lineage_accepts_verified_hash_chain(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,value\nAAPL,1\n", encoding="utf-8")
    manifest_path = _write_manifest(dataset)

    lineage = verify_dataset_lineage(dataset)

    assert lineage["dataset_csv_sha256"] == file_sha256(dataset)
    assert lineage["dataset_manifest_sha256"] == file_sha256(manifest_path)
    assert lineage["source_lineage_status"] == "verified_source_manifest"
    assert lineage["source_csv_sha256"] == "raw-sha"


def test_verify_dataset_lineage_rejects_missing_manifest(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,value\nAAPL,1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest is required"):
        verify_dataset_lineage(dataset)


def test_verify_dataset_lineage_rejects_stale_dataset_hash(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,value\nAAPL,1\n", encoding="utf-8")
    _write_manifest(dataset, dataset_sha="0" * 64)

    with pytest.raises(ValueError, match="does not match"):
        verify_dataset_lineage(dataset)


def test_verify_dataset_lineage_rejects_unverified_raw_source(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,value\nAAPL,1\n", encoding="utf-8")
    _write_manifest(dataset, source_status="unverified_no_source_manifest")

    with pytest.raises(ValueError, match="verified raw-source lineage"):
        verify_dataset_lineage(dataset)


def test_preflight_binding_accepts_exact_dataset_and_manifest(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,value\nAAPL,1\n", encoding="utf-8")
    _write_manifest(dataset)
    lineage = verify_dataset_lineage(dataset)
    preflight_path = _write_preflight(dataset)

    binding = verify_preflight_binding(preflight_path, dataset, lineage)

    assert binding["preflight_sha256"] == file_sha256(preflight_path)
    assert binding["preflight_dataset_csv_sha256"] == lineage["dataset_csv_sha256"]
    assert binding["preflight_dataset_manifest_sha256"] == lineage["dataset_manifest_sha256"]


def test_preflight_binding_rejects_different_dataset_bytes(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,value\nAAPL,1\n", encoding="utf-8")
    _write_manifest(dataset)
    preflight_path = _write_preflight(dataset)
    dataset.write_text("ticker,value\nAAPL,2\n", encoding="utf-8")
    _write_manifest(dataset)
    lineage = verify_dataset_lineage(dataset)

    with pytest.raises(ValueError, match="dataset SHA-256"):
        verify_preflight_binding(preflight_path, dataset, lineage)


def test_preflight_binding_rejects_changed_dataset_manifest(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,value\nAAPL,1\n", encoding="utf-8")
    manifest = _write_manifest(dataset)
    preflight_path = _write_preflight(dataset)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["builder_version"] = "changed-after-preflight"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    lineage = verify_dataset_lineage(dataset)

    with pytest.raises(ValueError, match="dataset-manifest SHA-256"):
        verify_preflight_binding(preflight_path, dataset, lineage)


def test_preflight_binding_rejects_failed_or_unauthorized_artifact(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,value\nAAPL,1\n", encoding="utf-8")
    _write_manifest(dataset)
    lineage = verify_dataset_lineage(dataset)
    preflight_path = _write_preflight(dataset, status="FAIL", allowed=False)

    with pytest.raises(ValueError, match="did not authorize"):
        verify_preflight_binding(preflight_path, dataset, lineage)


def test_report_manifest_chains_preflight_dataset_report_and_gate_hashes(tmp_path):
    dataset = tmp_path / "dataset.csv"
    dataset.write_text("ticker,value\nAAPL,1\n", encoding="utf-8")
    _write_manifest(dataset)
    lineage = verify_dataset_lineage(dataset)
    preflight_path = _write_preflight(dataset)
    preflight = verify_preflight_binding(preflight_path, dataset, lineage)

    report = tmp_path / "report.json"
    report.write_text(json.dumps(_passing_validation_report()), encoding="utf-8")
    gate_path = write_research_gate_decision(report)

    manifest_path = write_report_manifest(
        report,
        dataset=dataset,
        lineage=lineage,
        preflight=preflight,
        targets=["premarket_5m", "premarket_15m", "premarket_30m", "premarket_60m"],
        gate_path=gate_path,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["dataset_csv_sha256"] == file_sha256(dataset)
    assert payload["preflight_sha256"] == file_sha256(preflight_path)
    assert payload["validation_report_sha256"] == file_sha256(report)
    assert payload["research_gate_sha256"] == file_sha256(gate_path)
    assert payload["research_gate_decision"] == "eligible_for_research_promotion_review"
    assert payload["research_gate_eligible"] is True
    serialized = manifest_path.read_text(encoding="utf-8").lower()
    assert "api_key" not in serialized
    assert "secret" not in serialized


def test_gate_decision_rejects_incomplete_validation_report(tmp_path):
    report = tmp_path / "report.json"
    report.write_text('{"targets": {}}\n', encoding="utf-8")

    gate_path = write_research_gate_decision(report)
    payload = json.loads(gate_path.read_text(encoding="utf-8"))

    assert payload["eligible"] is False
    assert payload["decision"] == "reject_research_promotion"
    assert any("required_target_missing" in reason for reason in payload["reasons"])
