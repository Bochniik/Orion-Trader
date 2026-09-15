import unittest

from audit_regular_hours_slot_evidence_health import build_slot_evidence_report


class SlotEvidenceHealthTests(unittest.TestCase):
    def reconciliation(self, status="matched", run_id=101):
        return {
            "contract": "orion-regular-hours-daily-schedule-reconciliation-v1",
            "session_date_et": "2026-09-14",
            "slots": [{
                "slot_utc": "2026-09-14T13:35:00+00:00",
                "slot_et": "2026-09-14T09:35:00-04:00",
                "status": status,
                "matched_run_id": run_id,
            }],
        }

    def test_healthy_requires_successful_run_and_valid_artifact(self):
        report = build_slot_evidence_report(self.reconciliation(), {
            "101": {"run_conclusion": "success", "artifact_present": True, "artifact_valid": True}
        })
        self.assertTrue(report["healthy"])
        self.assertEqual(report["slots"][0]["evidence_status"], "healthy")

    def test_successful_run_without_artifact_is_not_healthy(self):
        report = build_slot_evidence_report(self.reconciliation(), {
            "101": {"run_conclusion": "success", "artifact_present": False, "artifact_valid": False}
        })
        self.assertFalse(report["healthy"])
        self.assertEqual(report["slots"][0]["evidence_status"], "artifact_missing")

    def test_failed_run_is_reported_before_artifact_state(self):
        report = build_slot_evidence_report(self.reconciliation(), {
            "101": {"run_conclusion": "failure", "artifact_present": True, "artifact_valid": True}
        })
        self.assertEqual(report["slots"][0]["evidence_status"], "run_failed")

    def test_ambiguous_schedule_never_attributes_evidence(self):
        report = build_slot_evidence_report(self.reconciliation(status="ambiguous", run_id=None), {
            "101": {"run_conclusion": "success", "artifact_present": True, "artifact_valid": True}
        })
        self.assertEqual(report["slots"][0]["evidence_status"], "ambiguous")
        self.assertFalse(report["healthy"])

    def test_invalid_artifact_preserves_validation_error(self):
        report = build_slot_evidence_report(self.reconciliation(), {
            "101": {"run_conclusion": "success", "artifact_present": True, "artifact_valid": False, "artifact_error": "manifest digest mismatch"}
        })
        self.assertEqual(report["slots"][0]["evidence_status"], "artifact_invalid")
        self.assertIn("manifest digest mismatch", report["slots"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
