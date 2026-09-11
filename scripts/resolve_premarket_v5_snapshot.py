from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

# Pre-registered forward collection cadence. These clocks are intentionally fixed
# before collecting their outcomes and must not be moved in response to model scores.
SNAPSHOT_CLOCKS: dict[str, time] = {
    "early": time(6, 45),
    "mid": time(8, 0),
    "late": time(9, 15),
}

# GitHub Actions schedules are UTC. Both EDT and EST slots are declared so the
# workflow remains DST-safe; this resolver makes exactly one slot active per
# snapshot/session and fails closed for the inactive duplicate.
REGISTERED_CRON_SLOTS: dict[str, str] = {
    "45 10 * * 1-5": "early",
    "45 11 * * 1-5": "early",
    "0 12 * * 1-5": "mid",
    "0 13 * * 1-5": "mid",
    "15 13 * * 1-5": "late",
    "15 14 * * 1-5": "late",
}


@dataclass(frozen=True)
class SnapshotResolution:
    active: bool
    reason: str
    snapshot: str
    as_of_utc: datetime
    as_of_et: datetime


def _target_for_local_day(snapshot: str, *, reference: datetime) -> tuple[datetime, datetime]:
    if snapshot not in SNAPSHOT_CLOCKS:
        raise ValueError(f"Unknown snapshot: {snapshot}")
    local_reference = reference.astimezone(NY)
    local_target = datetime.combine(local_reference.date(), SNAPSHOT_CLOCKS[snapshot], tzinfo=NY)
    return local_target.astimezone(timezone.utc), local_target


def _cron_clock(schedule_cron: str) -> tuple[int, int]:
    fields = schedule_cron.split()
    if len(fields) != 5:
        raise ValueError("schedule cron must contain five fields")
    try:
        minute = int(fields[0])
        hour = int(fields[1])
    except ValueError as exc:
        raise ValueError("schedule cron minute/hour must be integers") from exc
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        raise ValueError("schedule cron minute/hour out of range")
    return hour, minute


def resolve_snapshot(*, schedule_cron: str | None, now: datetime | None = None) -> SnapshotResolution:
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if schedule_cron:
        snapshot = REGISTERED_CRON_SLOTS.get(schedule_cron)
        if snapshot is None:
            raise ValueError(f"Unregistered Premarket V5 schedule: {schedule_cron}")
    else:
        # workflow_dispatch preserves the historical 09:15 ET behavior.
        snapshot = "late"

    target_utc, target_et = _target_for_local_day(snapshot, reference=reference)

    if target_et.weekday() >= 5:
        return SnapshotResolution(False, "weekend", snapshot, target_utc, target_et)

    if schedule_cron:
        cron_hour, cron_minute = _cron_clock(schedule_cron)
        if (target_utc.hour, target_utc.minute) != (cron_hour, cron_minute):
            return SnapshotResolution(False, "inactive_dst_slot", snapshot, target_utc, target_et)

    return SnapshotResolution(True, "registered_snapshot", snapshot, target_utc, target_et)


def _write_github_output(path: Path, resolution: SnapshotResolution) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"active={'true' if resolution.active else 'false'}\n")
        handle.write(f"reason={resolution.reason}\n")
        handle.write(f"snapshot={resolution.snapshot}\n")
        handle.write(f"as_of={resolution.as_of_utc.isoformat()}\n")
        handle.write(f"as_of_et={resolution.as_of_et.isoformat()}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve the pre-registered Premarket V5 cloud-shadow snapshot for a GitHub schedule slot.")
    parser.add_argument("--schedule-cron", default=None, help="Exact github.event.schedule string; omit for workflow_dispatch")
    parser.add_argument("--now", default=None, help="Testing/debug ISO timestamp; default is current UTC")
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    now = None
    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            raise ValueError("--now must include a timezone offset")

    resolution = resolve_snapshot(schedule_cron=args.schedule_cron or None, now=now)
    payload = {
        "active": resolution.active,
        "reason": resolution.reason,
        "snapshot": resolution.snapshot,
        "as_of_utc": resolution.as_of_utc.isoformat(),
        "as_of_et": resolution.as_of_et.isoformat(),
    }
    print(json.dumps(payload, sort_keys=True))
    if args.github_output is not None:
        _write_github_output(args.github_output, resolution)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
