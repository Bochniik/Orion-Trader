from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_premarket_v5_evidence_pipeline import (
    DEFAULT_TARGETS,
    build_commands,
    execution_identity,
    package_versions,
    parse_symbols,
    validate_request,
    write_pipeline_manifest,
)


def test_parse_symbols_normalizes_and_deduplicates():
    assert parse_symbols(["aapl, msft", "AAPL", " nvda "]) == ["AAPL", "MSFT", "NVDA"]


def test_build_commands_runs_fail_closed_readiness_before_validation(tmp_path):
    raw = tmp_path / "raw.csv"
    dataset = tmp_path / "dataset.csv"
    readiness = tmp_path / "readiness.json"
    validation = tmp_path / "validation.json"

    commands = build_commands(
        symbols=["AAPL", "MSFT"],
        start="2026-01-01",
        end="2026-04-30",
        feed="iex",
        raw=raw,
        dataset=dataset,
        readiness=readiness,
        validation=validation,
        skip_collect=False,
        targets=list(DEFAULT_TARGETS),
    )

    assert len(commands) == 4
    assert commands[0][1].endswith("collect_alpaca_extended_history.py")
    assert commands[1][1].endswith("build_premarket_training_dataset_v2.py")
    assert commands[2][1].endswith("audit_premarket_dataset_readiness.py")
    assert commands[3][1].endswith("run_premarket_v5_validation.py")
    assert commands[2].index(str(dataset)) > 0
    assert commands[3][-4:] == list(DEFAULT_TARGETS)


def test_skip_collect_still_builds_audits_and_validates(tmp_path):
    commands = build_commands(
        symbols=["AAPL"],
        start="2026-01-01",
        end="2026-04-30",
        feed="iex",
        raw=tmp_path / "raw.csv",
        dataset=tmp_path / "dataset.csv",
        readiness=tmp_path / "readiness.json",
        validation=tmp_path / "validation.json",
        skip_collect=True,
        targets=list(DEFAULT_TARGETS),
    )
    assert len(commands) == 3
    assert commands[0][1].endswith("build_premarket_training_dataset_v2.py")


def test_validate_request_requires_complete_target_set():
    with pytest.raises(ValueError, match="all four"):
        validate_request("2026-01-01", "2026-04-30", "iex", ["premarket_5m"])


def test_validate_request_rejects_reverse_dates():
    with pytest.raises(ValueError, match="on or after"):
        validate_request("2026-04-30", "2026-01-01", "iex", list(DEFAULT_TARGETS))


def test_package_versions_marks_missing_packages_without_failing():
    versions = package_versions(["pytest", "orion-package-that-does-not-exist"])
    assert versions["pytest"]
    assert versions["orion-package-that-does-not-exist"] is None


def test_execution_identity_hashes_reproducibility_files(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "backend").mkdir()
    for relative_path in [
        "scripts/collect_alpaca_extended_history.py",
        "scripts/build_premarket_training_dataset_v2.py",
        "scripts/audit_premarket_dataset_readiness.py",
        "scripts/run_premarket_v5_validation.py",
        "scripts/evaluate_premarket_v5_research_gate.py",
        "scripts/validate_premarket_directional_v5_event_nested.py",
        "scripts/premarket_directional_v5_common.py",
        "backend/requirements.txt",
    ]:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative_path + "\n", encoding="utf-8")

    identity = execution_identity(tmp_path)
    assert identity["python"]["version"]
    assert identity["platform"]
    assert set(identity["code_artifacts"]) == {
        "scripts/collect_alpaca_extended_history.py",
        "scripts/build_premarket_training_dataset_v2.py",
        "scripts/audit_premarket_dataset_readiness.py",
        "scripts/run_premarket_v5_validation.py",
        "scripts/evaluate_premarket_v5_research_gate.py",
        "scripts/validate_premarket_directional_v5_event_nested.py",
        "scripts/premarket_directional_v5_common.py",
        "backend/requirements.txt",
    }
    assert all(item["exists"] for item in identity["code_artifacts"].values())
    assert all(len(item["sha256"]) == 64 for item in identity["code_artifacts"].values())


def test_pipeline_manifest_hashes_existing_artifacts_without_secrets(tmp_path):
    raw = tmp_path / "raw.csv"
    dataset = tmp_path / "dataset.csv"
    readiness = tmp_path / "readiness.json"
    validation = tmp_path / "validation.json"
    raw.write_text("ticker,timestamp\nAAPL,2026-01-01T09:00:00Z\n", encoding="utf-8")
    dataset.write_text("ticker,session_date\nAAPL,2026-01-01\n", encoding="utf-8")
    readiness.write_text('{"status":"PASS"}\n', encoding="utf-8")
    validation.write_text('{"targets":{}}\n', encoding="utf-8")

    output = tmp_path / "pipeline.json"
    write_pipeline_manifest(
        output,
        symbols=["AAPL"],
        start="2026-01-01",
        end="2026-04-30",
        feed="iex",
        raw=raw,
        dataset=dataset,
        readiness=readiness,
        validation=validation,
        targets=list(DEFAULT_TARGETS),
        status="COMPLETED",
        repo_root=ROOT,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "COMPLETED"
    assert payload["pipeline_version"] == "premarket-v5-evidence-pipeline-v2"
    assert payload["artifacts"]["raw_csv"]["exists"] is True
    assert len(payload["artifacts"]["raw_csv"]["sha256"]) == 64
    assert payload["execution"]["python"]["version"]
    assert payload["execution"]["packages"]["pandas"]
    assert payload["execution"]["code_artifacts"]["backend/requirements.txt"]["exists"] is True
    assert len(payload["execution"]["code_artifacts"]["backend/requirements.txt"]["sha256"]) == 64
    serialized = output.read_text(encoding="utf-8").lower()
    assert "api_key" not in serialized
    assert "secret" not in serialized
