from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "evals" / "long_horizon_challenger_gate.py"
SPEC = importlib.util.spec_from_file_location("long_horizon_challenger_gate", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _records(*, strong: bool, start_day: int, sessions: int = 10, rows_per_session: int = 10):
    rows = []
    for day_offset in range(sessions):
        day = start_day + day_offset
        for index in range(rows_per_session):
            actual = (day + index) % 2
            p = (78.0 if actual else 22.0) if strong else (58.0 if actual else 42.0)
            rows.append({"timestamp": f"2026-09-{day:02d}T{14 + index // 6:02d}:{(index % 6) * 5:02d}:00+00:00", "p_up": p, "actual_up": actual})
    return rows


def _report(*, strong: bool, start_day: int, sessions: int = 10, rows_per_session: int = 10):
    records = _records(strong=strong, start_day=start_day, sessions=sessions, rows_per_session=rows_per_session)
    return {"prediction_records": {"30m": [], "1h": [], "3h": records, "5h": records}}


def _registration():
    from evals.adaptive_challenger_registry import register_candidate
    return register_candidate({
        "engine_family": "regular_hours_long_horizon",
        "hypothesis": "test long-horizon challenger",
        "change_summary": "test-only probability separation",
        "development_evidence_cutoff_utc": "2026-09-01T00:00:00+00:00",
        "forward_cutoff_utc": "2026-09-10T23:59:59+00:00",
        "code_sha": "test-sha",
        "horizons": ["3h", "5h"],
        "evaluation_protocol": {"contract": "orion-long-horizon-challenger-gate-v2"},
    }, registered_at_utc="2026-09-10T12:00:00+00:00")


def test_historical_screen_can_never_become_forward_eligible():
    result = MODULE.evaluate_long_horizon_candidate(_report(strong=False, start_day=1), _report(strong=True, start_day=1), evidence_mode="historical_screen", min_observations=80, min_sessions=8, bootstrap_samples=200)
    assert result["paired_tournament"]["research_conclusion"] == "challenger_research_eligible"
    assert result["paired_tournament"]["preregistration_required"] is False
    assert result["forward_research_eligible"] is False
    assert result["research_conclusion"] == "historical_screen_only"
    assert result["promotion_allowed"] is False


def test_forward_holdout_requires_immutable_registration():
    with pytest.raises(ValueError, match="immutable challenger registration"):
        MODULE.evaluate_long_horizon_candidate(_report(strong=False, start_day=11), _report(strong=True, start_day=11), evidence_mode="forward_holdout", bootstrap_samples=20)


def test_forward_holdout_rejects_any_pre_registration_observation():
    with pytest.raises(ValueError, match="violates immutable preregistration"):
        MODULE.evaluate_long_horizon_candidate(_report(strong=False, start_day=1), _report(strong=True, start_day=1), evidence_mode="forward_holdout", registration=_registration(), min_observations=80, min_sessions=8, bootstrap_samples=100)


def test_forward_holdout_reports_collecting_until_preregistered_sample_is_mature():
    result = MODULE.evaluate_long_horizon_candidate(_report(strong=False, start_day=11, sessions=4, rows_per_session=10), _report(strong=True, start_day=11, sessions=4, rows_per_session=10), evidence_mode="forward_holdout", registration=_registration(), min_observations=80, min_sessions=8, bootstrap_samples=100)
    assert result["forward_coverage"]["all_required_horizons_forward_only"] is True
    assert result["forward_sample_readiness"]["all_required_horizons_ready"] is False
    assert result["forward_sample_readiness"]["horizons"]["3h"]["paired_observations"] == 40
    assert result["forward_sample_readiness"]["horizons"]["3h"]["observations_remaining"] == 40
    assert result["forward_sample_readiness"]["horizons"]["3h"]["sessions_remaining"] == 4
    assert result["forward_research_eligible"] is False
    assert result["research_conclusion"] == "forward_holdout_collecting_evidence"


def test_mature_forward_sample_can_fail_as_model_not_demonstrated():
    result = MODULE.evaluate_long_horizon_candidate(_report(strong=True, start_day=11), _report(strong=False, start_day=11), evidence_mode="forward_holdout", registration=_registration(), min_observations=80, min_sessions=8, bootstrap_samples=100)
    assert result["forward_sample_readiness"]["all_required_horizons_ready"] is True
    assert result["paired_tournament"]["research_conclusion"] == "challenger_not_demonstrated"
    assert result["forward_research_eligible"] is False
    assert result["research_conclusion"] == "long_horizon_challenger_not_demonstrated"


def test_forward_holdout_can_pass_only_on_pre_registered_3h_and_5h():
    result = MODULE.evaluate_long_horizon_candidate(_report(strong=False, start_day=11), _report(strong=True, start_day=11), evidence_mode="forward_holdout", registration=_registration(), min_observations=80, min_sessions=8, bootstrap_samples=200)
    assert result["pre_registered_horizons"] == ["3h", "5h"]
    assert result["paired_tournament"]["horizons_required"] == ["3h", "5h"]
    assert result["paired_tournament"]["eligible_horizons"] == 2
    assert result["paired_tournament"]["registration_gate"]["forward_evidence_eligible"] is True
    assert result["forward_sample_readiness"]["all_required_horizons_ready"] is True
    assert result["forward_research_eligible"] is True
    assert result["research_conclusion"] == "long_horizon_challenger_research_eligible"


def test_missing_required_horizon_fails_closed():
    incumbent = _report(strong=False, start_day=11)
    challenger = _report(strong=True, start_day=11)
    challenger["prediction_records"]["5h"] = []
    with pytest.raises(ValueError, match="violates immutable preregistration"):
        MODULE.evaluate_long_horizon_candidate(incumbent, challenger, evidence_mode="forward_holdout", registration=_registration(), min_observations=80, min_sessions=8, bootstrap_samples=100)


def test_invalid_evidence_mode_is_rejected():
    with pytest.raises(ValueError, match="evidence_mode"):
        MODULE.evaluate_long_horizon_candidate(_report(strong=False, start_day=11), _report(strong=True, start_day=11), evidence_mode="reuse_old_holdout", bootstrap_samples=50)
