from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.finalize_regular_hours_v3_1_forward_artifact import ForwardArtifactError, finalize_payload


def _payload(*, allowed: bool = True, status: str = "completed") -> dict:
    return {
        "contract": "orion-regular-hours-cloud-shadow-v2",
        "runner_version": "regular-hours-v3-1-cloud-shadow-v2",
        "session_gate": {
            "allowed": allowed,
            "as_of_et": "2026-09-14T10:35:00-04:00",
            "reason": None if allowed else "outside_regular_hours_shadow_window",
        },
        "symbols_requested": ["AAPL"],
        "research_only": True,
        "order_submission_enabled": False,
        "runtime_modified": False,
        "status": status,
        "results": {},
    }


def _finalize(payload: dict, *, event_name: str = "schedule"):
    return finalize_payload(
        payload,
        collection_started_at="2026-09-14T14:35:01Z",
        collection_completed_at="2026-09-14T14:35:09Z",
        event_name=event_name,
        run_id=123,
        run_attempt=1,
        github_head_sha="a" * 40,
    )


def test_scheduled_active_artifact_is_forward_eligible_and_content_addressed() -> None:
    source = _payload()
    original = deepcopy(source)
    finalized, manifest = _finalize(source)

    provenance = finalized["acquisition_provenance"]
    assert provenance["event_name"] == "schedule"
    assert provenance["workflow_run_id"] == 123
    assert provenance["run_attempt"] == 1
    assert provenance["github_head_sha"] == "a" * 40
    assert provenance["forward_eligible"] is True
    assert len(provenance["source_payload_sha256"]) == 64
    assert manifest["forward_eligible"] is True
    assert len(manifest["finalized_payload_sha256"]) == 64
    assert source == original


def test_manual_dispatch_is_diagnostic_only() -> None:
    finalized, manifest = _finalize(_payload(), event_name="workflow_dispatch")
    assert finalized["acquisition_provenance"]["forward_eligible"] is False
    assert manifest["forward_eligible"] is False


def test_scheduled_off_session_artifact_is_not_forward_eligible() -> None:
    finalized, _ = _finalize(_payload(allowed=False, status="skipped"))
    assert finalized["acquisition_provenance"]["forward_eligible"] is False


def test_invalid_run_identity_fails_closed() -> None:
    with pytest.raises(ForwardArtifactError, match="positive"):
        finalize_payload(
            _payload(),
            collection_started_at="2026-09-14T14:35:01Z",
            collection_completed_at="2026-09-14T14:35:09Z",
            event_name="schedule",
            run_id=0,
            run_attempt=1,
            github_head_sha="a" * 40,
        )
    with pytest.raises(ForwardArtifactError, match="Git SHA"):
        finalize_payload(
            _payload(),
            collection_started_at="2026-09-14T14:35:01Z",
            collection_completed_at="2026-09-14T14:35:09Z",
            event_name="schedule",
            run_id=1,
            run_attempt=1,
            github_head_sha="bad",
        )


def test_backward_collection_window_fails_closed() -> None:
    with pytest.raises(ForwardArtifactError, match=">="):
        finalize_payload(
            _payload(),
            collection_started_at="2026-09-14T14:35:09Z",
            collection_completed_at="2026-09-14T14:35:01Z",
            event_name="schedule",
            run_id=1,
            run_attempt=1,
            github_head_sha="a" * 40,
        )


def test_double_finalization_is_rejected() -> None:
    finalized, _ = _finalize(_payload())
    with pytest.raises(ForwardArtifactError, match="already finalized"):
        _finalize(finalized)
