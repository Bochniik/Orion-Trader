from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Focused CI executes pytest from backend/. Add the repository root explicitly so
# the production-style backend.evals imports below resolve exactly as they do
# when Orion is launched from the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.evals.adaptive_challenger_registry import validate_registration
from backend.evals.adaptive_hypothesis_candidate import build_candidate_spec, build_registration


def _diagnostics():
    return {
        "contract": "orion-adaptive-research-diagnostics-v1",
        "created_at_utc": "2026-09-20T20:00:00+00:00",
        "engine": "regular_hours_v3_1",
        "safety": {"same_evidence_promotion_forbidden": True},
        "candidate_failure_patterns": [
            {
                "horizon": "15m",
                "dimension": "confidence_band",
                "value": "80-90",
                "observations": 24,
                "distinct_sessions": 6,
                "error_rate": 0.5,
                "baseline_error_rate": 0.25,
                "excess_error_rate": 0.25,
                "status": "candidate_failure_pattern",
            }
        ],
    }


def _kwargs():
    return {
        "pattern_index": 0,
        "change_summary": "Bound confidence in the diagnosed segment only.",
        "code_sha": "abc123",
        "forward_cutoff_utc": "2026-09-21T13:30:00+00:00",
        "evaluation_contract": "orion-intraday-challenger-tournament-v1",
    }


def test_build_registration_is_bounded_and_registry_valid():
    result = build_registration(
        _diagnostics(), registered_at_utc="2026-09-20T21:00:00+00:00", **_kwargs()
    )
    registration = result["registration"]
    validated = validate_registration(registration)
    assert result["safety"]["automatic_promotion_allowed"] is False
    assert validated["candidate"]["horizons"] == ["15m"]
    selected = validated["candidate"]["evaluation_protocol"]["selected_failure_pattern"]
    assert selected["dimension"] == "confidence_band"
    assert selected["value"] == "80-90"
    assert validated["candidate"]["development_evidence_cutoff_utc"] == "2026-09-20T20:00:00+00:00"


def test_rejects_forward_cutoff_not_after_development_evidence():
    kwargs = _kwargs()
    kwargs["forward_cutoff_utc"] = "2026-09-20T20:00:00+00:00"
    with pytest.raises(ValueError, match="forward cutoff must be later"):
        build_candidate_spec(_diagnostics(), **kwargs)


def test_rejects_diagnostics_without_same_evidence_guard():
    diagnostics = _diagnostics()
    diagnostics["safety"] = {"same_evidence_promotion_forbidden": False}
    with pytest.raises(ValueError, match="same-evidence promotion"):
        build_candidate_spec(diagnostics, **_kwargs())


def test_rejects_unqualified_or_tampered_pattern():
    diagnostics = _diagnostics()
    diagnostics["candidate_failure_patterns"][0]["status"] = "insufficient_evidence"
    with pytest.raises(ValueError, match="not an eligible"):
        build_candidate_spec(diagnostics, **_kwargs())


def test_rejects_unsupported_dimension():
    diagnostics = _diagnostics()
    diagnostics["candidate_failure_patterns"][0]["dimension"] = "future_return"
    with pytest.raises(ValueError, match="incomplete or unsupported"):
        build_candidate_spec(diagnostics, **_kwargs())


def test_rejects_empty_failure_pattern_set():
    diagnostics = _diagnostics()
    diagnostics["candidate_failure_patterns"] = []
    with pytest.raises(ValueError, match="no eligible"):
        build_candidate_spec(diagnostics, **_kwargs())
