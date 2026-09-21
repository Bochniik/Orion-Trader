from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OBSERVATION_SLOTS = ((4, 5), (4, 35), (5, 5), (5, 35), (6, 5), (6, 35))
CONTRACT = "orion-early-premarket-acquisition-health-v1"


@dataclass(frozen=True)
class RunEvidence:
    run_id: str
    created_at_utc: datetime
    conclusion: str | None
    target_slot_et: str | None = None


def slot_identity(session_date: date, hour: int, minute: int) -> str:
    return f"{session_date.isoformat()}-{hour:02d}{minute:02d}-America_New_York"


def expected_slots(session_date: date) -> list[dict[str, str]]:
    return [
        {
            "slot_id": slot_identity(session_date, hour, minute),
            "target_et": datetime.combine(session_date, time(hour, minute), tzinfo=NY).isoformat(),
            "target_utc": datetime.combine(session_date, time(hour, minute), tzinfo=NY)
            .astimezone(timezone.utc)
            .isoformat(),
        }
        for hour, minute in OBSERVATION_SLOTS
    ]


def build_health_report(
    *,
    session_date: date,
    runs: Iterable[RunEvidence],
    observed_at_utc: datetime,
    grace_minutes: int = 20,
) -> dict[str, Any]:
    if observed_at_utc.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    observed = observed_at_utc.astimezone(timezone.utc)
    by_slot: dict[str, list[RunEvidence]] = {}
    unattributed: list[str] = []
    for run in runs:
        if run.created_at_utc.tzinfo is None:
            raise ValueError("run created_at_utc must be timezone-aware")
        if run.target_slot_et:
            by_slot.setdefault(run.target_slot_et, []).append(run)
        else:
            unattributed.append(run.run_id)

    slots: list[dict[str, Any]] = []
    for spec in expected_slots(session_date):
        target = datetime.fromisoformat(spec["target_utc"])
        if observed < target + timedelta(minutes=grace_minutes):
            status = "pending"
            matched: list[RunEvidence] = []
        else:
            matched = by_slot.get(spec["target_et"], [])
            if not matched:
                status = "workflow_never_created"
            elif any(run.conclusion == "success" for run in matched):
                status = "collector_succeeded"
            else:
                status = "workflow_created_collector_failed"
        slots.append(
            {
                **spec,
                "status": status,
                "run_ids": sorted(run.run_id for run in matched),
                "duplicate_run_count": max(0, len(matched) - 1),
                "forward_backfill_allowed": False,
            }
        )

    return {
        "contract": CONTRACT,
        "session_date": session_date.isoformat(),
        "observed_at_utc": observed.isoformat(),
        "grace_minutes": grace_minutes,
        "slots": slots,
        "unattributed_run_ids": sorted(unattributed),
        "provenance_policy": "missed point-in-time slots must never be backfilled as contemporaneous evidence",
    }
