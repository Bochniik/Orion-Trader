import io
import json
import unittest
import zipfile

from scripts.collect_regular_hours_v3_1_actions_evidence import (
    ActionsEvidenceError,
    WORKFLOW_FILE,
    prediction_payload_from_zip,
    select_artifact,
)

SHA = "a" * 40


def blob(payload, name="prediction-42.json"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(name, json.dumps(payload))
    return out.getvalue()


def payload(**overrides):
    provenance = {
        "workflow_run_id": 42,
        "run_attempt": 1,
        "github_head_sha": SHA,
        "event_name": "schedule",
        "forward_eligible": True,
    }
    provenance.update(overrides)
    return {"acquisition_provenance": provenance}


class CollectorRegressionTests(unittest.TestCase):
    def test_workflow_contract(self):
        self.assertEqual(WORKFLOW_FILE, "market-acquisition-scheduler.yml")

    def test_selects_exact_nonexpired_artifact(self):
        self.assertIsNotNone(
            select_artifact(
                [{"name": "regular-hours-v3-1-shadow-42", "expired": False}],
                run_id="42",
            )
        )
        self.assertIsNone(
            select_artifact(
                [{"name": "regular-hours-v3-1-shadow-42", "expired": True}],
                run_id="42",
            )
        )

    def test_accepts_bound_scheduled_forward_payload(self):
        observed = prediction_payload_from_zip(
            blob(payload()), run_id="42", run_attempt=1, head_sha=SHA
        )
        self.assertEqual(observed["acquisition_provenance"]["workflow_run_id"], 42)

    def test_rejects_provenance_mismatches(self):
        cases = (
            payload(workflow_run_id=99),
            payload(run_attempt=2),
            payload(github_head_sha="b" * 40),
            payload(forward_eligible=False),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ActionsEvidenceError):
                    prediction_payload_from_zip(
                        blob(candidate), run_id="42", run_attempt=1, head_sha=SHA
                    )

    def test_rejects_zip_path_traversal(self):
        unsafe = io.BytesIO()
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr("../prediction-42.json", json.dumps(payload()))
        with self.assertRaises(ActionsEvidenceError):
            prediction_payload_from_zip(
                unsafe.getvalue(), run_id="42", run_attempt=1, head_sha=SHA
            )


if __name__ == "__main__":
    unittest.main()
