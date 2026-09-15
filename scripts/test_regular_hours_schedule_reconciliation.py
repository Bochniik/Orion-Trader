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
        self.assertEqual(report["counts"], {"matched": 7, "missing": 0, "ambiguous": 0})
        self.assertEqual([item["matched_run_id"] for item in report["slots"]], list(range(1, 8)))

    def test_missing_slot_is_not_filled_by_later_run(self):
        runs = [
            {"id": 1, "event": "schedule", "created_at": "2026-09-14T13:45:00Z"},
            {"id": 2, "event": "schedule", "created_at": "2026-09-14T15:45:00Z"},
        ]
        report = reconcile_day(session_date=date(2026, 9, 14), runs=runs)
        self.assertEqual(report["slots"][1]["status"], "missing")
        self.assertFalse(report["healthy"])

    def test_boundary_run_is_ambiguous_not_guessed(self):
        # 14:35 is both exactly 60m after 13:35 and exactly the next slot.
        runs = [{"id": 9, "event": "schedule", "created_at": "2026-09-14T14:35:00Z"}]
        report = reconcile_day(session_date=date(2026, 9, 14), runs=runs)
        self.assertEqual(report["slots"][0]["status"], "ambiguous")
        self.assertEqual(report["slots"][1]["status"], "ambiguous")
        self.assertIn(9, report["slots"][0]["candidate_run_ids"])
        self.assertIn(9, report["slots"][1]["candidate_run_ids"])

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
