from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from reconcile_early_premarket_run_history import WORKFLOW_NAME, reconcile


class ReconcileRunHistoryTests(unittest.TestCase):
    def _run(self, run_id: int, **extra):
        return {
            "id": run_id,
            "name": WORKFLOW_NAME,
            "created_at": "2026-09-21T08:06:00Z",
            "conclusion": "success",
            **extra,
        }

    def test_explicit_slot_identity_counts_coverage(self) -> None:
        report = reconcile(
            session_date=date(2026, 9, 21),
            observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
            raw_runs=[self._run(101, target_slot_et="2026-09-21T04:05:00-04:00")],
        )
        self.assertEqual(report["metrics"]["mature_slot_count"], 1)
        self.assertEqual(report["metrics"]["successful_slot_count"], 1)
        self.assertEqual(report["metrics"]["coverage_ratio"], 1.0)

    def test_identity_artifact_attributes_run_without_timestamp_inference(self) -> None:
        report = reconcile(
            session_date=date(2026, 9, 21),
            observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
            raw_runs=[self._run(105)],
            raw_identities=[{
                "github_run_id": "105",
                "target_slot_et": "2026-09-21T04:05:00-04:00",
            }],
        )
        self.assertEqual(report["metrics"]["successful_slot_count"], 1)
        self.assertEqual(report["metrics"]["attributed_run_count"], 1)
        self.assertEqual(report["metrics"]["unattributed_run_count"], 0)

    def test_created_at_is_never_used_to_infer_target_slot(self) -> None:
        report = reconcile(
            session_date=date(2026, 9, 21),
            observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
            raw_runs=[self._run(102, created_at="2026-09-21T08:05:01Z")],
        )
        self.assertEqual(report["metrics"]["successful_slot_count"], 0)
        self.assertEqual(report["metrics"]["unattributed_run_count"], 1)
        self.assertEqual(report["health"]["slots"][0]["status"], "workflow_never_created")

    def test_failed_explicit_run_is_not_coverage(self) -> None:
        report = reconcile(
            session_date=date(2026, 9, 21),
            observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
            raw_runs=[self._run(103, conclusion="failure", target_slot_et="2026-09-21T04:05:00-04:00")],
        )
        self.assertEqual(report["metrics"]["coverage_ratio"], 0.0)
        self.assertEqual(report["health"]["slots"][0]["status"], "workflow_created_collector_failed")

    def test_conflicting_artifact_identity_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicting target_slot_et"):
            reconcile(
                session_date=date(2026, 9, 21),
                observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
                raw_runs=[self._run(106)],
                raw_identities=[
                    {"github_run_id": "106", "target_slot_et": "2026-09-21T04:05:00-04:00"},
                    {"github_run_id": "106", "target_slot_et": "2026-09-21T04:35:00-04:00"},
                ],
            )

    def test_inline_artifact_disagreement_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicting inline/artifact"):
            reconcile(
                session_date=date(2026, 9, 21),
                observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
                raw_runs=[self._run(107, target_slot_et="2026-09-21T04:05:00-04:00")],
                raw_identities=[{"github_run_id": "107", "target_slot_et": "2026-09-21T04:35:00-04:00"}],
            )

    def test_other_workflows_are_ignored(self) -> None:
        run = self._run(104, target_slot_et="2026-09-21T04:05:00-04:00")
        run["name"] = "Backend analytics regression"
        report = reconcile(
            session_date=date(2026, 9, 21),
            observed_at_utc=datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc),
            raw_runs=[run],
        )
        self.assertEqual(report["ignored_run_ids"], ["104"])
        self.assertEqual(report["metrics"]["normalized_workflow_run_count"], 0)


if __name__ == "__main__":
    unittest.main()
