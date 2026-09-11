from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "premarket-v5-cloud-shadow.yml"

MIN_VALIDATION_SESSIONS = 40 + 10 + 5
# Eleven full weeks contain exactly 55 weekdays. The workflow keeps additional
# calendar slack for US market holidays and occasional failed/missed runs.
MIN_GEOMETRY_DAYS = 11 * 7
REQUIRED_RETENTION_DAYS = 90


def _retention_days() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^\s*retention-days:\s*(\d+)\s*$", text, re.MULTILINE)
    assert match, "Premarket V5 evidence upload must declare explicit retention-days"
    return int(match.group(1))


def test_forward_evidence_survives_minimum_validation_geometry():
    assert MIN_VALIDATION_SESSIONS == 55
    assert MIN_GEOMETRY_DAYS == 77

    retention_days = _retention_days()
    assert retention_days >= MIN_GEOMETRY_DAYS
    assert retention_days == REQUIRED_RETENTION_DAYS


def test_workflow_documents_why_retention_cannot_regress_to_short_window():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "40 train + 10 calibration + 5 test" in text
    assert "holiday/missing-run slack" in text
