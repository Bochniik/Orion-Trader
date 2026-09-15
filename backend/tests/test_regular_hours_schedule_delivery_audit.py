from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_regular_hours_schedule_delivery.py"
SPEC = importlib.util.spec_from_file_location("regular_hours_schedule_delivery_audit", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


def test_on_time_scheduled_delivery_is_explicitly_inferred():
    observed = datetime(2026, 9, 11, 13, 42, tzinfo=timezone.utc)
    report = module.build_audit(observed_at=observed, scheduled_cron="35 13-21 * * 1-5")
    assert report["contract"] == "orion-regular-hours-schedule-delivery-v2"
    assert report["expected_slot_utc"] == "2026-09-11T13:35:00+00:00"
    assert report["expected_slot_exact"] is False
    assert report["expected_slot_resolution"] == "latest_matching_cron_before_observed"
    assert report["delivery_delay_minutes"] == 7.0
    assert report["delivery_delay_semantics"] == "minimum_delay_from_latest_matching_slot_not_exact_occurrence_delay"
    assert report["delivery_class"] == "inferred_on_time"
    assert report["delivery_class_inferred"] is True
    assert report["expected_slot_in_regular_window"] is True
    assert report["observed_in_regular_window"] is True
    assert report["missed_regular_window"] is False


def test_severely_delayed_delivery_is_only_an_inferred_lost_regular_hours_slot():
    observed = datetime(2026, 9, 11, 20, 45, tzinfo=timezone.utc)  # 16:45 EDT
    report = module.build_audit(observed_at=observed, scheduled_cron="25 19 * * 1-5")
    assert report["expected_slot_utc"] == "2026-09-11T19:25:00+00:00"
    assert report["expected_slot_exact"] is False
    assert report["delivery_delay_minutes"] == 80.0
    assert report["delivery_class"] == "inferred_severely_delayed"
    assert report["expected_slot_in_regular_window"] is True
    assert report["observed_in_regular_window"] is False
    assert report["missed_regular_window"] is True
    assert report["missed_regular_window_inferred"] is True
    assert "full run history" in report["warning"]


def test_delayed_outside_slot_does_not_claim_a_missed_market_observation():
    observed = datetime(2026, 9, 11, 22, 45, tzinfo=timezone.utc)  # 18:45 EDT
    report = module.build_audit(observed_at=observed, scheduled_cron="35 21 * * 1-5")
    assert report["delivery_class"] == "inferred_severely_delayed"
    assert report["expected_slot_in_regular_window"] is False
    assert report["missed_regular_window"] is False


def test_winter_slot_uses_new_york_dst_rules():
    observed = datetime(2026, 1, 5, 15, 40, tzinfo=timezone.utc)  # 10:40 EST
    report = module.build_audit(observed_at=observed, scheduled_cron="35 15 * * 1-5")
    assert report["expected_slot_et"].startswith("2026-01-05T10:35:00-05:00")
    assert report["expected_slot_in_regular_window"] is True
    assert report["expected_slot_exact"] is False


def test_manual_dispatch_has_no_fabricated_schedule_delay():
    observed = datetime(2026, 9, 11, 14, 6, tzinfo=timezone.utc)
    report = module.build_audit(
        observed_at=observed,
        event_name="workflow_dispatch",
        scheduled_cron=None,
    )
    assert report["mode"] == "manual_dispatch"
    assert report["expected_slot_utc"] is None
    assert report["expected_slot_exact"] is None
    assert report["expected_slot_resolution"] == "not_applicable"
    assert report["delivery_delay_minutes"] is None
    assert report["delivery_delay_semantics"] == "not_applicable"
    assert report["delivery_class"] == "not_applicable"
    assert report["missed_regular_window"] is False
