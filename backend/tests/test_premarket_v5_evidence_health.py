from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_premarket_v5_collection_health as health
import scripts.audit_premarket_v5_evidence_health as evidence
import scripts.audit_premarket_v5_schedule_delivery as delivery
import scripts.finalize_premarket_v5_forward_artifact as attestation
import scripts.resolve_premarket_v5_snapshot as resolver


def _forecast():
    return {
        "direction": "NO_TRADE",
        "raw_direction": "UP",
        "probability_up": 0.5,
        "probability_down": 0.5,
        "directional_confidence": 0.5,
    }


def _payload(day: date, snapshot: str, run_id: str, *, complete: bool = True, lag: float = 2.0) -> dict:
    hour, minute = health.SNAPSHOT_CLOCKS[snapshot]
    local = datetime.combine(day, time(hour, minute), tzinfo=health.NY)
    symbols = list(health.PREREGISTERED_SYMBOLS)
    predictions = [
        {
            "ticker": symbol,
            "available": True,
            "forecasts": {horizon: _forecast() for horizon in health.SUPPORTED_HORIZONS},
        }
        for symbol in symbols
    ]
    if not complete:
        predictions[0]["available"] = False
        predictions[0]["forecasts"] = {}
    payload = {
        "runner_version": health.RUNNER_VERSION,
        "mode": "shadow_research_only",
        "order_submission_enabled": False,
        "as_of_utc": local.astimezone(timezone.utc).isoformat(),
        "as_of_et": local.isoformat(),
        "causal_cutoff_enforced": True,
        "feed": "iex",
        "symbols": symbols,
        "predictions": predictions,
    }
    as_of = datetime.fromisoformat(payload["as_of_utc"])
    return attestation.finalize_payload(
        payload,
        collection_started_at=as_of + timedelta(minutes=lag),
        collection_completed_at=as_of + timedelta(minutes=lag + 5),
        event_name="schedule",
        run_id=run_id,
        run_attempt=1,
    )


def _run(day: date, snapshot: str, run_id: str, *, conclusion: str = "success") -> dict:
    reference = datetime.combine(day, datetime.min.time(), tzinfo=resolver.NY).astimezone(timezone.utc)
    target, _ = resolver._target_for_local_day(snapshot, reference=reference)
    cron = f"{target.minute} {target.hour} * * 1-5"
    assert resolver.REGISTERED_CRON_SLOTS[cron] == snapshot
    return {
        "id": run_id,
        "event": "schedule",
        "display_title": f"{delivery.RUN_NAME_PREFIX}{cron}",
        "created_at": target.isoformat(),
        "status": "completed",
        "conclusion": conclusion,
        "run_attempt": 1,
    }


def _as_of(day: date) -> datetime:
    reference = datetime.combine(day, datetime.min.time(), tzinfo=resolver.NY).astimezone(timezone.utc)
    target, _ = resolver._target_for_local_day("late", reference=reference)
    return target + timedelta(minutes=delivery.MATURE_AFTER_MINUTES + 1)


def test_healthy_mature_slots_are_decision_grade_but_cohort_remains_young():
    day = date(2026, 9, 11)
    runs = [_run(day, snapshot, str(index)) for index, snapshot in enumerate(resolver.SNAPSHOT_CLOCKS, start=1)]
    payloads = [_payload(day, snapshot, str(index)) for index, snapshot in enumerate(resolver.SNAPSHOT_CLOCKS, start=1)]

    report = evidence.build_evidence_health_report(runs, payloads, start_date=day, as_of=_as_of(day))

    assert report["score_blind"] is True
    assert report["metrics_exposed"] is False
    assert report["summary"]["status_counts"]["decision_grade_complete"] == 3
    assert report["summary"]["all_mature_slots_decision_grade_complete"] is True
    assert report["summary"]["operationally_clean"] is True
    assert report["summary"]["ready_for_issue_3_score_inspection"] is False
    assert report["summary"]["blocking_layers"] == ["cohort_maturity"]


def test_missing_failed_and_missing_artifact_are_attributed_to_distinct_layers():
    day = date(2026, 9, 11)
    runs = [
        _run(day, "mid", "2", conclusion="failure"),
        _run(day, "late", "3"),
    ]
    report = evidence.build_evidence_health_report(runs, [], start_date=day, as_of=_as_of(day))

    counts = report["summary"]["status_counts"]
    assert counts["missing_delivery"] == 1
    assert counts["workflow_unsuccessful"] == 1
    assert counts["artifact_missing_after_success"] == 1
    assert report["summary"]["blocking_layers"][:3] == [
        "delivery",
        "workflow_execution",
        "artifact_persistence",
    ]


def test_forecast_and_acquisition_failures_are_separated():
    day = date(2026, 9, 11)
    runs = [_run(day, "early", "1"), _run(day, "mid", "2"), _run(day, "late", "3")]
    payloads = [
        _payload(day, "early", "1", complete=False),
        _payload(day, "mid", "2", lag=attestation.MAX_START_LAG_MINUTES + 1),
        _payload(day, "late", "3"),
    ]

    report = evidence.build_evidence_health_report(runs, payloads, start_date=day, as_of=_as_of(day))

    counts = report["summary"]["status_counts"]
    assert counts["forecast_incomplete"] == 1
    assert counts["acquisition_ineligible"] == 1
    assert counts["decision_grade_complete"] == 1
    assert "forecast_completeness" in report["summary"]["blocking_layers"]
    assert "acquisition_eligibility" in report["summary"]["blocking_layers"]


def test_score_changes_do_not_change_evidence_health_classification():
    day = date(2026, 9, 11)
    runs = [_run(day, "late", "3")]
    baseline_payload = _payload(day, "late", "3")
    changed = deepcopy(baseline_payload)
    changed.pop("acquisition_provenance")
    changed["predictions"][0]["forecasts"]["premarket_5m"].update(
        {"probability_up": 0.99, "brier": 0.0, "log_loss": 0.0, "realized_outcome": 1}
    )
    as_of = datetime.fromisoformat(changed["as_of_utc"])
    changed = attestation.finalize_payload(
        changed,
        collection_started_at=as_of + timedelta(minutes=2),
        collection_completed_at=as_of + timedelta(minutes=7),
        event_name="schedule",
        run_id="3",
        run_attempt=1,
    )

    baseline = evidence.build_evidence_health_report(runs, [baseline_payload], start_date=day, as_of=_as_of(day))
    altered = evidence.build_evidence_health_report(runs, [changed], start_date=day, as_of=_as_of(day))

    assert altered["summary"] == baseline["summary"]
    assert altered["per_snapshot"] == baseline["per_snapshot"]
    assert altered["evidence_rows"] == baseline["evidence_rows"]
