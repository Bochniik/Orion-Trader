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


HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40


def _artifact_zip(payload: dict, *, filename: str = "prediction-late-123.json") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, json.dumps(payload))
        archive.writestr(filename.replace(".json", ".manifest.json"), "{}")
    return buffer.getvalue()


def _payload(run_id: str = "123", run_attempt: int = 1, head_sha: str = HEAD_SHA) -> dict:
    return {
        "runner_version": "premarket-v5-cloud-shadow-v2",
        "acquisition_provenance": {
            "github_run_id": run_id,
            "github_run_attempt": run_attempt,
            "github_head_sha": head_sha,
        },
        "predictions": [],
    }


def _artifact(*, retention_days: int = 90) -> dict:
    if retention_days == 90:
        expires_at = "2026-12-13T13:20:00Z"
    elif retention_days == 30:
        expires_at = "2026-10-14T13:20:00Z"
    else:
        raise AssertionError("unsupported fixture retention")
    return {
        "id": 9,
        "name": "premarket-v5-shadow-late-123",
        "expired": False,
        "created_at": "2026-09-14T13:20:00Z",
        "expires_at": expires_at,
    }


def test_normalize_run_keeps_score_blind_delivery_and_commit_identity():
    raw = {
        "id": 123,
        "event": "schedule",
        "display_title": "Premarket V5 schedule 15 13 * * 1-5",
        "created_at": "2026-09-14T13:15:04Z",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 2,
        "head_sha": HEAD_SHA,
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
        "head_sha": HEAD_SHA,
    }

    bad = dict(raw)
    bad["head_sha"] = "bad"
    with pytest.raises(actions.ActionsEvidenceError, match="40-character"):
        actions.normalize_run(bad)


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


def test_select_shadow_artifact_ignores_expired_wrong_run_and_rejects_ambiguity():
    assert actions.select_shadow_artifact(
        [{"id": 1, "name": "premarket-v5-shadow-late-123", "expired": True}], run_id="123"
    ) is None
    assert actions.select_shadow_artifact(
        [{"id": 1, "name": "premarket-v5-shadow-late-999", "expired": False}], run_id="123"
    ) is None
    with pytest.raises(actions.ActionsEvidenceError, match="ambiguous"):
        actions.select_shadow_artifact(
            [
                {"id": 1, "name": "premarket-v5-shadow-late-123", "expired": False},
                {"id": 2, "name": "premarket-v5-shadow-copy-123", "expired": False},
            ],
            run_id="123",
        )


def test_artifact_retention_contract_requires_real_90_day_api_retention():
    expires_at, observed_days = actions.artifact_retention_contract(_artifact(retention_days=90), run_id="123")
    assert expires_at == "2026-12-13T13:20:00Z"
    assert observed_days == pytest.approx(90.0)

    with pytest.raises(actions.ActionsEvidenceError, match="requires at least 90 days"):
        actions.artifact_retention_contract(_artifact(retention_days=30), run_id="123")

    missing_expiry = _artifact(retention_days=90)
    missing_expiry.pop("expires_at")
    with pytest.raises(actions.ActionsEvidenceError, match="expires_at must be ISO-8601"):
        actions.artifact_retention_contract(missing_expiry, run_id="123")


def test_prediction_payload_from_zip_requires_run_attempt_and_commit_binding():
    parsed = actions.prediction_payload_from_zip(
        _artifact_zip(_payload()), run_id="123", run_attempt=1, head_sha=HEAD_SHA
    )
    assert parsed["acquisition_provenance"]["github_run_id"] == "123"
    assert parsed["acquisition_provenance"]["github_run_attempt"] == 1
    assert parsed["acquisition_provenance"]["github_head_sha"] == HEAD_SHA

    with pytest.raises(actions.ActionsEvidenceError, match="not bound"):
        actions.prediction_payload_from_zip(
            _artifact_zip(_payload("999")), run_id="123", run_attempt=1, head_sha=HEAD_SHA
        )

    with pytest.raises(actions.ActionsEvidenceError, match="does not match workflow attempt"):
        actions.prediction_payload_from_zip(
            _artifact_zip(_payload("123", 1)), run_id="123", run_attempt=2, head_sha=HEAD_SHA
        )

    with pytest.raises(actions.ActionsEvidenceError, match="does not match workflow head_sha"):
        actions.prediction_payload_from_zip(
            _artifact_zip(_payload(head_sha=OTHER_SHA)), run_id="123", run_attempt=1, head_sha=HEAD_SHA
        )

    missing_attempt = _payload()
    missing_attempt["acquisition_provenance"].pop("github_run_attempt")
    with pytest.raises(actions.ActionsEvidenceError, match="invalid github_run_attempt"):
        actions.prediction_payload_from_zip(
            _artifact_zip(missing_attempt), run_id="123", run_attempt=1, head_sha=HEAD_SHA
        )

    missing_sha = _payload()
    missing_sha["acquisition_provenance"].pop("github_head_sha")
    with pytest.raises(actions.ActionsEvidenceError, match="prediction github_head_sha"):
        actions.prediction_payload_from_zip(
            _artifact_zip(missing_sha), run_id="123", run_attempt=1, head_sha=HEAD_SHA
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../prediction-late-123.json", json.dumps(_payload()))
    with pytest.raises(actions.ActionsEvidenceError, match="unsafe path"):
        actions.prediction_payload_from_zip(buffer.getvalue(), run_id="123", run_attempt=1, head_sha=HEAD_SHA)


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
                "head_sha": HEAD_SHA,
            },
            {
                "id": "124",
                "event": "schedule",
                "display_title": "Premarket V5 schedule 15 14 * * 1-5",
                "created_at": "2026-09-14T14:15:03Z",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "head_sha": HEAD_SHA,
            },
            {
                "id": "125",
                "event": "schedule",
                "display_title": "Premarket V5 schedule 0 12 * * 1-5",
                "created_at": "2026-09-14T12:00:02Z",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 1,
                "head_sha": HEAD_SHA,
            },
        ]

    def run_artifacts(self, run_id: str):
        if run_id == "123":
            return [_artifact(retention_days=90)]
        return []

    def download_artifact(self, artifact_id: int):
        assert artifact_id == 9
        return _artifact_zip(_payload("123", 1, HEAD_SHA))


def test_collect_preserves_failed_runs_and_reports_success_without_live_artifact():
    runs, payloads, summary = actions.collect(_FakeClient(), start_date=date(2026, 9, 14))
    assert len(runs) == 3
    assert [payload["acquisition_provenance"]["github_run_id"] for payload in payloads] == ["123"]
    assert runs[0]["head_sha"] == HEAD_SHA
    assert summary["score_blind"] is True
    assert summary["scheduled_run_count"] == 3
    assert summary["prediction_artifact_count"] == 1
    assert summary["successful_runs_missing_live_artifact_ids"] == ["124"]
    assert summary["required_artifact_retention_days"] == 90
    assert summary["minimum_observed_artifact_retention_days"] == pytest.approx(90.0)
    assert summary["earliest_live_artifact_expires_at"] == "2026-12-13T13:20:00Z"
