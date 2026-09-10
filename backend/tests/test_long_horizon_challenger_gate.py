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
            if strong:
                p = 78.0 if actual else 22.0
            else:
                p = 58.0 if actual else 42.0
            rows.append(
                {
                    "timestamp": f"2026-09-{day:02d}T{14 + index // 6:02d}:{(index % 6) * 5:02d}:00+00:00",
                    "p_up": p,
                    "actual_up": actual,
                }
            )
    return rows


def _report(*, strong: bool, start_day: int):
    records = _records(strong=strong, start_day=start_day)
    return {
        "prediction_records": {
            "30m": [],
            "1h": [],
            "3h": records,
            "5h": records,
        }
    }


def test_historical_screen_can_never_become_forward_eligible():
    result = MODULE.evaluate_long_horizon_candidate(
        _report(strong=False, start_day=1),
        _report(strong=True, start_day=1),
        evidence_mode="historical_screen",
        min_observations=80,
        min_sessions=8,
        bootstrap_samples=200,
    )
    assert result["paired_tournament"]["research_conclusion"] == "challenger_research_eligible"
    assert result["forward_research_eligible"] is False
    assert result["research_conclusion"] == "historical_screen_only"
    assert result["promotion_allowed"] is False


def test_forward_holdout_rejects_any_pre_registration_observation():
    result = MODULE.evaluate_long_horizon_candidate(
        _report(strong=False, start_day=1),
        _report(strong=True, start_day=1),
        evidence_mode="forward_holdout",
        min_observations=80,
        min_sessions=8,
        bootstrap_samples=100,
    )
    assert result["forward_coverage"]["all_required_horizons_forward_only"] is False
    assert result["forward_research_eligible"] is False
    assert result["research_conclusion"] == "forward_holdout_contaminated_or_missing"


def test_forward_holdout_can_pass_only_on_pre_registered_3h_and_5h():
    incumbent = _report(strong=False, start_day=11)
    challenger = _report(strong=True, start_day=11)
    result = MODULE.evaluate_long_horizon_candidate(
        incumbent,
        challenger,
        evidence_mode="forward_holdout",
        min_observations=80,
        min_sessions=8,
        bootstrap_samples=200,
    )
    assert result["pre_registered_horizons"] == ["3h", "5h"]
    assert result["paired_tournament"]["horizons_required"] == ["3h", "5h"]
    assert result["paired_tournament"]["eligible_horizons"] == 2
    assert result["forward_coverage"]["all_required_horizons_forward_only"] is True
    assert result["forward_research_eligible"] is True
    assert result["research_conclusion"] == "long_horizon_challenger_research_eligible"


def test_missing_required_horizon_fails_closed():
    incumbent = _report(strong=False, start_day=11)
    challenger = _report(strong=True, start_day=11)
    challenger["prediction_records"]["5h"] = []
    result = MODULE.evaluate_long_horizon_candidate(
        incumbent,
        challenger,
        evidence_mode="forward_holdout",
        min_observations=80,
        min_sessions=8,
        bootstrap_samples=100,
    )
    assert result["forward_coverage"]["all_required_horizons_forward_only"] is False
    assert result["forward_research_eligible"] is False


def test_invalid_evidence_mode_is_rejected():
    with pytest.raises(ValueError, match="evidence_mode"):
        MODULE.evaluate_long_horizon_candidate(
            _report(strong=False, start_day=11),
            _report(strong=True, start_day=11),
            evidence_mode="reuse_old_holdout",
            bootstrap_samples=50,
        )
