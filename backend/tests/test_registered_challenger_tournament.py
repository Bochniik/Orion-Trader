from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from evals.adaptive_challenger_registry import register_candidate
from evals.registered_challenger_tournament import compare_registered_reports


def _registration(horizons=("1h",), cutoff="2026-09-10T14:00:00+00:00"):
    return register_candidate(
        {
            "engine_family": "regular_hours",
            "hypothesis": "bounded calibration challenger",
            "change_summary": "research-only calibration variant",
            "development_evidence_cutoff_utc": "2026-09-09T20:00:00+00:00",
            "forward_cutoff_utc": cutoff,
            "code_sha": "abc123",
            "horizons": list(horizons),
            "evaluation_protocol": {"contract": "orion-intraday-challenger-tournament-v1"},
        },
        registered_at_utc="2026-09-10T13:00:00+00:00",
    )


def _reports(*, start="2026-09-11T14:00:00+00:00", horizon="1h", count=8):
    base = datetime.fromisoformat(start)
    incumbent = []
    challenger = []
    for index in range(count):
        timestamp = (base + timedelta(days=index)).isoformat()
        actual = index % 2
        incumbent.append({"timestamp": timestamp, "symbol": "AAPL", "p_up": 60 if actual else 40, "actual_up": actual})
        challenger.append({"timestamp": timestamp, "symbol": "AAPL", "p_up": 70 if actual else 30, "actual_up": actual})
    return (
        {"prediction_records": {horizon: incumbent}},
        {"prediction_records": {horizon: challenger}},
    )


def test_registered_forward_evidence_reaches_existing_tournament():
    registration = _registration()
    incumbent, challenger = _reports()
    result = compare_registered_reports(
        registration,
        incumbent,
        challenger,
        min_observations=1,
        min_sessions=1,
        bootstrap_samples=100,
    )
    assert result["contract"] == "orion-registered-challenger-tournament-v1"
    assert result["candidate_id"] == registration["candidate_id"]
    assert result["forward_evidence"]["forward_evidence_eligible"] is True
    assert result["registration_required"] is True
    assert result["runtime_modified"] is False
    assert result["automatic_promotion_allowed"] is False
    assert result["tournament"]["horizons_required"] == ["1h"]


def test_rejects_any_pre_cutoff_challenger_evidence():
    registration = _registration()
    incumbent, challenger = _reports(start="2026-09-10T14:00:00+00:00", count=2)
    with pytest.raises(ValueError, match="at_or_before_cutoff_count=1"):
        compare_registered_reports(registration, incumbent, challenger, min_observations=1, min_sessions=1)


def test_rejects_tournament_horizon_drift_from_registration():
    registration = _registration(horizons=("1h",))
    incumbent, challenger = _reports()
    with pytest.raises(ValueError, match="exactly match"):
        compare_registered_reports(registration, incumbent, challenger, horizons=("30m",))


def test_rejects_mutated_registration_before_scoring():
    registration = _registration()
    registration["candidate"]["code_sha"] = "mutated"
    incumbent, challenger = _reports()
    with pytest.raises(ValueError, match="integrity mismatch"):
        compare_registered_reports(registration, incumbent, challenger)


def test_rejects_empty_forward_evidence():
    registration = _registration()
    empty = {"prediction_records": {"1h": []}}
    with pytest.raises(ValueError, match="observations=0"):
        compare_registered_reports(registration, empty, empty, min_observations=1, min_sessions=1)
