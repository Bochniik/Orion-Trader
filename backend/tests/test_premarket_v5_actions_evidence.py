from __future__ import annotations

from datetime import date
import io
import json
from pathlib import Path
import sys
import urllib.request
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.collect_premarket_v5_actions_evidence as actions


def _artifact_zip(payload: dict, *, filename: str = "prediction-late-123.json") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, json.dumps(payload))
        archive.writestr(filename.replace(".json", ".manifest.json"), "{}")
    return buffer.getvalue()


def _payload(run_id: str = "123") -> dict:
    return {
        "runner_version": "premarket-v5-cloud-shadow-v2",
        "acquisition_provenance": {"github_run_id": run_id},
        "predictions": [],
    }


def test_normalize_run_keeps_only_score_blind_delivery_fields():
    raw = {
        "id": 123,
        "event": "schedule",
        "display_title": "Premarket V5 schedule 15 13 * * 1-5",
        "created_at": "2026-09-14T13:15:04Z",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 2,
        "head_sha": "secret-not-needed",
    }
    normalized = actions.normalize_run(raw)
    assert normalized == {
        "id": "123",
        "event": "schedule",
        "display_title": raw["display_title"],
        "created_at": raw["created_at"],
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 2,
    }


def test_cross_host_redirect_strips_github_bearer_token():
    request = urllib.request.Request(
        "https://api.github.com/repos/o/r/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer secret", "Accept": "application/octet-stream"},
    )
    redirected = actions._SafeRedirectHandler().redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://artifact-cache.example.net/signed.zip",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Accept") == "application/octet-stream"


def test_select_shadow_artifact_ignores_expired_and_rejects_ambiguity():
    assert actions.select_shadow_artifact(
        [{"id": 1, "name": "premarket-v5-shadow-late-123", "expired": True}], run_id="123"
    ) is None
    with pytest.raises(actions.ActionsEvidenceError, match="ambiguous"):
        actions.select_shadow_artifact(
            [
                {"id": 1, "name": "premarket-v5-shadow-late-123", "expired": False},
                {"id": 2, "name": "premarket-v5-shadow-copy-123", "expired": False},
            ],
            run_id="123",
        )


def test_prediction_payload_from_zip_requires_run_binding_and_safe_single_payload():
    parsed = actions.prediction_payload_from_zip(_artifact_zip(_payload()), run_id="123")
    assert parsed["acquisition_provenance"]["github_run_id"] == "123"

    with pytest.raises(actions.ActionsEvidenceError, match="not bound"):
        actions.prediction_payload_from_zip(_artifact_zip(_payload("999")), run_id="123")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../prediction-late-123.json", json.dumps(_payload()))
    with pytest.raises(actions.ActionsEvidenceError, match="unsafe path"):
        actions.prediction_payload_from_zip(buffer.getvalue(), run_id="123")


class _FakeClient:
    def scheduled_runs(self, *, start_date: date):
        assert start_date == date(2026, 9, 14)
        return [
            {
                "id": "123",
                "event": "schedule",
                "display_title": "Premarket V5 schedule 15 13 * * 1-5",
                "created_at": "2026-09-14T13:15:04Z",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            },
            {
                "id": "124",
                "event": "schedule",
                "display_title": "Premarket V5 schedule 15 14 * * 1-5",
                "created_at": "2026-09-14T14:15:03Z",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            },
            {
                "id": "125",
                "event": "schedule",
                "display_title": "Premarket V5 schedule 0 12 * * 1-5",
                "created_at": "2026-09-14T12:00:02Z",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 1,
            },
        ]

    def run_artifacts(self, run_id: str):
        if run_id == "123":
            return [{"id": 9, "name": "premarket-v5-shadow-late-123", "expired": False}]
        return []

    def download_artifact(self, artifact_id: int):
        assert artifact_id == 9
        return _artifact_zip(_payload("123"))


def test_collect_preserves_failed_runs_and_reports_success_without_live_artifact():
    runs, payloads, summary = actions.collect(_FakeClient(), start_date=date(2026, 9, 14))
    assert len(runs) == 3
    assert [payload["acquisition_provenance"]["github_run_id"] for payload in payloads] == ["123"]
    assert summary["score_blind"] is True
    assert summary["scheduled_run_count"] == 3
    assert summary["prediction_artifact_count"] == 1
    assert summary["successful_runs_missing_live_artifact_ids"] == ["124"]
