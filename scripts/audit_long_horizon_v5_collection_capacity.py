from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ")
SCHEDULED_UTC_HOURS = (14, 15, 16, 17, 18, 19)
RUN_MINUTE = 5
SESSION_OPEN = time(10, 0)
SESSION_CLOSE = time(13, 30)
REGULAR_CLOSE = time(16, 0)
HORIZON_HOURS = {"3h": 3, "5h": 5}
MIN_OBSERVATIONS = 80
MIN_SESSIONS = 8
CONTRACT = "orion-long-horizon-v5-collection-capacity-v1"


@dataclass(frozen=True)
class EligibleRun:
    horizon: str
    utc_time: str
    et_time: str


def _local_clock(dt: datetime) -> time:
    return dt.astimezone(NY).time().replace(tzinfo=None)


def eligible_runs_for_session(session_date: str) -> list[EligibleRun]:
    day = datetime.fromisoformat(session_date).date()
    eligible: list[EligibleRun] = []
    for utc_hour in SCHEDULED_UTC_HOURS:
        run = datetime(day.year, day.month, day.day, utc_hour, RUN_MINUTE, tzinfo=ZoneInfo("UTC"))
        local = run.astimezone(NY)
        clock = local.time().replace(tzinfo=None)
        if local.date() != day or local.weekday() >= 5:
            continue
        if not (SESSION_OPEN <= clock <= SESSION_CLOSE):
            continue
        for horizon, hours in HORIZON_HOURS.items():
            target = local + timedelta(hours=hours)
            if target.date() != local.date() or target.time().replace(tzinfo=None) > REGULAR_CLOSE:
                continue
            eligible.append(
                EligibleRun(
                    horizon=horizon,
                    utc_time=run.isoformat(),
                    et_time=local.isoformat(),
                )
            )
    return eligible


def build_report(session_date: str, symbol_count: int) -> dict[str, Any]:
    if symbol_count <= 0:
        raise ValueError("symbol_count must be positive")
    runs = eligible_runs_for_session(session_date)
    by_horizon: dict[str, Any] = {}
    for horizon in HORIZON_HOURS:
        horizon_runs = [row for row in runs if row.horizon == horizon]
        snapshots = len(horizon_runs)
        observations_per_session = snapshots * symbol_count
        sessions_for_observations = (
            (MIN_OBSERVATIONS + observations_per_session - 1) // observations_per_session
            if observations_per_session
            else None
        )
        earliest_decision_sessions = (
            max(MIN_SESSIONS, sessions_for_observations)
            if sessions_for_observations is not None
            else None
        )
        eight_session_capacity = observations_per_session * MIN_SESSIONS
        by_horizon[horizon] = {
            "eligible_snapshots_per_session": snapshots,
            "observations_per_session_at_full_symbol_coverage": observations_per_session,
            "minimum_observations": MIN_OBSERVATIONS,
            "minimum_sessions": MIN_SESSIONS,
            "minimum_sessions_needed_for_observation_count": sessions_for_observations,
            "earliest_possible_decision_session_count": earliest_decision_sessions,
            "capacity_after_minimum_sessions": eight_session_capacity,
            "capacity_margin_after_minimum_sessions": eight_session_capacity - MIN_OBSERVATIONS,
            "zero_margin_at_minimum_sessions": eight_session_capacity == MIN_OBSERVATIONS,
            "eligible_runs": [asdict(row) for row in horizon_runs],
        }
    return {
        "contract": CONTRACT,
        "research_only": True,
        "score_blind": True,
        "session_date": session_date,
        "symbol_count": symbol_count,
        "scheduled_utc_hours": list(SCHEDULED_UTC_HOURS),
        "run_minute": RUN_MINUTE,
        "horizons": by_horizon,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit score-blind collection capacity for frozen long-horizon V5 forward evidence.")
    parser.add_argument("--session-date", required=True, help="Representative YYYY-MM-DD trading session date")
    parser.add_argument("--symbol-count", type=int, default=len(DEFAULT_SYMBOLS))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = build_report(args.session_date, args.symbol_count)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
