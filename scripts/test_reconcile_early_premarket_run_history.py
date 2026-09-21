from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from reconcile_early_premarket_run_history import WORKFLOW_NAME, reconcile


class ReconcileRunHistoryTests(unittest.TestCase):
    def test_explicit_slot_identity_counts_coverage(self) -> None:
        report = reconcile(
            session_date=date(2026, 9, 21),
            observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
            raw_runs=[{
                "id": 101,
                "name": WORKFLOW_NAME,
                "created_at": "2026-09-21T08:06:00Z",
                "conclusion": "success",
                "target_slot_et": "2026-09-21T04:05:00-04:00",
            }],
        )
        self.assertEqual(report["metrics"]["mature_slot_count"], 1)
        self.assertEqual(report["metrics"]["successful_slot_count"], 1)
        self.assertEqual(report["metrics"]["coverage_ratio"], 1.0)

    def test_created_at_is_never_used_to_infer_target_slot(self) -> None:
        report = reconcile(
            session_date=date(2026, 9, 21),
            observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
            raw_runs=[{
                "id": 102,
                "name": WORKFLOW_NAME,
                "created_at": "2026-09-21T08:05:01Z",
                "conclusion": "success",
            }],
        )
        self.assertEqual(report["metrics"]["successful_slot_count"], 0)
        self.assertEqual(report["metrics"]["unattributed_run_count"], 1)
        self.assertEqual(report["health"]["slots"][0]["status"], "workflow_never_created")

    def test_failed_explicit_run_is_not_coverage(self) -> None:
        report = reconcile(
            session_date=date(2026, 9, 21),
            observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
            raw_runs=[{
                "id": 103,
                "name": WORKFLOW_NAME,
                "created_at": "2026-09-21T08:06:00Z",
                "conclusion": "failure",
                "target_slot_et": "2026-09-21T04:05:00-04:00",
            }],
        )
        self.assertEqual(report["metrics"]["coverage_ratio"], 0.0)
        self.assertEqual(report["health"]["slots"][0]["status"], "workflow_created_collector_failed")

    def test_other_workflows_are_ignored(self) -> None:
        report = reconcile(
            session_date=date(2026, 9, 21),
            observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
            raw_runs=[{
                "id": 104,
                "name": "Backend analytics regression",
                "created_at": "2026-09-21T08:06:00Z",
                "conclusion": "success",
                "target_slot_et": "2026-09-21T04:05:00-04:00",
            }],
        )
        self.assertEqual(report["ignored_run_ids"], ["104"])
        self.assertEqual(report["metrics"]["normalized_workflow_run_count"], 0)


if __name__ == "__main__":
    unittest.main()
