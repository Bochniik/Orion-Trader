from datetime import datetime, timezone

import pytest

import scripts.finalize_premarket_v5_forward_artifact as attestation


def _payload():
    return {
        "mode": "shadow_research_only",
        "order_submission_enabled": False,
        "causal_cutoff_enforced": True,
        "as_of_utc": "2026-09-14T13:15:00+00:00",
    }


def test_scheduled_attestation_requires_and_records_exact_head_sha():
    started = datetime(2026, 9, 14, 13, 16, tzinfo=timezone.utc)
    completed = datetime(2026, 9, 14, 13, 18, tzinfo=timezone.utc)
    sha = "a" * 40
    result = attestation.finalize_payload(
        _payload(), collection_started_at=started, collection_completed_at=completed,
        event_name="schedule", run_id="123", run_attempt=1, github_head_sha=sha,
    )
    assert result["acquisition_provenance"]["github_head_sha"] == sha
    assert result["acquisition_provenance"]["contract"] == "orion-premarket-v5-forward-acquisition-v2"


def test_scheduled_attestation_fails_closed_without_valid_head_sha():
    started = datetime(2026, 9, 14, 13, 16, tzinfo=timezone.utc)
    completed = datetime(2026, 9, 14, 13, 18, tzinfo=timezone.utc)
    with pytest.raises(attestation.ForwardAcquisitionError, match="requires GitHub head SHA"):
        attestation.finalize_payload(
            _payload(), collection_started_at=started, collection_completed_at=completed,
            event_name="schedule", run_id="123", run_attempt=1,
        )
    with pytest.raises(attestation.ForwardAcquisitionError, match="40-character"):
        attestation.finalize_payload(
            _payload(), collection_started_at=started, collection_completed_at=completed,
            event_name="schedule", run_id="123", run_attempt=1, github_head_sha="bad",
        )
