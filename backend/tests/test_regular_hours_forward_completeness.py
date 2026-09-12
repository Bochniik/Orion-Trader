from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

from scripts.audit_regular_hours_collection_health import PREREGISTERED_SYMBOLS
from scripts.audit_regular_hours_forward_completeness import (
    MIN_COMPLETE_SESSIONS_FOR_SCORE_INSPECTION,
    build_completeness_report,
)
from scripts.nyse_session_calendar import is_nyse_trading_day


def _artifact(*, as_of_et: str, provenance_gap: str | None = None, failed_symbol: str | None = None) -> dict:
    symbols = list(PREREGISTERED_SYMBOLS)
    rows = {}
    failures = {}
    for symbol in symbols:
        if symbol == failed_symbol:
            failures[symbol] = "RuntimeError: provider unavailable"
            continue
        aligned = symbol != provenance_gap
        rows[symbol] = {
            "symbol": symbol,
            "available": True,
            "as_of": "2026-09-11T14:05:00+00:00" if aligned else None,
            "source_timestamp_aligned": aligned,
            "source_as_of": {"v1": "2026-09-11T14:05:00+00:00", "v2": "2026-09-11T14:05:00+00:00"},
            "alignment_attempts": 1,
            "horizons": {"30m": {"probability_up": 80.0, "probability_down": 20.0, "direction": "bullish"}},
        }
    available = len(rows)
    provenance_valid = sum(row["source_timestamp_aligned"] and bool(row["as_of"]) for row in rows.values())
    return {
        "contract": "orion-regular-hours-cloud-shadow-v2",
        "runner_version": "regular-hours-v3-1-cloud-shadow-v2",
        "created_at_utc": "2026-09-11T14:05:10+00:00",
        "session_gate": {"allowed": True, "as_of_et": as_of_et, "weekday": 4, "nyse_trading_day": True, "window_et": "09:30-15:30", "reason": None},
        "symbols_requested": symbols,
        "research_only": True,
        "order_submission_enabled": False,
        "runtime_modified": False,
        "status": "completed",
        "results": {
            "symbol_count": 10,
            "available_symbol_count": available,
            "provenance_valid_symbol_count": provenance_valid,
            "alignment_retry_symbol_count": 0,
            "alignment_attempt_count": available,
            "failure_count": len(failures),
            "symbols": rows,
            "failures": failures,
        },
    }


def _complete_sessions(count: int) -> list[dict]:
    payloads = []
    session = date(2026, 7, 1)
    while len(payloads) < count:
        if is_nyse_trading_day(session):
            payloads.append(_artifact(as_of_et=f"{session.isoformat()}T10:05:00-04:00"))
        session += timedelta(days=1)
    return payloads


def test_complete_session_requires_full_standard_provenance_and_zero_failures() -> None:
    complete = _artifact(as_of_et="2026-09-11T10:05:00-04:00")
    incomplete = _artifact(as_of_et="2026-09-10T10:05:00-04:00", provenance_gap="AAPL")
    report = build_completeness_report([complete, incomplete])

    assert report["contract"] == "orion-regular-hours-collection-health-v3"
    assert report["complete_standard_session_count"] == 1
    assert report["incomplete_standard_session_count"] == 1
    assert report["complete_standard_sessions"] == ["2026-09-11"]
    assert report["incomplete_standard_sessions"] == ["2026-09-10"]
    assert report["by_session"]["2026-09-11"]["complete_standard_session"] is True
    assert report["by_session"]["2026-09-10"]["complete_standard_session"] is False
    assert report["score_inspection_readiness_threshold_defined"] is True
    assert report["score_inspection_required_complete_sessions"] == 30
    assert report["ready_for_score_inspection"] is False
    assert report["promotion_authorized"] is False


def test_one_failed_symbol_makes_session_incomplete() -> None:
    report = build_completeness_report([
        _artifact(as_of_et="2026-09-11T10:05:00-04:00", failed_symbol="NVDA")
    ])
    assert report["complete_standard_session_count"] == 0
    assert report["incomplete_standard_session_count"] == 1


def test_multiple_artifacts_require_session_wide_completeness() -> None:
    first = _artifact(as_of_et="2026-09-11T10:05:00-04:00")
    second = _artifact(as_of_et="2026-09-11T13:05:00-04:00", provenance_gap="MSFT")
    report = build_completeness_report([first, second])
    assert report["by_session"]["2026-09-11"]["artifact_count"] == 2
    assert report["by_session"]["2026-09-11"]["complete_standard_session"] is False


def test_score_inspection_unlocks_only_at_preregistered_complete_session_count() -> None:
    below = build_completeness_report(_complete_sessions(MIN_COMPLETE_SESSIONS_FOR_SCORE_INSPECTION - 1))
    ready = build_completeness_report(_complete_sessions(MIN_COMPLETE_SESSIONS_FOR_SCORE_INSPECTION))

    assert below["ready_for_score_inspection"] is False
    assert below["score_inspection_remaining_complete_sessions"] == 1
    assert ready["ready_for_score_inspection"] is True
    assert ready["score_inspection_remaining_complete_sessions"] == 0
    assert ready["promotion_authorized"] is False


def test_readiness_is_invariant_to_probability_and_direction() -> None:
    original = _complete_sessions(MIN_COMPLETE_SESSIONS_FOR_SCORE_INSPECTION)
    changed = deepcopy(original)
    for artifact in changed:
        for row in artifact["results"]["symbols"].values():
            row["horizons"] = {"30m": {"probability_up": 1.0, "probability_down": 99.0, "direction": "bearish"}}
    assert build_completeness_report(changed) == build_completeness_report(original)
