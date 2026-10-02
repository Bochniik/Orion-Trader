from datetime import date, datetime, timezone
import unittest

from reconcile_regular_hours_schedule_delivery import reconcile_day


class ReconciliationTests(unittest.TestCase):
    def test_complete_day_matches_one_to_one(self):
        runs = []
        # 2026-09-14 is EDT: expected UTC slots 13:35..19:35.
        for index, hour in enumerate(range(13, 20), start=1):
            runs.append({"id": index, "event": "schedule", "created_at": f"2026-09-14T{hour:02d}:45:00Z", "conclusion": "success"})
        report = reconcile_day(session_date=date(2026, 9, 14), runs=runs)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["counts"], {"matched": 7, "missing": 0, "failed": 0})
        self.assertEqual([item["matched_run_id"] for item in report["slots"]], list(range(1, 8)))

    def test_missing_slot_is_not_filled_by_later_run(self):
        runs = [
            {"id": 1, "event": "schedule", "created_at": "2026-09-14T13:45:00Z"},
            {"id": 2, "event": "schedule", "created_at": "2026-09-14T15:45:00Z"},
        ]
        report = reconcile_day(session_date=date(2026, 9, 14), runs=runs)
        self.assertEqual(report["slots"][1]["status"], "missing")
        self.assertFalse(report["healthy"])

    def test_next_slot_boundary_belongs_only_to_next_slot(self):
        runs = [{"id": 9, "event": "schedule", "created_at": "2026-09-14T14:35:00Z", "conclusion": "success"}]
        report = reconcile_day(session_date=date(2026, 9, 14), runs=runs)
        self.assertEqual(report["slots"][0]["status"], "missing")
        self.assertEqual(report["slots"][1]["status"], "matched")
        self.assertNotIn(9, report["slots"][0]["candidate_run_ids"])
        self.assertIn(9, report["slots"][1]["candidate_run_ids"])

    def test_failed_primary_is_recovered_by_successful_retry(self):
        runs = [
            {"id": 1, "event": "schedule", "created_at": "2026-09-14T13:35:00Z", "conclusion": "failure"},
            {"id": 2, "event": "schedule", "created_at": "2026-09-14T13:45:00Z", "conclusion": "success"},
        ]
        report = reconcile_day(session_date=date(2026, 9, 14), runs=runs)
        self.assertEqual(report["slots"][0]["status"], "matched")
        self.assertEqual(report["slots"][0]["matched_run_id"], 2)
        self.assertEqual(report["slots"][0]["candidate_run_ids"], [1, 2])

    def test_all_attempts_failed_marks_slot_failed(self):
        runs = [
            {"id": 1, "event": "schedule", "created_at": "2026-09-14T13:35:00Z", "conclusion": "failure"},
            {"id": 2, "event": "schedule", "created_at": "2026-09-14T13:45:00Z", "conclusion": "cancelled"},
        ]
        report = reconcile_day(session_date=date(2026, 9, 14), runs=runs)
        self.assertEqual(report["slots"][0]["status"], "failed")
        self.assertFalse(report["healthy"])

    def test_manual_dispatch_is_ignored(self):
        runs = [{"id": 99, "event": "workflow_dispatch", "created_at": "2026-09-14T13:40:00Z"}]
        report = reconcile_day(session_date=date(2026, 9, 14), runs=runs)
        self.assertEqual(report["counts"]["matched"], 0)
        self.assertEqual(report["counts"]["missing"], 7)

    def test_weekend_has_no_expected_slots(self):
        report = reconcile_day(session_date=date(2026, 9, 13), runs=[])
        self.assertEqual(report["slot_count"], 0)
        self.assertTrue(report["healthy"])


if __name__ == "__main__":
    unittest.main()
