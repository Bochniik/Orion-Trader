from __future__ import annotations

import pytest

from scripts.audit_regular_hours_session_cadence import (
    EXPECTED_SCHEDULED_ARTIFACTS_PER_SESSION,
    SessionCadenceError,
    build_cadence_report,
)


def _health(counts: dict[str, int]) -> dict:
    return {
        "score_blind": True,
        "metrics_exposed": False,
        "by_session": {session: {"artifact_count": count} for session, count in counts.items()},
    }


def test_cadence_requires_all_seven_scheduled_rth_observations() -> None:
    report = build_cadence_report(_health({"2026-09-21": 7, "2026-09-22": 3}))
    assert EXPECTED_SCHEDULED_ARTIFACTS_PER_SESSION == 7
    assert report["cadence_sufficient_session_count"] == 1
    assert report["cadence_insufficient_session_count"] == 1
    assert report["sessions"]["2026-09-21"]["cadence_sufficient"] is True
    assert report["sessions"]["2026-09-22"]["artifact_coverage_fraction"] == pytest.approx(3 / 7, abs=1e-6)
    assert report["model_performance_evidence"] is False
    assert report["promotion_authorized"] is False


def test_empty_evidence_does_not_fabricate_coverage() -> None:
    report = build_cadence_report(_health({}))
    assert report["session_count"] == 0
    assert report["cadence_sufficient_fraction"] is None


def test_score_exposing_input_fails_closed() -> None:
    payload = _health({"2026-09-21": 7})
    payload["metrics_exposed"] = True
    with pytest.raises(SessionCadenceError, match="score-blind"):
        build_cadence_report(payload)


def test_malformed_session_row_fails_closed() -> None:
    payload = _health({})
    payload["by_session"] = {"2026-09-21": "bad"}
    with pytest.raises(SessionCadenceError, match="objects"):
        build_cadence_report(payload)
