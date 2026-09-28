from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.nyse_session_calendar import is_nyse_trading_day

NY = ZoneInfo("America/New_York")
RECOVERY_DELAY = timedelta(minutes=10)

# Frozen decision timestamps. They remain unchanged by recovery transport.
SNAPSHOT_CLOCKS: dict[str, time] = {
    "early": time(6, 45),
    "mid": time(8, 0),
    "late": time(9, 15),
}

# Compatibility and research contract: these are the original primary transport
# slots only. Delivery/evidence audits intentionally use this mapping to preserve
# the frozen expected cadence and keep recovery separate from primary delivery.
REGISTERED_CRON_SLOTS: dict[str, str] = {
    "45 10 * * 1-5": "early",
    "45 11 * * 1-5": "early",
    "0 12 * * 1-5": "mid",
    "0 13 * * 1-5": "mid",
    "15 13 * * 1-5": "late",
    "15 14 * * 1-5": "late",
}

# Fixed +10 minute score-blind recovery transport. A recovery run preserves the
# original decision timestamp and may emit evidence only when the idempotency guard
# proves no successful same-session/same-snapshot evidence artifact already exists.
RECOVERY_CRON_SLOTS: dict[str, str] = {
    "55 10 * * 1-5": "early",
    "55 11 * * 1-5": "early",
    "10 12 * * 1-5": "mid",
    "10 13 * * 1-5": "mid",
    "25 13 * * 1-5": "late",
    "25 14 * * 1-5": "late",
}


@dataclass(frozen=True)
class SnapshotResolution:
    active: bool
    reason: str
    snapshot: str
    mode: str
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


def resolve_snapshot(*, schedule_cron: str | None, now: datetime | None = None, manual_current: bool = False) -> SnapshotResolution:
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if manual_current and schedule_cron:
        raise ValueError('manual_current is incompatible with a scheduled cron slot')

    if schedule_cron:
        if schedule_cron in REGISTERED_CRON_SLOTS:
            snapshot = REGISTERED_CRON_SLOTS[schedule_cron]
            mode = "primary"
        elif schedule_cron in RECOVERY_CRON_SLOTS:
            snapshot = RECOVERY_CRON_SLOTS[schedule_cron]
            mode = "recovery"
        else:
            raise ValueError(f"Unregistered Premarket V5 schedule: {schedule_cron}")
    else:
        # workflow_dispatch preserves the historical 09:15 ET behavior and never
        # masquerades as the scheduled recovery path.
        snapshot, mode = ("current", "manual_current") if manual_current else ("late", "manual")

    if manual_current:
        # Capture the actual manual decision time, never a future registered slot.
        # This is research-only: workflow_dispatch is always promotion-ineligible.
        target_utc = reference.replace(second=0, microsecond=0)
        target_et = target_utc.astimezone(NY)
    else:
        target_utc, target_et = _target_for_local_day(snapshot, reference=reference)

    if target_et.weekday() >= 5:
        return SnapshotResolution(False, "weekend", snapshot, mode, target_utc, target_et)
    if not is_nyse_trading_day(target_et.date()):
        return SnapshotResolution(False, "market_holiday", snapshot, mode, target_utc, target_et)

    if schedule_cron:
        scheduled_target_utc = target_utc + (RECOVERY_DELAY if mode == "recovery" else timedelta(0))
        cron_hour, cron_minute = _cron_clock(schedule_cron)
        if (scheduled_target_utc.hour, scheduled_target_utc.minute) != (cron_hour, cron_minute):
            return SnapshotResolution(False, "inactive_dst_slot", snapshot, mode, target_utc, target_et)

    reason = "registered_recovery" if mode == "recovery" else "registered_snapshot"
    if mode == "manual":
        reason = "manual_dispatch"
    elif mode == "manual_current":
        reason = "manual_current_research_only"
    return SnapshotResolution(True, reason, snapshot, mode, target_utc, target_et)


def _write_github_output(path: Path, resolution: SnapshotResolution) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"active={'true' if resolution.active else 'false'}\n")
        handle.write(f"reason={resolution.reason}\n")
        handle.write(f"snapshot={resolution.snapshot}\n")
        handle.write(f"mode={resolution.mode}\n")
        handle.write(f"session={resolution.as_of_et.date().isoformat()}\n")
        handle.write(f"as_of={resolution.as_of_utc.isoformat()}\n")
        handle.write(f"as_of_et={resolution.as_of_et.isoformat()}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve the pre-registered Premarket V5 cloud-shadow snapshot for a GitHub schedule slot.")
    parser.add_argument("--schedule-cron", default=None, help="Exact github.event.schedule string; omit for workflow_dispatch")
    parser.add_argument("--now", default=None, help="Testing/debug ISO timestamp; default is current UTC")
    parser.add_argument("--manual-current", action="store_true", help="Manual research collection at the current minute, never forward eligible")
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    now = None
    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            raise ValueError("--now must include a timezone offset")

    resolution = resolve_snapshot(schedule_cron=args.schedule_cron or None, now=now, manual_current=args.manual_current)
    payload = {
        "active": resolution.active,
        "reason": resolution.reason,
        "snapshot": resolution.snapshot,
        "mode": resolution.mode,
        "session": resolution.as_of_et.date().isoformat(),
        "as_of_utc": resolution.as_of_utc.isoformat(),
        "as_of_et": resolution.as_of_et.isoformat(),
    }
    print(json.dumps(payload, sort_keys=True))
    if args.github_output is not None:
        _write_github_output(args.github_output, resolution)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
