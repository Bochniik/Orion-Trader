from __future__ import annotations

from datetime import date
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "guard_premarket_v5_recovery.py"
spec = importlib.util.spec_from_file_location("premarket_v5_recovery_guard", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)

SESSION = date(2026, 9, 14)


def run(run_id: int, *, conclusion: str = "success", created_at: str = "2026-09-14T10:46:00Z", path: str | None = None):
    return {
        "id": run_id,
        "event": "schedule",
        "path": path or module.WORKFLOW_PATH,
        "head_branch": "main",
        "status": "completed",
        "conclusion": conclusion,
        "created_at": created_at,
    }


def artifact(name: str, *, expired: bool = False):
    return {"name": name, "expired": expired}


def test_recovery_is_allowed_when_no_successful_evidence_exists():
    decision = module.decide_recovery(
        runs=[run(10, conclusion="failure")],
        artifacts_by_run={10: [artifact("premarket-v5-shadow-early-10")]},
        session=SESSION,
        snapshot="early",
        current_run_id=20,
    )
    assert decision.collect_allowed is True
    assert decision.reason == "no_successful_evidence"


def test_successful_same_session_same_snapshot_artifact_blocks_recovery():
    decision = module.decide_recovery(
        runs=[run(10)],
        artifacts_by_run={10: [artifact("premarket-v5-shadow-early-10")]},
        session=SESSION,
        snapshot="early",
        current_run_id=20,
    )
    assert decision.collect_allowed is False
    assert decision.reason == "existing_successful_evidence"
    assert decision.blocking_run_id == 10


def test_other_snapshot_does_not_block_recovery():
    decision = module.decide_recovery(
        runs=[run(10)],
        artifacts_by_run={10: [artifact("premarket-v5-shadow-mid-10")]},
        session=SESSION,
        snapshot="early",
        current_run_id=20,
    )
    assert decision.collect_allowed is True


def test_previous_session_does_not_block_recovery():
    decision = module.decide_recovery(
        runs=[run(10, created_at="2026-09-11T10:46:00Z")],
        artifacts_by_run={10: [artifact("premarket-v5-shadow-early-10")]},
        session=SESSION,
        snapshot="early",
        current_run_id=20,
    )
    assert decision.collect_allowed is True


def test_expired_artifact_does_not_block_recovery():
    decision = module.decide_recovery(
        runs=[run(10)],
        artifacts_by_run={10: [artifact("premarket-v5-shadow-early-10", expired=True)]},
        session=SESSION,
        snapshot="early",
        current_run_id=20,
    )
    assert decision.collect_allowed is True


def test_current_run_is_never_used_as_its_own_claim():
    decision = module.decide_recovery(
        runs=[run(20)],
        artifacts_by_run={20: [artifact("premarket-v5-shadow-early-20")]},
        session=SESSION,
        snapshot="early",
        current_run_id=20,
    )
    assert decision.collect_allowed is True


def test_non_main_or_wrong_workflow_run_does_not_block():
    wrong_path = run(10, path=".github/workflows/other.yml")
    branch_run = run(11)
    branch_run["head_branch"] = "research/test"
    decision = module.decide_recovery(
        runs=[wrong_path, branch_run],
        artifacts_by_run={
            10: [artifact("premarket-v5-shadow-early-10")],
            11: [artifact("premarket-v5-shadow-early-11")],
        },
        session=SESSION,
        snapshot="early",
        current_run_id=20,
    )
    assert decision.collect_allowed is True


def test_malformed_run_id_fails_closed():
    malformed = run(10)
    malformed["id"] = "not-an-int"
    try:
        module.decide_recovery(
            runs=[malformed],
            artifacts_by_run={},
            session=SESSION,
            snapshot="early",
            current_run_id=20,
        )
    except module.GuardError:
        pass
    else:
        raise AssertionError("malformed GitHub run metadata must fail closed")
