from datetime import datetime, timedelta, timezone

from backend.evals.adaptive_challenger_registry import register_candidate
from backend.evals.adaptive_forward_evidence import assess_forward_evidence_readiness


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
            "evaluation_protocol": {"contract": "test-v1"},
        },
        registered_at_utc=(cutoff - timedelta(hours=1)).isoformat(),
    )


def _row(day: int, symbol: str = "AAPL"):
    ts = datetime(2026, 9, 20 + day, 14, tzinfo=timezone.utc)
    return {
        "prediction_time_utc": ts.isoformat(),
        "session_date": ts.date().isoformat(),
        "symbol": symbol,
        "horizon": "15m",
    }


def test_ready_only_after_sample_and_session_contract():
    result = assess_forward_evidence_readiness(
        _registration(), [_row(1, "AAPL"), _row(2, "MSFT")], min_observations=2, min_distinct_sessions=2
    )
    assert result["tournament_ready"] is True
    assert result["distinct_sessions"] == 2


def test_rejects_pre_cutoff_contamination():
    row = _row(1)
    row["prediction_time_utc"] = "2026-09-20T12:00:00+00:00"
    result = assess_forward_evidence_readiness(_registration(), [row], min_observations=1, min_distinct_sessions=1)
    assert result["tournament_ready"] is False
    assert result["at_or_before_cutoff_count"] == 1


def test_rejects_missing_session_identity():
    row = _row(1)
    row.pop("session_date")
    result = assess_forward_evidence_readiness(_registration(), [row], min_observations=1, min_distinct_sessions=1)
    assert result["tournament_ready"] is False
    assert result["missing_session_count"] == 1


def test_rejects_duplicate_observations():
    row = _row(1)
    result = assess_forward_evidence_readiness(_registration(), [row, dict(row)], min_observations=2, min_distinct_sessions=1)
    assert result["tournament_ready"] is False
    assert result["duplicate_observation_count"] == 1


def test_rejects_insufficient_session_coverage():
    rows = [_row(1, "AAPL"), _row(1, "MSFT")]
    result = assess_forward_evidence_readiness(_registration(), rows, min_observations=2, min_distinct_sessions=2)
    assert result["tournament_ready"] is False
    assert result["distinct_sessions"] == 1
