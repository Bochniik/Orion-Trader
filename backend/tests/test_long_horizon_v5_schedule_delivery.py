from datetime import datetime, timezone

import pytest

from scripts.audit_long_horizon_v5_schedule_delivery import (
    PROTOCOL_NOT_BEFORE_UTC,
    ScheduleDeliveryError,
    build_schedule_delivery_report,
    expected_slots,
)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run(run_id: int, created_at: str, *, conclusion: str = "success", event: str = "schedule") -> dict:
    return {
        "id": run_id,
        "event": event,
        "created_at": created_at,
        "status": "completed",
        "conclusion": conclusion,
        "probability_up": 0.999,
        "direction": "UP",
    }


def test_expected_slots_start_at_protocol_activation_and_skip_weekend():
    slots = expected_slots(start=dt("2026-09-01T00:00:00Z"), as_of=dt("2026-09-14T14:30:00Z"))
    assert slots[0] == dt("2026-09-11T14:05:00Z")
    assert dt("2026-09-12T14:05:00Z") not in slots
    assert dt("2026-09-13T14:05:00Z") not in slots
    assert slots[-1] == dt("2026-09-14T14:05:00Z")


def test_complete_day_reports_full_schedule_delivery_without_model_fields():
    runs = [run(100 + hour, f"2026-09-11T{hour:02d}:08:00Z") for hour in range(14, 20)]
    report = build_schedule_delivery_report(
        runs,
        start=PROTOCOL_NOT_BEFORE_UTC,
        as_of=dt("2026-09-11T20:00:00Z"),
    )
    assert report["summary"]["expected_slot_count"] == 6
    assert report["summary"]["delivered_slot_count"] == 6
    assert report["summary"]["missing_slot_count"] == 0
    assert report["summary"]["schedule_delivery_rate"] == 1.0
    serialized = str(report)
    assert "probability_up" not in serialized
    assert "direction" not in serialized


def test_missing_single_slot_is_visible_and_hour_specific():
    runs = [
        run(1, "2026-09-11T14:06:00Z"),
        run(2, "2026-09-11T15:06:00Z"),
        run(3, "2026-09-11T16:06:00Z"),
        run(4, "2026-09-11T17:06:00Z"),
        run(6, "2026-09-11T19:06:00Z"),
    ]
    report = build_schedule_delivery_report(runs, start=PROTOCOL_NOT_BEFORE_UTC, as_of=dt("2026-09-11T20:00:00Z"))
    assert report["summary"]["missing_slot_count"] == 1
    assert report["summary"]["schedule_delivery_rate"] == pytest.approx(5 / 6)
    assert report["missing_slots"][0]["expected_slot_utc"] == "2026-09-11T18:05:00+00:00"
    assert report["per_utc_slot"]["18:05Z"]["missing"] == 1


def test_delayed_run_within_tolerance_matches_expected_slot():
    report = build_schedule_delivery_report(
        [run(1, "2026-09-11T14:59:00Z")],
        start=dt("2026-09-11T14:00:00Z"),
        as_of=dt("2026-09-11T15:02:00Z"),
    )
    assert report["summary"]["expected_slot_count"] == 1
    assert report["summary"]["delivered_slot_count"] == 1
    assert report["deliveries"][0]["delivery_delay_minutes"] == 54.0


def test_run_beyond_delivery_tolerance_does_not_mask_missing_slot():
    report = build_schedule_delivery_report(
        [run(1, "2026-09-11T15:01:00Z")],
        start=dt("2026-09-11T14:00:00Z"),
        as_of=dt("2026-09-11T15:04:00Z"),
    )
    assert report["summary"]["missing_slot_count"] == 1
    assert report["summary"]["unexpected_run_count"] == 1


def test_immature_latest_slot_is_not_in_denominator():
    report = build_schedule_delivery_report(
        [],
        start=dt("2026-09-11T18:00:00Z"),
        as_of=dt("2026-09-11T19:10:00Z"),
    )
    assert report["summary"]["expected_slot_count"] == 1
    assert report["deliveries"][0]["expected_slot_utc"] == "2026-09-11T18:05:00+00:00"


def test_duplicate_ids_and_non_schedule_inputs_fail_closed():
    with pytest.raises(ScheduleDeliveryError, match="duplicate"):
        build_schedule_delivery_report(
            [run(1, "2026-09-11T14:06:00Z"), run(1, "2026-09-11T15:06:00Z")],
            start=PROTOCOL_NOT_BEFORE_UTC,
            as_of=dt("2026-09-11T16:00:00Z"),
        )
    with pytest.raises(ScheduleDeliveryError, match="scheduled runs only"):
        build_schedule_delivery_report(
            [run(2, "2026-09-11T14:06:00Z", event="workflow_dispatch")],
            start=PROTOCOL_NOT_BEFORE_UTC,
            as_of=dt("2026-09-11T16:00:00Z"),
        )


def test_empty_pre_activation_window_has_null_rate():
    report = build_schedule_delivery_report(
        [],
        start=dt("2026-09-01T00:00:00Z"),
        as_of=dt("2026-09-11T05:09:00Z"),
    )
    assert report["summary"]["expected_slot_count"] == 0
    assert report["summary"]["schedule_delivery_rate"] is None
