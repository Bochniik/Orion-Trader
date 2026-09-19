from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "evals" / "adaptive_challenger_registry.py"
SPEC = importlib.util.spec_from_file_location("adaptive_challenger_registry", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _spec():
    return {
        "engine_family": "regular_hours",
        "hypothesis": "High-confidence 1h errors cluster in a repeatable regime.",
        "change_summary": "Add a research-only regime feature and recalibrate the challenger.",
        "development_evidence_cutoff_utc": "2026-09-19T11:00:00+00:00",
        "forward_cutoff_utc": "2026-09-20T13:30:00+00:00",
        "code_sha": "abc123",
        "model_artifact_sha256": "def456",
        "horizons": ["1h"],
        "evaluation_protocol": {
            "contract": "orion-intraday-challenger-tournament-v1",
            "minimum_observations": 80,
            "minimum_sessions": 8,
        },
    }


def test_registration_is_deterministic_and_integrity_checked():
    first = MODULE.register_candidate(_spec(), registered_at_utc="2026-09-19T12:00:00+00:00")
    second = MODULE.register_candidate(_spec(), registered_at_utc="2026-09-19T12:30:00+00:00")
    assert first["candidate_id"] == second["candidate_id"]
    assert first["immutable_material_sha256"] == second["immutable_material_sha256"]
    MODULE.validate_registration(first)

    tampered = copy.deepcopy(first)
    tampered["candidate"]["hypothesis"] = "Changed after registration"
    with pytest.raises(ValueError, match="integrity mismatch"):
        MODULE.validate_registration(tampered)


def test_forward_cutoff_must_be_after_development_evidence():
    spec = _spec()
    spec["forward_cutoff_utc"] = spec["development_evidence_cutoff_utc"]
    with pytest.raises(ValueError, match="strictly later"):
        MODULE.register_candidate(spec, registered_at_utc="2026-09-19T10:00:00+00:00")


def test_registration_must_happen_before_forward_cutoff():
    with pytest.raises(ValueError, match="registered no later"):
        MODULE.register_candidate(_spec(), registered_at_utc="2026-09-21T00:00:00+00:00")


def test_pre_cutoff_or_wrong_horizon_evidence_fails_closed():
    registration = MODULE.register_candidate(
        _spec(), registered_at_utc="2026-09-19T12:00:00+00:00"
    )
    clean = [
        {"timestamp": "2026-09-21T14:00:00+00:00", "horizon": "1h"},
        {"prediction_time_utc": "2026-09-22T14:00:00+00:00", "horizon": "1h"},
    ]
    assert MODULE.assert_forward_evidence_eligible(registration, clean)["forward_evidence_eligible"] is True

    contaminated = clean + [
        {"timestamp": "2026-09-20T13:30:00+00:00", "horizon": "1h"},
        {"timestamp": "2026-09-23T14:00:00+00:00", "horizon": "30m"},
    ]
    result = MODULE.assert_forward_evidence_eligible(registration, contaminated)
    assert result["forward_evidence_eligible"] is False
    assert result["at_or_before_cutoff_count"] == 1
    assert result["wrong_horizon_count"] == 1


def test_empty_evidence_is_not_forward_eligible():
    registration = MODULE.register_candidate(
        _spec(), registered_at_utc="2026-09-19T12:00:00+00:00"
    )
    assert MODULE.assert_forward_evidence_eligible(registration, [])["forward_evidence_eligible"] is False
