from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    path = ROOT / "scripts/summarize_long_horizon_v5_run_recovery_health.py"
    spec = importlib.util.spec_from_file_location("long_horizon_run_recovery_health", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


health = _load_module()
CUTOFF = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _run(run_id: int, *, event="schedule", status="completed", conclusion="success", created_at="2026-09-10T14:05:00Z"):
    return {
        "id": run_id,
        "event": event,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "created_at": created_at,
        "head_sha": "deadbeef",
    }


def test_summary_exposes_whole_scheduled_run_artifact_loss():
    result = health.summarize_run_recovery(
        [
            _run(101),
            _run(102, conclusion="failure", created_at="2026-09-10T15:05:00Z"),
            _run(103, conclusion="cancelled", created_at="2026-09-10T16:05:00Z"),
        ],
        [101],
        cutoff=CUTOFF,
    )

    assert result["contract"] == "orion-long-horizon-v5-run-recovery-health-v1"
    assert result["score_blind"] is True
    assert result["population"] == "completed_scheduled_shadow_runs"
    assert result["completed_scheduled_run_count"] == 3
    assert result["recovered_prediction_artifact_run_count"] == 1
    assert result["missing_prediction_artifact_run_count"] == 2
    assert result["recovery_rate"] == pytest.approx(1 / 3)
    assert result["missing_run_conclusion_counts"] == {"cancelled": 1, "failure": 1}
    assert [entry["run_id"] for entry in result["missing_runs"]] == [102, 103]
    assert "deadbeef" not in str(result)


def test_manual_and_in_progress_runs_do_not_pollute_completed_population():
    result = health.summarize_run_recovery(
        [
            _run(201),
            _run(202, event="workflow_dispatch"),
            _run(203, status="in_progress"),
        ],
        [201],
        cutoff=CUTOFF,
    )

    assert result["completed_scheduled_run_count"] == 1
    assert result["pending_scheduled_run_count"] == 1
    assert result["ignored_non_schedule_run_count"] == 1
    assert result["recovery_rate"] == 1.0
    assert result["missing_runs"] == []


def test_cutoff_prevents_boundary_runs_from_becoming_false_missing():
    result = health.summarize_run_recovery(
        [
            _run(301, created_at="2026-08-31T23:59:59Z"),
            _run(302, created_at="2026-09-01T00:00:00Z"),
        ],
        [301, 302],
        cutoff=CUTOFF,
    )

    assert result["ignored_before_cutoff_run_count"] == 1
    assert result["completed_scheduled_run_count"] == 1
    assert result["recovered_prediction_artifact_run_count"] == 1
    assert result["recovered_outside_population_count"] == 1


def test_no_completed_runs_reports_null_recovery_rate():
    result = health.summarize_run_recovery(
        [_run(401, status="queued")],
        [],
        cutoff=CUTOFF,
    )
    assert result["completed_scheduled_run_count"] == 0
    assert result["recovery_rate"] is None


def test_duplicate_run_or_recovered_ids_fail_closed():
    with pytest.raises(ValueError, match="duplicate workflow run id"):
        health.summarize_run_recovery([_run(501), _run(501)], [], cutoff=CUTOFF)

    with pytest.raises(ValueError, match="duplicate recovered run id"):
        health.summarize_run_recovery([_run(502)], [502, 502], cutoff=CUTOFF)


def test_malformed_completed_run_fails_closed():
    bad = _run(601)
    bad["conclusion"] = None
    with pytest.raises(ValueError, match="must have a conclusion"):
        health.summarize_run_recovery([bad], [], cutoff=CUTOFF)


def test_non_score_fields_are_not_projected():
    run = _run(701)
    run["probability_up"] = 0.999999
    run["display_title"] = "secret model score"
    result = health.summarize_run_recovery([run], [701], cutoff=CUTOFF)
    rendered = str(result)
    assert "0.999999" not in rendered
    assert "secret model score" not in rendered
