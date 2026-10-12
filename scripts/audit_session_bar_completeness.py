from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
REPORT_CONTRACT = "orion-session-bar-completeness-v1"
PREMARKET_START = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EXPECTED_PREMARKET_MINUTES = 330
EXPECTED_REGULAR_MINUTES = 390


class SessionCompletenessError(ValueError):
    pass


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SessionCompletenessError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise SessionCompletenessError(f"timestamp must be timezone-aware: {value}")
    return parsed


def _minute_range(day: date, start: time, end: time) -> list[datetime]:
    cursor = datetime.combine(day, start, tzinfo=NY)
    stop = datetime.combine(day, end, tzinfo=NY)
    result: list[datetime] = []
    while cursor < stop:
        result.append(cursor)
        cursor += timedelta(minutes=1)
    return result


def _compress_missing(minutes: Iterable[datetime]) -> list[dict[str, str | int]]:
    ordered = sorted(set(minutes))
    if not ordered:
        return []
    ranges: list[dict[str, str | int]] = []
    start = previous = ordered[0]
    for current in ordered[1:]:
        if current - previous != timedelta(minutes=1):
            ranges.append({
                "start_et": start.isoformat(),
                "end_et": previous.isoformat(),
                "minute_count": int((previous - start).total_seconds() // 60) + 1,
            })
            start = current
        previous = current
    ranges.append({
        "start_et": start.isoformat(),
        "end_et": previous.isoformat(),
        "minute_count": int((previous - start).total_seconds() // 60) + 1,
    })
    return ranges


def _window_projection(
    observed: set[datetime],
    *,
    day: date,
    start: time,
    end: time,
) -> dict:
    expected = _minute_range(day, start, end)
    expected_set = set(expected)
    observed_in_window = observed & expected_set
    missing = expected_set - observed_in_window
    return {
        "expected_minute_count": len(expected),
        "observed_minute_count": len(observed_in_window),
        "missing_minute_count": len(missing),
        "coverage_fraction": round(len(observed_in_window) / len(expected), 6) if expected else None,
        "strict_grid_complete": not missing,
        "missing_minute_ranges": _compress_missing(missing),
    }


def build_report(rows: Iterable[dict[str, str]]) -> dict:
    minutes_by_symbol_day: dict[tuple[str, date], set[datetime]] = defaultdict(set)
    duplicate_count = 0
    out_of_session_count = 0
    malformed_count = 0
    seen: set[tuple[str, datetime]] = set()

    for row in rows:
        symbol = str(row.get("ticker") or "").strip().upper()
        stamp = str(row.get("timestamp") or "").strip()
        if not symbol or not stamp:
            malformed_count += 1
            continue
        parsed = _parse_timestamp(stamp).astimezone(NY).replace(second=0, microsecond=0)
        key = (symbol, parsed)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)

        clock = parsed.time().replace(tzinfo=None)
        if not (PREMARKET_START <= clock < REGULAR_CLOSE):
            out_of_session_count += 1
            continue
        minutes_by_symbol_day[(symbol, parsed.date())].add(parsed)

    projections: list[dict] = []
    for (symbol, day), observed in sorted(minutes_by_symbol_day.items(), key=lambda item: (item[0][1], item[0][0])):
        premarket = _window_projection(
            observed,
            day=day,
            start=PREMARKET_START,
            end=REGULAR_OPEN,
        )
        regular = _window_projection(
            observed,
            day=day,
            start=REGULAR_OPEN,
            end=REGULAR_CLOSE,
        )
        projections.append({
            "symbol": symbol,
            "session_date": day.isoformat(),
            "premarket": premarket,
            "regular_hours": regular,
            "strict_session_complete": bool(
                premarket["strict_grid_complete"] and regular["strict_grid_complete"]
            ),
        })

    expected_premarket = sum(row["premarket"]["expected_minute_count"] for row in projections)
    observed_premarket = sum(row["premarket"]["observed_minute_count"] for row in projections)
    expected_regular = sum(row["regular_hours"]["expected_minute_count"] for row in projections)
    observed_regular = sum(row["regular_hours"]["observed_minute_count"] for row in projections)

    return {
        "contract": REPORT_CONTRACT,
        "timezone": "America/New_York",
        "invariant_semantics": (
            "Strict 1-minute grid coverage. A missing minute is reported as an observation gap; "
            "this audit does not infer whether the cause is provider delivery or a genuine no-trade minute."
        ),
        "expected_minutes_per_symbol_session": {
            "premarket": EXPECTED_PREMARKET_MINUTES,
            "regular_hours": EXPECTED_REGULAR_MINUTES,
            "total": EXPECTED_PREMARKET_MINUTES + EXPECTED_REGULAR_MINUTES,
        },
        "symbol_session_count": len(projections),
        "strict_complete_symbol_session_count": sum(1 for row in projections if row["strict_session_complete"]),
        "duplicate_ticker_minute_count": duplicate_count,
        "out_of_session_row_count": out_of_session_count,
        "malformed_row_count": malformed_count,
        "coverage": {
            "premarket": {
                "expected_minute_count": expected_premarket,
                "observed_minute_count": observed_premarket,
                "missing_minute_count": expected_premarket - observed_premarket,
                "coverage_fraction": round(observed_premarket / expected_premarket, 6) if expected_premarket else None,
            },
            "regular_hours": {
                "expected_minute_count": expected_regular,
                "observed_minute_count": observed_regular,
                "missing_minute_count": expected_regular - observed_regular,
                "coverage_fraction": round(observed_regular / expected_regular, 6) if expected_regular else None,
            },
        },
        "symbol_sessions": projections,
    }


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit strict premarket and regular-hours 1-minute raw-bar coverage."
    )
    parser.add_argument("--input", type=Path, required=True, help="CSV with ticker,timestamp columns")
    parser.add_argument("--output", type=Path, required=True, help="JSON health report")
    args = parser.parse_args()

    try:
        report = build_report(_load_rows(args.input))
    except (OSError, SessionCompletenessError, ValueError) as exc:
        print(json.dumps({"status": "invalid_session_completeness_input", "error": str(exc)}, sort_keys=True))
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "completed",
        "symbol_session_count": report["symbol_session_count"],
        "strict_complete_symbol_session_count": report["strict_complete_symbol_session_count"],
        "premarket_coverage_fraction": report["coverage"]["premarket"]["coverage_fraction"],
        "regular_hours_coverage_fraction": report["coverage"]["regular_hours"]["coverage_fraction"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
