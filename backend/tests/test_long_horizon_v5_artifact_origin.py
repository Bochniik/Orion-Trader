from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "scripts/validate_long_horizon_v5_artifact_origin.py"
    spec = importlib.util.spec_from_file_location("long_horizon_v5_artifact_origin", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load()
HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40


def _payload() -> dict:
    return {
        "lineage": {"git_commit": HEAD_SHA},
        "acquisition_provenance": {
            "contract": validator.EXPECTED_CONTRACT,
            "event_name": "schedule",
            "github_run_id": "123",
            "github_run_attempt": 2,
            "github_head_sha": HEAD_SHA,
            "workflow_commit_verified": True,
            "forward_eligible": True,
        },
    }


def _run() -> dict:
    return {
        "id": 123,
        "path": validator.EXPECTED_WORKFLOW_PATH,
        "event": "schedule",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 2,
        "head_sha": HEAD_SHA,
    }


def test_accepts_exact_scheduled_workflow_origin():
    result = validator.validate_origin(_payload(), "long-horizon-v5-paired-shadow-123", _run())
    assert result["valid"] is True
    assert result["score_blind"] is True
    assert result["github_run_attempt"] == 2
    assert result["github_head_sha"] == HEAD_SHA


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("path", ".github/workflows/other.yml", "unexpected workflow path"),
        ("event", "workflow_dispatch", "not genuine scheduled forward evidence"),
        ("conclusion", "failure", "not successfully completed"),
        ("run_attempt", 3, "run attempt does not match recovered run"),
        ("head_sha", OTHER_SHA, "head SHA does not match recovered run"),
    ],
)
def test_rejects_recovered_run_metadata_drift(field, value, message):
    run = _run()
    run[field] = value
    with pytest.raises(ValueError, match=message):
        validator.validate_origin(_payload(), "long-horizon-v5-paired-shadow-123", run)


def test_rejects_artifact_name_run_id_mismatch():
    with pytest.raises(ValueError, match="Artifact run id does not match"):
        validator.validate_origin(_payload(), "long-horizon-v5-paired-shadow-999", _run())


def test_rejects_payload_provenance_or_lineage_drift():
    payload = _payload()
    payload["acquisition_provenance"]["github_run_id"] = "999"
    with pytest.raises(ValueError, match="payload GitHub run id"):
        validator.validate_origin(payload, "long-horizon-v5-paired-shadow-123", _run())

    payload = _payload()
    payload["lineage"]["git_commit"] = OTHER_SHA
    with pytest.raises(ValueError, match="lineage commit"):
        validator.validate_origin(payload, "long-horizon-v5-paired-shadow-123", _run())


def test_rejects_non_forward_eligible_payload():
    payload = _payload()
    payload["acquisition_provenance"]["forward_eligible"] = False
    with pytest.raises(ValueError, match="not forward-eligible"):
        validator.validate_origin(payload, "long-horizon-v5-paired-shadow-123", _run())
