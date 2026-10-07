from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")
REGULAR_COLLECTION_SLOTS = tuple((hour, 35) for hour in range(9, 16))
# GitHub scheduled runs have recently arrived 20-25 minutes after their nominal
# trigger. Keep a small transport grace so those runs can still create genuinely
# forward observations instead of being discarded. The prediction/evidence
# timestamp remains the actual collection time; this never backdates evidence to
# the nominal :35 slot.
MAX_SCHEDULE_LAG_MINUTES = 30.0


@dataclass(frozen=True)
class RegularCollectionTarget:
    active: bool
    reason: str
    session_date: str
    slot: str
    target_et: str
    target_utc: str
    lag_minutes: float | None


def resolve_regular_collection_target(now_utc: datetime) -> RegularCollectionTarget:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")

    now_utc = now_utc.astimezone(timezone.utc)
    local = now_utc.astimezone(NY)
    session_date = local.date().isoformat()

    if local.weekday() >= 5:
        return RegularCollectionTarget(False, "weekend", session_date, "", "", "", None)

    targets = [
        datetime.combine(local.date(), time(hour, minute), tzinfo=NY)
        for hour, minute in REGULAR_COLLECTION_SLOTS
    ]
    eligible = [target for target in targets if target <= local]
    if not eligible:
        return RegularCollectionTarget(False, "before_regular_collection_window", session_date, "", "", "", None)

    target = max(eligible)
    lag_minutes = (now_utc - target.astimezone(timezone.utc)).total_seconds() / 60.0
    slot = target.strftime("%H%M")
    target_et = target.isoformat()
    target_utc = target.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    if lag_minutes > MAX_SCHEDULE_LAG_MINUTES:
        return RegularCollectionTarget(
            False,
            "outside_schedule_lag_window",
            session_date,
            slot,
            target_et,
            target_utc,
            round(lag_minutes, 6),
        )

    return RegularCollectionTarget(
        True,
        "scheduled_regular_collection_window",
        session_date,
        slot,
        target_et,
        target_utc,
        round(lag_minutes, 6),
    )


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _write_github_output(path: Path, target: RegularCollectionTarget) -> None:
    values = {
        "active": "true" if target.active else "false",
        "reason": target.reason,
        "session_date": target.session_date,
        "slot": target.slot,
        "target_et": target.target_et,
        "target_utc": target.target_utc,
        "lag_minutes": "" if target.lag_minutes is None else str(target.lag_minutes),
    }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve a retry-safe regular-hours collection slot.")
    parser.add_argument("--now", default=None, help="Optional timezone-aware ISO-8601 instant for testing")
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    target = resolve_regular_collection_target(_parse_now(args.now))
    if args.github_output is not None:
        _write_github_output(args.github_output, target)

    print(
        f"active={str(target.active).lower()} reason={target.reason} "
        f"session_date={target.session_date} slot={target.slot or '-'} "
        f"target_utc={target.target_utc or '-'} lag_minutes={target.lag_minutes}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
