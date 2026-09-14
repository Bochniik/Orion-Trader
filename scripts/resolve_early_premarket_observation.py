from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")
OBSERVATION_SLOTS = ((4, 5), (4, 35), (5, 5), (5, 35), (6, 5), (6, 35))
MAX_SCHEDULE_LAG_MINUTES = 20.0


@dataclass(frozen=True)
class ObservationTarget:
    active: bool
    reason: str
    session_date: str
    slot: str
    target_et: str
    target_utc: str
    lag_minutes: float | None


def resolve_observation_target(now_utc: datetime) -> ObservationTarget:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")

    now_utc = now_utc.astimezone(timezone.utc)
    local = now_utc.astimezone(NY)
    session_date = local.date().isoformat()

    if local.weekday() >= 5:
        return ObservationTarget(False, "weekend", session_date, "", "", "", None)

    targets = [
        datetime.combine(local.date(), time(hour, minute), tzinfo=NY)
        for hour, minute in OBSERVATION_SLOTS
    ]
    eligible = [target for target in targets if target <= local]
    if not eligible:
        return ObservationTarget(False, "before_observation_window", session_date, "", "", "", None)

    target = max(eligible)
    lag_minutes = (now_utc - target.astimezone(timezone.utc)).total_seconds() / 60.0
    slot = target.strftime("%H%M")
    target_et = target.isoformat()
    target_utc = target.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    if lag_minutes > MAX_SCHEDULE_LAG_MINUTES:
        return ObservationTarget(
            False,
            "outside_schedule_lag_window",
            session_date,
            slot,
            target_et,
            target_utc,
            round(lag_minutes, 6),
        )

    return ObservationTarget(
        True,
        "scheduled_observation_window",
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


def _write_github_output(path: Path, target: ObservationTarget) -> None:
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
    parser = argparse.ArgumentParser(
        description="Resolve a DST-safe early-premarket observational collection slot."
    )
    parser.add_argument("--now", default=None, help="Optional timezone-aware ISO-8601 instant for testing")
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    target = resolve_observation_target(_parse_now(args.now))
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
