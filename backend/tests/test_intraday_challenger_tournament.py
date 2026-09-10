from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "evals" / "intraday_challenger_tournament.py"
SPEC = importlib.util.spec_from_file_location("intraday_challenger_tournament", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _records(*, challenger: bool, sessions: int = 10, rows_per_session: int = 10):
    records = []
    for day in range(1, sessions + 1):
        for index in range(rows_per_session):
            actual = (day + index) % 2
            if challenger:
                p = 78.0 if actual else 22.0
            else:
                p = 58.0 if actual else 42.0
            records.append(
                {
                    "timestamp": f"2026-08-{day:02d}T{14 + index // 6:02d}:{(index % 6) * 5:02d}:00+00:00",
                    "p_up": p,
                    "actual_up": actual,
                }
            )
    return records


def test_pair_records_aligns_exact_timestamps_and_rejects_outcome_mismatch():
    incumbent = _records(challenger=False, sessions=2, rows_per_session=3)
    challenger = _records(challenger=True, sessions=2, rows_per_session=3)
    challenger.append({"timestamp": "2026-08-20T14:00:00+00:00", "p_up": 90, "actual_up": 1})
    paired = MODULE.pair_records(incumbent, challenger)
    assert len(paired) == 6

    broken = copy.deepcopy(challenger)
    broken[0]["actual_up"] = 1 - broken[0]["actual_up"]
    with pytest.raises(ValueError, match="Outcome mismatch"):
        MODULE.pair_records(incumbent, broken)


def test_conflicting_duplicate_fails_closed():
    rows = _records(challenger=False, sessions=1, rows_per_session=2)
    duplicate = dict(rows[0])
    duplicate["p_up"] = 99.0
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        MODULE.pair_records(rows + [duplicate], rows)


def test_strong_challenger_is_research_eligible_with_session_block_bootstrap():
    result = MODULE.evaluate_paired_horizon(
        _records(challenger=False),
        _records(challenger=True),
        min_observations=80,
        min_sessions=8,
        bootstrap_samples=300,
        seed=7,
    )
    assert result["coverage_ok"] is True
    assert result["brier_improvement"] > 0
    assert result["log_loss_improvement"] > 0
    assert result["bootstrap"]["brier_improvement_ci95"][0] > 0
    assert result["bootstrap"]["log_loss_improvement_ci95"][0] > 0
    assert result["verdict"] == "research_eligible"


def test_better_accuracy_alone_cannot_promote_when_proper_scores_do_not_improve():
    incumbent = []
    challenger = []
    for day in range(1, 11):
        for index in range(10):
            actual = (day + index) % 2
            timestamp = f"2026-08-{day:02d}T14:{index * 5:02d}:00+00:00"
            incumbent.append({"timestamp": timestamp, "actual_up": actual, "p_up": 51 if actual else 49})
            challenger.append({"timestamp": timestamp, "actual_up": actual, "p_up": 99 if index < 8 and actual else (1 if index < 8 else (99 if not actual else 1))})
    result = MODULE.evaluate_paired_horizon(
        incumbent,
        challenger,
        min_observations=80,
        min_sessions=8,
        bootstrap_samples=200,
        seed=9,
    )
    assert result["verdict"] == "not_demonstrated"


def test_insufficient_sessions_fails_closed_even_when_scores_improve():
    result = MODULE.evaluate_paired_horizon(
        _records(challenger=False, sessions=3, rows_per_session=30),
        _records(challenger=True, sessions=3, rows_per_session=30),
        min_observations=80,
        min_sessions=8,
        bootstrap_samples=100,
    )
    assert result["paired_observations"] == 90
    assert result["distinct_sessions"] == 3
    assert result["coverage_ok"] is False
    assert result["verdict"] == "not_demonstrated"


def test_compare_reports_requires_every_horizon_to_pass():
    incumbent_records = _records(challenger=False)
    challenger_records = _records(challenger=True)
    incumbent = {"prediction_records": {h: incumbent_records for h in MODULE.HORIZONS}}
    challenger = {"prediction_records": {h: challenger_records for h in MODULE.HORIZONS}}

    result = MODULE.compare_reports(
        incumbent,
        challenger,
        min_observations=80,
        min_sessions=8,
        bootstrap_samples=150,
    )
    assert result["research_conclusion"] == "challenger_research_eligible"
    assert result["eligible_horizons"] == 4

    challenger["prediction_records"]["5h"] = challenger_records[:20]
    result = MODULE.compare_reports(
        incumbent,
        challenger,
        min_observations=80,
        min_sessions=8,
        bootstrap_samples=150,
    )
    assert result["research_conclusion"] == "challenger_not_demonstrated"
    assert result["eligible_horizons"] == 3
