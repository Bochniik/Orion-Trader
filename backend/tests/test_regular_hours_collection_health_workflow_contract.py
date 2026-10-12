from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "regular-hours-collection-health.yml"
)


def test_collection_health_runs_importing_audits_as_modules() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m scripts.audit_regular_hours_forward_completeness" in workflow
    assert "python -m scripts.audit_regular_hours_session_cadence" in workflow
    assert "python scripts/audit_regular_hours_forward_completeness.py" not in workflow
    assert "python scripts/audit_regular_hours_session_cadence.py" not in workflow
