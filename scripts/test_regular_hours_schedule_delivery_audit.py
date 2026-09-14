from datetime import datetime, timezone
import unittest

from audit_regular_hours_schedule_delivery import build_audit


class RegularHoursScheduleDeliveryAuditTests(unittest.TestCase):
    def test_scheduled_slot_is_explicitly_inferred(self) -> None:
        report = build_audit(
            observed_at=datetime(2026, 9, 14, 18, 50, tzinfo=timezone.utc),
            event_name="schedule",
            scheduled_cron="35 13-21 * * 1-5",
        )

        self.assertEqual(report["contract"], "orion-regular-hours-schedule-delivery-v2")
        self.assertEqual(report["expected_slot_utc"], "2026-09-14T18:35:00+00:00")
        self.assertFalse(report["expected_slot_exact"])
        self.assertEqual(report["expected_slot_resolution"], "latest_matching_cron_before_observed")
        self.assertEqual(report["delivery_delay_minutes"], 15.0)
        self.assertEqual(
            report["delivery_delay_semantics"],
            "minimum_delay_from_latest_matching_slot_not_exact_occurrence_delay",
        )
        self.assertEqual(report["delivery_class"], "inferred_on_time")
        self.assertTrue(report["delivery_class_inferred"])
        self.assertIn("full run history", report["warning"])

    def test_late_observation_does_not_claim_exact_occurrence(self) -> None:
        # A run observed at 20:43 could be the 20:35 occurrence with an 8-minute
        # delay, or an older occurrence delayed by more than one cadence. The
        # per-run payload must not present the inferred 20:35 slot as exact.
        report = build_audit(
            observed_at=datetime(2026, 9, 14, 20, 43, tzinfo=timezone.utc),
            event_name="schedule",
            scheduled_cron="35 13-21 * * 1-5",
        )

        self.assertEqual(report["expected_slot_utc"], "2026-09-14T20:35:00+00:00")
        self.assertFalse(report["expected_slot_exact"])
        self.assertEqual(report["delivery_delay_minutes"], 8.0)
        self.assertTrue(report["missed_regular_window_inferred"])

    def test_manual_dispatch_has_no_slot_claim(self) -> None:
        report = build_audit(
            observed_at=datetime(2026, 9, 14, 18, 50, tzinfo=timezone.utc),
            event_name="workflow_dispatch",
            scheduled_cron=None,
        )

        self.assertEqual(report["mode"], "manual_dispatch")
        self.assertIsNone(report["expected_slot_utc"])
        self.assertEqual(report["expected_slot_resolution"], "not_applicable")
        self.assertIsNone(report["expected_slot_exact"])
        self.assertEqual(report["delivery_delay_semantics"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
