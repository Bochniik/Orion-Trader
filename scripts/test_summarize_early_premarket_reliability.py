import unittest

from summarize_early_premarket_reliability import summarize


def report(day, statuses, *, attributed=1, unattributed=0):
    slots = []
    for i, status in enumerate(statuses):
        slots.append({"status": status, "duplicate_run_count": 1 if i == 0 and status == "collector_succeeded" else 0})
    successful = statuses.count("collector_succeeded")
    return {
        "contract": "orion-early-premarket-run-history-reconciliation-v2",
        "health": {"session_date": day, "slots": slots},
        "metrics": {
            "mature_slot_count": len(statuses),
            "successful_slot_count": successful,
            "attributed_run_count": attributed,
            "unattributed_run_count": unattributed,
        },
    }


class ReliabilitySummaryTests(unittest.TestCase):
    def test_aggregates_acquisition_failure_modes(self):
        result = summarize([
            report("2026-09-17", ["collector_succeeded", "workflow_never_created"], unattributed=1),
            report("2026-09-18", ["collector_succeeded", "workflow_created_collector_failed"]),
        ])
        agg = result["aggregate"]
        self.assertEqual(result["session_count"], 2)
        self.assertEqual(agg["mature_slot_count"], 4)
        self.assertEqual(agg["successful_slot_count"], 2)
        self.assertEqual(agg["coverage_ratio"], 0.5)
        self.assertEqual(agg["missing_workflow_rate"], 0.25)
        self.assertEqual(agg["collector_failure_rate"], 0.25)
        self.assertEqual(agg["duplicate_slot_rate"], 0.5)
        self.assertAlmostEqual(agg["unattributed_evidence_rate"], 1 / 3)

    def test_rejects_duplicate_session_reports(self):
        with self.assertRaisesRegex(ValueError, "duplicate session"):
            summarize([report("2026-09-17", ["collector_succeeded"]), report("2026-09-17", ["collector_succeeded"])])

    def test_rejects_slot_accounting_mismatch(self):
        broken = report("2026-09-17", ["collector_succeeded"])
        broken["metrics"]["mature_slot_count"] = 2
        with self.assertRaisesRegex(ValueError, "slot accounting mismatch"):
            summarize([broken])

    def test_rejects_unknown_contract(self):
        broken = report("2026-09-17", ["collector_succeeded"])
        broken["contract"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unsupported reconciliation contract"):
            summarize([broken])


if __name__ == "__main__":
    unittest.main()
