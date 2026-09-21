from datetime import datetime, timedelta, timezone

import pytest

from backend.evals.adaptive_challenger_registry import register_candidate
from backend.evals.adaptive_tournament_entry import compare_registered_challenger


def _registration():
    cutoff = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    return register_candidate(
        {
            "engine_family": "regular_hours",
            "hypothesis": "test",
            "change_summary": "test candidate",
            "development_evidence_cutoff_utc": (cutoff - timedelta(days=1)).isoformat(),
            "forward_cutoff_utc": cutoff.isoformat(),
            "code_sha": "abc123",
            "horizons": ["15m"],
            "evaluation_protocol": {
                "contract": "test-v1",
                "min_forward_observations": 2,
                "min_forward_distinct_sessions": 2,
            },
        },
        registered_at_utc=(cutoff - timedelta(hours=1)).isoformat(),
    )


def _evidence(day: int, symbol: str):
    ts = datetime(2026, 9, 20 + day, 14, tzinfo=timezone.utc)
    return {
        "prediction_time_utc": ts.isoformat(),
        "session_date": ts.date().isoformat(),
        "symbol": symbol,
        "horizon": "15m",
    }


def _report(probabilities):
    rows = []
    for day, (symbol, probability, actual) in enumerate(probabilities, start=1):
        ts = datetime(2026, 9, 20 + day, 14, tzinfo=timezone.utc)
        rows.append({"timestamp": ts.isoformat(), "symbol": symbol, "p_up": probability, "actual_up": actual})
    return {"prediction_records": {"15m": rows}}


def test_scores_only_after_positive_readiness():
    registration = _registration()
    evidence = [_evidence(1, "AAPL"), _evidence(2, "MSFT")]
    incumbent = _report([("AAPL", 55, 1), ("MSFT", 45, 0)])
    challenger = _report([("AAPL", 65, 1), ("MSFT", 35, 0)])
    result = compare_registered_challenger(
        registration,
        evidence,
        incumbent,
        challenger,
        bootstrap_samples=20,
    )
    assert result["readiness"]["tournament_ready"] is True
    assert result["tournament"]["horizons_required"] == ["15m"]
    assert result["safety"]["readiness_required_before_scoring"] is True


def test_rejects_scoring_when_forward_cohort_is_not_ready():
    with pytest.raises(ValueError, match="not tournament-ready"):
        compare_registered_challenger(
            _registration(),
            [_evidence(1, "AAPL")],
            _report([("AAPL", 55, 1)]),
            _report([("AAPL", 65, 1)]),
            bootstrap_samples=20,
        )


def test_rejects_caller_horizon_drift():
    registration = _registration()
    evidence = [_evidence(1, "AAPL"), _evidence(2, "MSFT")]
    with pytest.raises(ValueError, match="exactly match preregistered"):
        compare_registered_challenger(
            registration,
            evidence,
            _report([("AAPL", 55, 1), ("MSFT", 45, 0)]),
            _report([("AAPL", 65, 1), ("MSFT", 35, 0)]),
            horizons=["30m"],
            bootstrap_samples=20,
        )
