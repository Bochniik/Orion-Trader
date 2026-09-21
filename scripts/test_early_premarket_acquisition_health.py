from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from audit_early_premarket_acquisition_health import RunEvidence, build_health_report, expected_slots


class EarlyPremarketAcquisitionHealthTests(unittest.TestCase):
    def test_dst_safe_slot_identity(self):
        winter = expected_slots(date(2026, 1, 12))[0]
        summer = expected_slots(date(2026, 9, 17))[0]
        self.assertTrue(winter["target_utc"].startswith("2026-01-12T09:05"))
        self.assertTrue(summer["target_utc"].startswith("2026-09-17T08:05"))
        self.assertNotEqual(winter["slot_id"], summer["slot_id"])

    def test_missing_run_is_fail_visible_not_backfilled(self):
        report = build_health_report(
            session_date=date(2026, 9, 17),
            runs=[],
            observed_at_utc=datetime(2026, 9, 17, 11, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(report["slots"][0]["status"], "workflow_never_created")
        self.assertFalse(report["slots"][0]["forward_backfill_allowed"])

    def test_created_failed_run_is_distinct_from_missing_workflow(self):
        target = expected_slots(date(2026, 9, 17))[0]
        run = RunEvidence(
            run_id="101",
            created_at_utc=datetime(2026, 9, 17, 8, 6, tzinfo=timezone.utc),
            conclusion="failure",
            target_slot_et=target["target_et"],
        )
        report = build_health_report(
            session_date=date(2026, 9, 17),
            runs=[run],
            observed_at_utc=datetime(2026, 9, 17, 11, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(report["slots"][0]["status"], "workflow_created_collector_failed")

    def test_duplicate_slot_runs_do_not_double_count_evidence(self):
        target = expected_slots(date(2026, 9, 17))[0]
        runs = [
            RunEvidence("101", datetime(2026, 9, 17, 8, 6, tzinfo=timezone.utc), "success", target["target_et"]),
            RunEvidence("102", datetime(2026, 9, 17, 8, 7, tzinfo=timezone.utc), "success", target["target_et"]),
        ]
        report = build_health_report(
            session_date=date(2026, 9, 17),
            runs=runs,
            observed_at_utc=datetime(2026, 9, 17, 11, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(report["slots"][0]["status"], "collector_succeeded")
        self.assertEqual(report["slots"][0]["duplicate_run_count"], 1)

    def test_future_slot_remains_pending(self):
        report = build_health_report(
            session_date=date(2026, 9, 17),
            runs=[],
            observed_at_utc=datetime(2026, 9, 17, 8, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(report["slots"][0]["status"], "pending")
        self.assertEqual(report["slots"][1]["status"], "pending")

    def test_weekend_is_not_scored_as_acquisition_failure(self):
        with self.assertRaisesRegex(ValueError, "not a regular NYSE trading day"):
            build_health_report(
                session_date=date(2026, 9, 19),
                runs=[],
                observed_at_utc=datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
            )

    def test_nyse_holiday_is_not_scored_as_acquisition_failure(self):
        with self.assertRaisesRegex(ValueError, "not a regular NYSE trading day"):
            build_health_report(
                session_date=date(2026, 12, 25),
                runs=[],
                observed_at_utc=datetime(2026, 12, 25, 12, 0, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
