from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts.build_early_premarket_session_evidence import build_session_evidence


def _run(run_id: int, *, slot: str | None = None, conclusion: str = "success"):
    row = {
        "id": run_id,
        "name": "Early premarket observational collection",
        "created_at": "2026-09-21T08:06:00Z",
        "conclusion": conclusion,
    }
    if slot is not None:
        row["target_slot_et"] = slot
    return row


def _identity(tmp_path: Path, run_id: int, slot: str) -> Path:
    path = tmp_path / f"identity-{run_id}.txt"
    path.write_text(f"github_run_id={run_id}\ntarget_slot_et={slot}\n", encoding="utf-8")
    return path


def test_explicit_identity_attributes_run_without_timestamp_inference(tmp_path):
    evidence = build_session_evidence(
        session_date=date(2026, 9, 21),
        raw_runs=[_run(101)],
        identity_files=[_identity(tmp_path, 101, "04:05")],
        observed_at_utc=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
    )
    report = evidence["reconciliation"]
    assert evidence["provenance"]["timestamp_slot_inference_allowed"] is False
    assert report["metrics"]["attributed_run_count"] == 1
    assert report["metrics"]["unattributed_run_count"] == 0


def test_missing_identity_remains_unattributed(tmp_path):
    evidence = build_session_evidence(
        session_date=date(2026, 9, 21),
        raw_runs=[_run(102)],
        identity_files=[],
        observed_at_utc=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
    )
    report = evidence["reconciliation"]
    assert report["metrics"]["attributed_run_count"] == 0
    assert report["metrics"]["unattributed_run_count"] == 1


def test_conflicting_identity_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="conflicting inline/artifact slot identity"):
        build_session_evidence(
            session_date=date(2026, 9, 21),
            raw_runs=[_run(103, slot="04:35")],
            identity_files=[_identity(tmp_path, 103, "04:05")],
            observed_at_utc=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        )
