from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    path = ROOT / "scripts/audit_long_horizon_v5_schedule_delivery.py"
    spec = importlib.util.spec_from_file_location("long_horizon_schedule_delivery", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _load_module()
PROTOCOL_NOT_BEFORE_UTC = audit.PROTOCOL_NOT_BEFORE_UTC
ScheduleDeliveryError = audit.ScheduleDeliveryError
build_schedule_delivery_report = audit.build_schedule_delivery_report
expected_slots = audit.expected_slots


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
    assert report["evidence_opportunities"]["3h"]["expected_opportunity_count"] == 3
    assert report["evidence_opportunities"]["3h"]["effective_delivery_rate"] == 1.0
    assert report["critical_5h"]["expected_opportunity_count"] == 1
    assert report["critical_5h"]["effective_delivery_rate"] == 1.0
    serialized = str(report)
    assert "probability_up" not in serialized
    assert "direction" not in serialized


def test_missing_single_support_slot_does_not_reduce_evidence_opportunity_coverage():
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
    assert report["evidence_opportunities"]["3h"]["effective_delivery_rate"] == 1.0
    assert report["critical_5h"]["effective_delivery_rate"] == 1.0


def test_missing_critical_5h_slot_is_visible_even_when_support_slots_arrive():
    runs = [
        run(2, "2026-09-11T15:06:00Z"),
        run(3, "2026-09-11T16:06:00Z"),
        run(4, "2026-09-11T17:06:00Z"),
        run(5, "2026-09-11T18:06:00Z"),
        run(6, "2026-09-11T19:06:00Z"),
    ]
    report = build_schedule_delivery_report(runs, start=PROTOCOL_NOT_BEFORE_UTC, as_of=dt("2026-09-11T20:00:00Z"))
    assert report["summary"]["schedule_delivery_rate"] == pytest.approx(5 / 6)
    assert report["evidence_opportunities"]["3h"]["effective_delivery_count"] == 2
    assert report["evidence_opportunities"]["3h"]["effective_delivery_rate"] == pytest.approx(2 / 3)
    assert report["critical_5h"]["expected_opportunity_count"] == 1
    assert report["critical_5h"]["effective_delivery_count"] == 0
    assert report["critical_5h"]["lost_expected_slots_utc"] == ["2026-09-11T14:05:00+00:00"]


def test_market_relative_opportunities_shift_across_dst_without_changing_cron():
    edt = build_schedule_delivery_report(
        [run(100 + hour, f"2026-09-14T{hour:02d}:06:00Z") for hour in range(14, 20)],
        start=dt("2026-09-14T14:00:00Z"),
        as_of=dt("2026-09-14T20:00:00Z"),
    )
    est = build_schedule_delivery_report(
        [run(200 + hour, f"2026-11-09T{hour:02d}:06:00Z") for hour in range(14, 20)],
        start=dt("2026-11-09T14:00:00Z"),
        as_of=dt("2026-11-09T20:00:00Z"),
    )
    edt_5h = [row["expected_slot_utc"] for row in edt["deliveries"] if "5h" in row["expected_eligible_horizons"]]
    est_5h = [row["expected_slot_utc"] for row in est["deliveries"] if "5h" in row["expected_eligible_horizons"]]
    assert edt_5h == ["2026-09-14T14:05:00+00:00"]
    assert est_5h == ["2026-11-09T15:05:00+00:00"]
    assert edt["critical_5h"]["effective_delivery_rate"] == 1.0
    assert est["critical_5h"]["effective_delivery_rate"] == 1.0


def test_delayed_run_within_tolerance_matches_expected_slot_and_preserves_horizon():
    report = build_schedule_delivery_report(
        [run(1, "2026-09-11T14:59:00Z")],
        start=dt("2026-09-11T14:00:00Z"),
        as_of=dt("2026-09-11T15:02:00Z"),
    )
    assert report["summary"]["expected_slot_count"] == 1
    assert report["summary"]["delivered_slot_count"] == 1
    assert report["deliveries"][0]["delivery_delay_minutes"] == 54.0
    assert report["deliveries"][0]["expected_eligible_horizons"] == ["3h", "5h"]
    assert report["deliveries"][0]["effective_eligible_horizons"] == ["3h", "5h"]


def test_run_beyond_delivery_tolerance_does_not_mask_missing_slot():
    report = build_schedule_delivery_report(
        [run(1, "2026-09-11T15:01:00Z")],
        start=dt("2026-09-11T14:00:00Z"),
        as_of=dt("2026-09-11T15:04:00Z"),
    )
    assert report["summary"]["missing_slot_count"] == 1
    assert report["summary"]["unexpected_run_count"] == 1
    assert report["critical_5h"]["effective_delivery_count"] == 0


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


def test_empty_pre_activation_window_has_null_rates():
    report = build_schedule_delivery_report(
        [],
        start=dt("2026-09-01T00:00:00Z"),
        as_of=dt("2026-09-11T05:09:00Z"),
    )
    assert report["summary"]["expected_slot_count"] == 0
    assert report["summary"]["schedule_delivery_rate"] is None
    assert report["evidence_opportunities"]["3h"]["effective_delivery_rate"] is None
    assert report["critical_5h"]["effective_delivery_rate"] is None
