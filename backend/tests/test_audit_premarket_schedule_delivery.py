from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audit_premarket_schedule_delivery import audit_schedule_delivery


def _run(run_id: int, created_at: str, conclusion: str = "success", event: str = "schedule") -> dict:
    return {"id": run_id, "created_at": created_at, "conclusion": conclusion, "event": event}


def test_audit_distinguishes_missing_from_failed_and_deduplicates_slots() -> None:
    report = audit_schedule_delivery(
        date(2026, 9, 22),
        [
            _run(1, "2026-09-22T08:05:30Z"),
            _run(2, "2026-09-22T08:06:00Z"),  # duplicate delivery for 04:05 ET
            _run(3, "2026-09-22T08:35:20Z", "failure"),
            _run(4, "2026-09-22T09:05:10Z"),
            _run(5, "2026-09-22T09:35:10Z"),
            _run(6, "2026-09-22T10:05:10Z"),
            # 06:35 ET / 10:35 UTC deliberately missing
            _run(99, "2026-09-22T10:35:00Z", event="workflow_dispatch"),
        ],
    )

    assert report["expected_slots"] == 6
    assert report["counts"] == {
        "run_created_success": 4,
        "run_created_collector_failed": 1,
        "run_missing": 1,
    }
    assert report["healthy"] is False
    assert report["promotion_authorized"] is False
    assert report["slots"][0]["duplicate_run_ids"] == (2,)
    assert report["slots"][1]["status"] == "run_created_collector_failed"
    assert report["slots"][-1]["status"] == "run_missing"


def test_audit_uses_est_targets_after_dst_transition() -> None:
    report = audit_schedule_delivery(
        date(2026, 11, 3),
        [_run(index, f"2026-11-03T{hour:02d}:{minute:02d}:10Z") for index, (hour, minute) in enumerate(((9, 5), (9, 35), (10, 5), (10, 35), (11, 5), (11, 35)), start=1)],
    )

    assert report["healthy"] is True
    assert report["counts"]["run_created_success"] == 6
    assert report["slots"][0]["target_utc"] == "2026-11-03T09:05:00Z"


def test_audit_has_no_expected_slots_on_nyse_holiday() -> None:
    report = audit_schedule_delivery(date(2026, 12, 25), [])

    assert report["trading_day"] is False
    assert report["expected_slots"] == 0
    assert report["healthy"] is True
