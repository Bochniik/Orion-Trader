from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from premarket_directional_v4_common import PREMARKET_TARGETS
from run_premarket_v5_evidence_pipeline import (
    DEFAULT_TARGETS,
    REPRODUCIBILITY_FILES,
    build_commands,
    execution_identity,
    package_versions,
    parse_symbols,
    validate_request,
    write_pipeline_manifest,
)


def test_pipeline_targets_share_validator_contract():
    assert DEFAULT_TARGETS == tuple(PREMARKET_TARGETS)
    assert DEFAULT_TARGETS == ("premarket_5m", "premarket_15m", "premarket_30m")


def test_parse_symbols_normalizes_and_deduplicates():
    assert parse_symbols(["aapl, msft", "AAPL", " nvda "]) == ["AAPL", "MSFT", "NVDA"]


def test_build_commands_runs_gate_only_after_bound_validation_manifest(tmp_path):
    raw = tmp_path / "raw.csv"
    dataset = tmp_path / "dataset.csv"
    readiness = tmp_path / "readiness.json"
    preflight = tmp_path / "preflight.json"
    validation = tmp_path / "validation.json"

    commands = build_commands(
        symbols=["AAPL", "MSFT"],
        start="2026-01-01",
        end="2026-04-30",
        feed="iex",
        raw=raw,
        dataset=dataset,
        readiness=readiness,
        preflight=preflight,
        validation=validation,
        skip_collect=False,
        targets=list(DEFAULT_TARGETS),
    )

    assert len(commands) == 6
    assert commands[0][1].endswith("collect_alpaca_extended_history.py")
    assert commands[1][1].endswith("build_premarket_training_dataset_v2.py")
    assert commands[2][1].endswith("audit_premarket_dataset_readiness.py")
    assert commands[3][1].endswith("run_premarket_v5_decision_preflight.py")
    assert commands[4][1].endswith("run_premarket_v5_validation.py")
    assert commands[5][1].endswith("evaluate_premarket_v5_research_gate.py")
    assert commands[3].index(str(dataset)) > 0
    assert commands[4][commands[4].index("--preflight") + 1] == str(preflight)
    assert commands[4][-len(DEFAULT_TARGETS):] == list(DEFAULT_TARGETS)
    assert commands[5][2] == str(validation)
    assert commands[5][commands[5].index("--manifest") + 1] == str(
        validation.with_suffix(validation.suffix + ".manifest.json")
    )
    assert commands[5][commands[5].index("--output") + 1] == str(
        validation.with_suffix(validation.suffix + ".gate.json")
    )


def test_skip_collect_still_builds_audits_preflights_validates_and_gates(tmp_path):
    commands = build_commands(
        symbols=["AAPL"],
        start="2026-01-01",
        end="2026-04-30",
        feed="iex",
        raw=tmp_path / "raw.csv",
        dataset=tmp_path / "dataset.csv",
        readiness=tmp_path / "readiness.json",
        preflight=tmp_path / "preflight.json",
        validation=tmp_path / "validation.json",
        skip_collect=True,
        targets=list(DEFAULT_TARGETS),
    )
    assert len(commands) == 5
    assert commands[0][1].endswith("build_premarket_training_dataset_v2.py")
    assert commands[2][1].endswith("run_premarket_v5_decision_preflight.py")
    assert commands[3][1].endswith("run_premarket_v5_validation.py")
    assert commands[4][1].endswith("evaluate_premarket_v5_research_gate.py")


def test_validate_request_requires_exact_complete_target_set():
    with pytest.raises(ValueError, match="exact shared PREMARKET_TARGETS"):
        validate_request("2026-01-01", "2026-04-30", "iex", ["premarket_5m"])
    with pytest.raises(ValueError, match="exact shared PREMARKET_TARGETS"):
        validate_request(
            "2026-01-01",
            "2026-04-30",
            "iex",
            [*DEFAULT_TARGETS, "premarket_60m"],
        )


def test_validate_request_rejects_reverse_dates():
    with pytest.raises(ValueError, match="on or after"):
        validate_request("2026-04-30", "2026-01-01", "iex", list(DEFAULT_TARGETS))


def test_package_versions_marks_missing_packages_without_failing():
    versions = package_versions(["pytest", "orion-package-that-does-not-exist"])
    assert versions["pytest"]
    assert versions["orion-package-that-does-not-exist"] is None


def test_execution_identity_hashes_reproducibility_files(tmp_path):
    for relative_path in REPRODUCIBILITY_FILES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative_path + "\n", encoding="utf-8")

    identity = execution_identity(tmp_path)
    assert identity["python"]["version"]
    assert identity["platform"]
    assert set(identity["code_artifacts"]) == set(REPRODUCIBILITY_FILES)
    assert all(item["exists"] for item in identity["code_artifacts"].values())
    assert all(len(item["sha256"]) == 64 for item in identity["code_artifacts"].values())


def test_pipeline_manifest_hashes_preflight_and_existing_artifacts_without_secrets(tmp_path):
    raw = tmp_path / "raw.csv"
    dataset = tmp_path / "dataset.csv"
    readiness = tmp_path / "readiness.json"
    preflight = tmp_path / "preflight.json"
    validation = tmp_path / "validation.json"
    raw.write_text("ticker,timestamp\nAAPL,2026-01-01T09:00:00Z\n", encoding="utf-8")
    dataset.write_text("ticker,session_date\nAAPL,2026-01-01\n", encoding="utf-8")
    readiness.write_text('{"status":"PASS"}\n', encoding="utf-8")
    preflight.write_text('{"status":"PASS"}\n', encoding="utf-8")
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
        preflight=preflight,
        validation=validation,
        targets=list(DEFAULT_TARGETS),
        status="COMPLETED",
        repo_root=ROOT,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "COMPLETED"
    assert payload["pipeline_version"] == "premarket-v5-evidence-pipeline-v5"
    assert payload["target_contract"] == "shared_PREMARKET_TARGETS_exact"
    assert payload["request"]["targets"] == list(PREMARKET_TARGETS)
    assert payload["artifacts"]["raw_csv"]["exists"] is True
    assert len(payload["artifacts"]["raw_csv"]["sha256"]) == 64
    assert payload["artifacts"]["decision_preflight"]["exists"] is True
    assert len(payload["artifacts"]["decision_preflight"]["sha256"]) == 64
    assert payload["execution"]["python"]["version"]
    assert payload["execution"]["packages"]["pandas"]
    assert payload["execution"]["code_artifacts"]["backend/requirements.txt"]["exists"] is True
    assert len(payload["execution"]["code_artifacts"]["backend/requirements.txt"]["sha256"]) == 64
    serialized = output.read_text(encoding="utf-8").lower()
    assert "api_key" not in serialized
    assert "secret" not in serialized
