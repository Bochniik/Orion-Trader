from __future__ import annotations

from datetime import date
import unittest

from build_regular_hours_operational_acceptance import build_operational_acceptance_report
from audit_regular_hours_collection_health import PREDICTIVE_LINEAGE_FILES


HEAD_SHA = "b" * 40


def _digest() -> str:
    return "a" * 64


def _payload(run_id: int, as_of_et: str) -> dict:
    symbols = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ"]
    rows = {symbol: {"available": True, "source_timestamp_aligned": True, "as_of": as_of_et, "alignment_attempts": 1} for symbol in symbols}
    return {
        "runner_version": "regular-hours-v3-1-cloud-shadow-v2",
        "research_only": True,
        "order_submission_enabled": False,
        "runtime_modified": False,
        "status": "completed",
        "session_gate": {"as_of_et": as_of_et, "allowed": True},
        "symbols_requested": symbols,
        "results": {"symbols": rows, "failures": {}, "symbol_count": 10, "available_symbol_count": 10, "provenance_valid_symbol_count": 10, "alignment_retry_symbol_count": 0, "alignment_attempt_count": 10, "failure_count": 0},
        "lineage": {"files_sha256": {path: _digest() for path in PREDICTIVE_LINEAGE_FILES}},
        "acquisition_provenance": {
            "schema": "regular-hours-v3-1-acquisition-provenance-v1",
            "collected_live": True,
            "event_name": "schedule",
            "workflow_run_id": run_id,
            "run_attempt": 1,
            "github_head_sha": HEAD_SHA,
            "collection_started_at_utc": "2026-09-15T13:35:10+00:00",
            "collection_completed_at_utc": "2026-09-15T13:36:00+00:00",
            "source_payload_sha256": _digest(),
            "forward_eligible": True,
        },
    }


def _fixtures():
    runs = []
    artifacts = []
    payloads = {}
    for offset, hour in enumerate(range(13, 20), start=1):
        run_id = 1000 + offset
        runs.append({"id": run_id, "event": "schedule", "created_at": f"2026-09-15T{hour}:36:00Z", "conclusion": "success", "run_attempt": 1, "head_sha": HEAD_SHA})
        artifact_id = 2000 + offset
        artifacts.append({"id": artifact_id, "name": f"regular-hours-v3-1-shadow-{run_id}", "expired": False, "workflow_run": {"id": run_id}})
        et_hour = 9 + offset - 1
        payloads[str(artifact_id)] = _payload(run_id, f"2026-09-15T{et_hour:02d}:36:00-04:00")
    return runs, artifacts, payloads


class OperationalAcceptanceTests(unittest.TestCase):
    def test_complete_day_with_real_forward_provenance_is_accepted(self):
        runs, artifacts, payloads = _fixtures()
        report = build_operational_acceptance_report(session_date=date(2026, 9, 15), runs=runs, artifacts=artifacts, artifact_payloads=payloads)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["contract"], "orion-regular-hours-operational-acceptance-v2")
        self.assertEqual(report["expected_slot_count"], 7)
        self.assertEqual(report["healthy_slot_count"], 7)
        self.assertEqual(report["acceptance_rate"], 1.0)

    def test_missing_artifact_is_not_accepted(self):
        runs, artifacts, payloads = _fixtures()
        artifacts.pop(3)
        report = build_operational_acceptance_report(session_date=date(2026, 9, 15), runs=runs, artifacts=artifacts, artifact_payloads=payloads)
        self.assertFalse(report["healthy"])
        self.assertEqual(report["counts"]["artifact_missing"], 1)

    def test_failed_run_is_not_accepted_even_with_valid_artifact(self):
        runs, artifacts, payloads = _fixtures()
        runs[2]["conclusion"] = "failure"
        report = build_operational_acceptance_report(session_date=date(2026, 9, 15), runs=runs, artifacts=artifacts, artifact_payloads=payloads)
        self.assertEqual(report["counts"]["run_failed"], 1)

    def test_cross_run_acquisition_provenance_is_rejected(self):
        runs, artifacts, payloads = _fixtures()
        payloads[str(artifacts[0]["id"])]["acquisition_provenance"]["workflow_run_id"] = 999999
        report = build_operational_acceptance_report(session_date=date(2026, 9, 15), runs=runs, artifacts=artifacts, artifact_payloads=payloads)
        self.assertEqual(report["counts"]["artifact_invalid"], 1)

    def test_wrong_attempt_is_rejected(self):
        runs, artifacts, payloads = _fixtures()
        payloads[str(artifacts[0]["id"])]["acquisition_provenance"]["run_attempt"] = 2
        report = build_operational_acceptance_report(session_date=date(2026, 9, 15), runs=runs, artifacts=artifacts, artifact_payloads=payloads)
        self.assertEqual(report["counts"]["artifact_invalid"], 1)

    def test_wrong_head_sha_is_rejected(self):
        runs, artifacts, payloads = _fixtures()
        payloads[str(artifacts[0]["id"])]["acquisition_provenance"]["github_head_sha"] = "c" * 40
        report = build_operational_acceptance_report(session_date=date(2026, 9, 15), runs=runs, artifacts=artifacts, artifact_payloads=payloads)
        self.assertEqual(report["counts"]["artifact_invalid"], 1)

    def test_non_forward_or_manual_provenance_is_rejected(self):
        runs, artifacts, payloads = _fixtures()
        payloads[str(artifacts[0]["id"])]["acquisition_provenance"]["forward_eligible"] = False
        payloads[str(artifacts[1]["id"])]["acquisition_provenance"]["event_name"] = "workflow_dispatch"
        report = build_operational_acceptance_report(session_date=date(2026, 9, 15), runs=runs, artifacts=artifacts, artifact_payloads=payloads)
        self.assertEqual(report["counts"]["artifact_invalid"], 2)

    def test_legacy_fake_provenance_field_is_rejected(self):
        runs, artifacts, payloads = _fixtures()
        payload = payloads[str(artifacts[0]["id"])]
        payload.pop("acquisition_provenance")
        payload["provenance"] = {"github_run_id": str(runs[0]["id"])}
        report = build_operational_acceptance_report(session_date=date(2026, 9, 15), runs=runs, artifacts=artifacts, artifact_payloads=payloads)
        self.assertEqual(report["counts"]["artifact_invalid"], 1)

    def test_adjacent_slot_boundary_is_not_reused_for_previous_slot(self):
        runs, artifacts, payloads = _fixtures()
        runs[0]["created_at"] = "2026-09-15T14:35:00Z"
        report = build_operational_acceptance_report(session_date=date(2026, 9, 15), runs=runs, artifacts=artifacts, artifact_payloads=payloads)
        self.assertFalse(report["healthy"])
        self.assertEqual(report["counts"].get("missing", 0), 1)


if __name__ == "__main__":
    unittest.main()
