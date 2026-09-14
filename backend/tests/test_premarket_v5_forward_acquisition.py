from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_premarket_v5_collection_health as health
import scripts.audit_premarket_v5_forward_readiness as readiness
import scripts.finalize_premarket_v5_forward_artifact as attestation


HEAD_SHA = "a" * 40


def _forecast():
    return {
        "direction": "NO_TRADE",
        "raw_direction": "UP",
        "probability_up": 0.5,
        "probability_down": 0.5,
        "directional_confidence": 0.5,
    }


def _base_payload(day: date, snapshot: str) -> dict:
    hour, minute = health.SNAPSHOT_CLOCKS[snapshot]
    local = datetime.combine(day, time(hour, minute), tzinfo=health.NY)
    symbols = list(health.PREREGISTERED_SYMBOLS)
    return {
        "runner_version": health.RUNNER_VERSION,
        "mode": "shadow_research_only",
        "order_submission_enabled": False,
        "as_of_utc": local.astimezone(timezone.utc).isoformat(),
        "as_of_et": local.isoformat(),
        "causal_cutoff_enforced": True,
        "feed": "iex",
        "symbols": symbols,
        "predictions": [
            {
                "ticker": symbol,
                "available": True,
                "forecasts": {horizon: _forecast() for horizon in health.SUPPORTED_HORIZONS},
            }
            for symbol in symbols
        ],
    }


def _attested_payload(
    day: date,
    snapshot: str,
    *,
    start_lag_minutes: float = 2.0,
    collection_duration_minutes: float = 5.0,
    event_name: str = "schedule",
) -> dict:
    payload = _base_payload(day, snapshot)
    as_of = datetime.fromisoformat(payload["as_of_utc"])
    started = as_of + timedelta(minutes=start_lag_minutes)
    completed = started + timedelta(minutes=collection_duration_minutes)
    return attestation.finalize_payload(
        payload,
        collection_started_at=started,
        collection_completed_at=completed,
        event_name=event_name,
        run_id="123456" if event_name == "schedule" else None,
        run_attempt=1 if event_name == "schedule" else None,
        github_head_sha=HEAD_SHA if event_name == "schedule" else None,
    )


def _trading_days(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if health.is_nyse_trading_day(current):
            result.append(current)
        current += timedelta(days=1)
    return result


def test_scheduled_timely_artifact_is_forward_eligible_and_bound_to_payload():
    payload = _attested_payload(date(2026, 9, 11), "late", start_lag_minutes=4.0)

    projection = readiness.validate_acquisition(payload)

    assert payload["acquisition_provenance"]["contract"] == attestation.ATTESTATION_CONTRACT
    assert payload["acquisition_provenance"]["github_head_sha"] == HEAD_SHA
    assert payload["acquisition_provenance"]["forward_eligible"] is True
    assert payload["acquisition_provenance"]["eligibility_reason"] == "scheduled_forward_window"
    assert projection["decision_grade_complete"] is True
    assert projection["horizon_forward_eligible"] == {
        "premarket_5m": False,
        "premarket_15m": True,
        "premarket_30m": True,
    }
    assert projection["collection_start_lag_minutes"] == 4.0


def test_delayed_or_manual_artifact_is_diagnostic_not_decision_grade():
    delayed = _attested_payload(
        date(2026, 9, 11),
        "early",
        start_lag_minutes=attestation.MAX_START_LAG_MINUTES + 1.0,
    )
    manual = _attested_payload(date(2026, 9, 11), "mid", event_name="workflow_dispatch")

    delayed_projection = readiness.validate_acquisition(delayed)
    manual_projection = readiness.validate_acquisition(manual)

    assert delayed_projection["forecast_complete"] is True
    assert delayed_projection["decision_grade_complete"] is False
    assert delayed_projection["eligibility_reason"] == "collection_started_too_late"
    assert manual_projection["decision_grade_complete"] is False
    assert manual_projection["eligibility_reason"] == "not_scheduled_collection"


def test_tampering_after_attestation_fails_closed():
    payload = _attested_payload(date(2026, 9, 11), "late")
    payload["predictions"][0]["forecasts"]["premarket_5m"]["probability_up"] = 0.99

    with pytest.raises(readiness.ForwardReadinessError, match="changed after acquisition attestation"):
        readiness.validate_acquisition(payload)


def test_horizon_eligibility_excludes_targets_observable_before_collection_completed():
    payload = _attested_payload(
        date(2026, 9, 11),
        "mid",
        start_lag_minutes=2.0,
        collection_duration_minutes=10.0,
    )

    projection = readiness.validate_acquisition(payload)

    assert projection["forward_eligible"] is True
    assert projection["horizon_forward_eligible"] == {
        "premarket_5m": False,
        "premarket_15m": True,
        "premarket_30m": True,
    }
    assert projection["decision_grade_complete_by_horizon"] == {
        "premarket_5m": False,
        "premarket_15m": True,
        "premarket_30m": True,
    }
    assert projection["decision_grade_complete"] is False


def test_horizon_eligibility_requires_collection_to_finish_strictly_before_target():
    payload = _attested_payload(
        date(2026, 9, 11),
        "mid",
        start_lag_minutes=2.0,
        collection_duration_minutes=13.0,
    )

    projection = readiness.validate_acquisition(payload)

    assert projection["forward_eligible"] is True
    assert projection["horizon_forward_eligible"] == {
        "premarket_5m": False,
        "premarket_15m": False,
        "premarket_30m": True,
    }


def test_forward_readiness_requires_55_decision_grade_sessions_for_every_snapshot():
    days = _trading_days(date(2026, 1, 2), health.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT)
    payloads = [
        _attested_payload(day, snapshot, start_lag_minutes=0.0, collection_duration_minutes=1.0)
        for day in days
        for snapshot in health.SNAPSHOT_CLOCKS
    ]

    last_mid = next(
        payload
        for payload in payloads
        if payload["as_of_et"].startswith(days[-1].isoformat())
        and payload["as_of_et"][11:16] == "08:00"
    )
    replacement = _attested_payload(
        days[-1],
        "mid",
        start_lag_minutes=attestation.MAX_START_LAG_MINUTES + 5.0,
    )
    payloads[payloads.index(last_mid)] = replacement

    report = readiness.build_forward_readiness_report(payloads)

    assert report["score_blind"] is True
    assert report["metrics_exposed"] is False
    assert report["readiness"]["ready_for_issue_3_score_inspection"] is False
    assert report["readiness"]["per_snapshot"]["early"]["ready"] is True
    assert report["readiness"]["per_snapshot"]["late"]["ready"] is True
    mid = report["readiness"]["per_snapshot"]["mid"]
    assert mid["operational_complete_distinct_session_count"] == 55
    assert mid["decision_grade_complete_distinct_session_count"] == 54
    assert mid["remaining_decision_grade_complete_distinct_session_count"] == 1
    assert mid["ready"] is False
    assert report["forward_acquisition"]["ineligible_reason_counts"] == {"collection_started_too_late": 1}


def test_forward_readiness_blocks_score_inspection_when_short_horizon_is_not_prospective():
    days = _trading_days(date(2026, 1, 2), health.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT)
    payloads = [
        _attested_payload(day, snapshot, start_lag_minutes=0.0, collection_duration_minutes=1.0)
        for day in days
        for snapshot in health.SNAPSHOT_CLOCKS
    ]
    last_mid = next(
        payload
        for payload in payloads
        if payload["as_of_et"].startswith(days[-1].isoformat())
        and payload["as_of_et"][11:16] == "08:00"
    )
    recovery = _attested_payload(
        days[-1],
        "mid",
        start_lag_minutes=2.0,
        collection_duration_minutes=10.0,
    )
    payloads[payloads.index(last_mid)] = recovery

    report = readiness.build_forward_readiness_report(payloads)
    mid = report["readiness"]["per_snapshot"]["mid"]

    assert report["readiness"]["ready_for_issue_3_score_inspection"] is False
    assert mid["per_horizon"]["premarket_5m"] == {
        "prospective_decision_grade_complete_distinct_session_count": 54,
        "required_prospective_decision_grade_complete_distinct_session_count": 55,
        "remaining_prospective_decision_grade_complete_distinct_session_count": 1,
        "ready": False,
    }
    assert mid["per_horizon"]["premarket_15m"]["ready"] is True
    assert mid["per_horizon"]["premarket_30m"]["ready"] is True
    assert report["forward_acquisition"]["horizon_forward_eligible_artifact_counts"]["premarket_5m"] == 164
    assert report["forward_acquisition"]["horizon_forward_eligible_artifact_counts"]["premarket_15m"] == 165


def test_forward_readiness_becomes_true_only_with_full_scheduled_forward_geometry():
    days = _trading_days(date(2026, 1, 2), health.REQUIRED_DISTINCT_SESSIONS_PER_SNAPSHOT)
    payloads = [
        _attested_payload(day, snapshot, start_lag_minutes=0.0, collection_duration_minutes=1.0)
        for day in days
        for snapshot in health.SNAPSHOT_CLOCKS
    ]

    report = readiness.build_forward_readiness_report(payloads)

    assert report["contract"] == readiness.REPORT_CONTRACT
    assert report["readiness"]["ready_for_issue_3_score_inspection"] is True
    assert report["forward_acquisition"]["forward_ineligible_artifact_count"] == 0
    assert all(row["decision_grade_complete_distinct_session_count"] == 55 for row in report["readiness"]["per_snapshot"].values())
    for snapshot in report["readiness"]["per_snapshot"].values():
        assert all(
            horizon["prospective_decision_grade_complete_distinct_session_count"] == 55
            for horizon in snapshot["per_horizon"].values()
        )


def test_forward_readiness_stays_score_blind():
    payload = _attested_payload(
        date(2026, 9, 11),
        "early",
        start_lag_minutes=0.0,
        collection_duration_minutes=1.0,
    )
    baseline = readiness.build_forward_readiness_report([payload])
    altered = deepcopy(payload)
    altered.pop("acquisition_provenance")
    for prediction in altered["predictions"]:
        for forecast in prediction["forecasts"].values():
            forecast.update({"probability_up": 0.999, "brier": 0.0, "log_loss": 0.0, "realized_outcome": 1})
    as_of = datetime.fromisoformat(altered["as_of_utc"])
    altered = attestation.finalize_payload(
        altered,
        collection_started_at=as_of,
        collection_completed_at=as_of + timedelta(minutes=1),
        event_name="schedule",
        run_id="123456",
        run_attempt=1,
        github_head_sha=HEAD_SHA,
    )

    changed = readiness.build_forward_readiness_report([altered])
    assert changed["readiness"] == baseline["readiness"]
    assert changed["forward_acquisition"]["artifact_count"] == baseline["forward_acquisition"]["artifact_count"]
    assert changed["forward_acquisition"]["forward_eligible_artifact_count"] == baseline["forward_acquisition"]["forward_eligible_artifact_count"]
    assert changed["forward_acquisition"]["horizon_forward_eligible_artifact_counts"] == baseline["forward_acquisition"]["horizon_forward_eligible_artifact_counts"]
