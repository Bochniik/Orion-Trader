from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.nyse_session_calendar import is_nyse_trading_day
from scripts.resolve_premarket_v5_snapshot import SNAPSHOT_CLOCKS

NY = ZoneInfo("America/New_York")
DEFAULT_MAX_LAG_MINUTES = 12


@dataclass(frozen=True)
class WatchdogResolution:
    active: bool
    reason: str
    snapshot: str
    as_of_utc: datetime | None
    as_of_et: datetime | None
    lag_minutes: float | None


def resolve_watchdog_snapshot(
    *,
    now: datetime | None = None,
    max_lag_minutes: int = DEFAULT_MAX_LAG_MINUTES,
) -> WatchdogResolution:
    if max_lag_minutes < 0:
        raise ValueError("max_lag_minutes must be non-negative")

    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_now = reference.astimezone(NY)
    session_day = local_now.date()

    if local_now.weekday() >= 5:
        return WatchdogResolution(False, "weekend", "", None, None, None)
    if not is_nyse_trading_day(session_day):
        return WatchdogResolution(False, "market_holiday", "", None, None, None)

    candidates: list[tuple[float, str, datetime, datetime]] = []
    for snapshot, clock in SNAPSHOT_CLOCKS.items():
        target_et = datetime.combine(session_day, clock, tzinfo=NY)
        target_utc = target_et.astimezone(timezone.utc)
        lag_minutes = (reference - target_utc).total_seconds() / 60.0
        if 0.0 <= lag_minutes <= float(max_lag_minutes):
            candidates.append((lag_minutes, snapshot, target_utc, target_et))

    if not candidates:
        return WatchdogResolution(False, "outside_snapshot_window", "", None, None, None)

    lag_minutes, snapshot, target_utc, target_et = min(candidates, key=lambda item: item[0])
    return WatchdogResolution(
        True,
        "watchdog_recovery_window",
        snapshot,
        target_utc,
        target_et,
        lag_minutes,
    )


def _write_output(path: Path, resolution: WatchdogResolution, *, triggered_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"active={'true' if resolution.active else 'false'}\n")
        handle.write(f"reason={resolution.reason}\n")
        handle.write(f"snapshot={resolution.snapshot}\n")
        handle.write(f"as_of={resolution.as_of_utc.isoformat() if resolution.as_of_utc else ''}\n")
        handle.write(f"as_of_et={resolution.as_of_et.isoformat() if resolution.as_of_et else ''}\n")
        handle.write(f"lag_minutes={resolution.lag_minutes if resolution.lag_minutes is not None else ''}\n")
        handle.write(f"triggered_at_utc={triggered_at.astimezone(timezone.utc).isoformat()}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve redundant Premarket V5 watchdog delivery windows.")
    parser.add_argument("--now", default=None, help="ISO timestamp for tests/debug; defaults to current UTC")
    parser.add_argument("--max-lag-minutes", type=int, default=DEFAULT_MAX_LAG_MINUTES)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            raise ValueError("--now must include a timezone offset")
        now = now.astimezone(timezone.utc)

    resolution = resolve_watchdog_snapshot(now=now, max_lag_minutes=args.max_lag_minutes)
    print(
        {
            "active": resolution.active,
            "reason": resolution.reason,
            "snapshot": resolution.snapshot,
            "as_of_utc": resolution.as_of_utc.isoformat() if resolution.as_of_utc else None,
            "as_of_et": resolution.as_of_et.isoformat() if resolution.as_of_et else None,
            "lag_minutes": resolution.lag_minutes,
        }
    )
    if args.github_output is not None:
        _write_output(args.github_output, resolution, triggered_at=now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
