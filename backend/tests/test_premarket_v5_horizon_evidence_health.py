from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_premarket_v5_collection_health as health
import scripts.audit_premarket_v5_horizon_evidence_health as evidence
import scripts.audit_premarket_v5_schedule_delivery as delivery
import scripts.finalize_premarket_v5_forward_artifact as attestation
import scripts.resolve_premarket_v5_snapshot as resolver


HEAD_SHA = "b" * 40


def _forecast() -> dict:
    return {
        "direction": "NO_TRADE",
        "raw_direction": "UP",
        "probability_up": 0.5,
        "probability_down": 0.5,
        "directional_confidence": 0.5,
    }


def _payload(day: date, snapshot: str, run_id: str, *, start_lag: float = 2.0, duration: float = 2.0) -> dict:
    hour, minute = health.SNAPSHOT_CLOCKS[snapshot]
    local = datetime.combine(day, time(hour, minute), tzinfo=health.NY)
    symbols = list(health.PREREGISTERED_SYMBOLS)
    payload = {
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
    as_of = datetime.fromisoformat(payload["as_of_utc"])
    started = as_of + timedelta(minutes=start_lag)
    return attestation.finalize_payload(
        payload,
        collection_started_at=started,
        collection_completed_at=started + timedelta(minutes=duration),
        event_name="schedule",
        run_id=run_id,
        run_attempt=1,
        github_head_sha=HEAD_SHA,
    )


def _run(day: date, snapshot: str, run_id: str) -> dict:
    reference = datetime.combine(day, datetime.min.time(), tzinfo=resolver.NY).astimezone(timezone.utc)
    target, _ = resolver._target_for_local_day(snapshot, reference=reference)
    cron = f"{target.minute} {target.hour} * * 1-5"
    return {
        "id": run_id,
        "event": "schedule",
        "display_title": f"{delivery.RUN_NAME_PREFIX}{cron}",
        "created_at": target.isoformat(),
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }


def _recovery_run(day: date, snapshot: str, run_id: str) -> dict:
    reference = datetime.combine(day, datetime.min.time(), tzinfo=resolver.NY).astimezone(timezone.utc)
    target, _ = resolver._target_for_local_day(snapshot, reference=reference)
    recovery_target = target + resolver.RECOVERY_DELAY
    cron = f"{recovery_target.minute} {recovery_target.hour} * * 1-5"
    return {
        "id": run_id,
        "event": "schedule",
        "display_title": f"{delivery.RUN_NAME_PREFIX}{cron}",
        "created_at": recovery_target.isoformat(),
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }


def _as_of(day: date) -> datetime:
    reference = datetime.combine(day, datetime.min.time(), tzinfo=resolver.NY).astimezone(timezone.utc)
    target, _ = resolver._target_for_local_day("late", reference=reference)
    return target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)


def test_healthy_primary_observations_remain_fully_decision_grade():
    day = date(2026, 9, 14)
    runs = [_run(day, snapshot, str(i)) for i, snapshot in enumerate(resolver.SNAPSHOT_CLOCKS, start=1)]
    payloads = [_payload(day, snapshot, str(i)) for i, snapshot in enumerate(resolver.SNAPSHOT_CLOCKS, start=1)]

    report = evidence.build_evidence_health_report(runs, payloads, start_date=day, as_of=_as_of(day))

    assert report["contract"] == "orion-premarket-v5-evidence-health-v3"
    assert report["summary"]["status_counts"]["decision_grade_complete"] == 3
    assert report["summary"]["status_counts"]["horizon_partially_prospective"] == 0
    assert report["summary"]["all_mature_slots_decision_grade_complete"] is True
    assert report["summary"]["all_mature_slots_decision_grade_complete_by_horizon"] == {
        "premarket_5m": True,
        "premarket_15m": True,
        "premarket_30m": True,
    }
    for row in report["evidence_rows"]:
        assert all(row["decision_grade_complete_by_horizon"].values())


def test_delayed_recovery_is_partial_not_globally_decision_grade():
    day = date(2026, 9, 14)
    runs = [
        _recovery_run(day, "early", "101"),
        _run(day, "mid", "2"),
        _run(day, "late", "3"),
    ]
    payloads = [
        # Completes at +14 minutes: 5m is already observable, while 15m and 30m remain prospective.
        _payload(day, "early", "101", start_lag=12.0, duration=2.0),
        _payload(day, "mid", "2"),
        _payload(day, "late", "3"),
    ]

    report = evidence.build_evidence_health_report(runs, payloads, start_date=day, as_of=_as_of(day))

    early = next(row for row in report["evidence_rows"] if row["snapshot"] == "early")
    assert early["recovered_transport"] is True
    assert early["forward_eligible"] is True
    assert early["status"] == "horizon_partially_prospective"
    assert early["horizon_forward_eligible"] == {
        "premarket_5m": False,
        "premarket_15m": True,
        "premarket_30m": True,
    }
    assert early["decision_grade_complete_by_horizon"] == early["horizon_forward_eligible"]

    assert report["summary"]["status_counts"]["decision_grade_complete"] == 2
    assert report["summary"]["status_counts"]["horizon_partially_prospective"] == 1
    assert report["summary"]["decision_grade_complete_by_horizon_counts"] == {
        "premarket_5m": 2,
        "premarket_15m": 3,
        "premarket_30m": 3,
    }
    assert report["summary"]["all_mature_slots_decision_grade_complete"] is False
    assert report["summary"]["all_mature_slots_decision_grade_complete_by_horizon"]["premarket_5m"] is False
    assert "horizon_acquisition_eligibility" in report["summary"]["historical_incident_layers"]


def test_snapshot_summary_exposes_operational_and_cohort_horizon_counts():
    day = date(2026, 9, 14)
    runs = [_recovery_run(day, "early", "101")]
    payloads = [_payload(day, "early", "101", start_lag=12.0, duration=2.0)]

    report = evidence.build_evidence_health_report(runs, payloads, start_date=day, as_of=_as_of(day))
    early = report["per_snapshot"]["early"]

    assert early["per_horizon"]["premarket_5m"]["decision_grade_complete_slot_count"] == 0
    assert early["per_horizon"]["premarket_15m"]["decision_grade_complete_slot_count"] == 1
    assert early["per_horizon"]["premarket_30m"]["decision_grade_complete_slot_count"] == 1
    assert "prospective_decision_grade_complete_distinct_session_count" in early["per_horizon"]["premarket_5m"]
