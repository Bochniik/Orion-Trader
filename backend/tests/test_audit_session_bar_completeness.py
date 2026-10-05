from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_session_bar_completeness.py"
spec = importlib.util.spec_from_file_location("audit_session_bar_completeness", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def _row(symbol: str, timestamp: datetime) -> dict[str, str]:
    return {"ticker": symbol, "timestamp": timestamp.isoformat()}


def _full_session_rows(symbol: str = "AAPL") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    cursor = datetime(2026, 10, 2, 4, 0, tzinfo=module.NY)
    stop = datetime(2026, 10, 2, 16, 0, tzinfo=module.NY)
    while cursor < stop:
        rows.append(_row(symbol, cursor))
        cursor += timedelta(minutes=1)
    return rows


def test_full_session_reports_exact_expected_minute_invariants():
    report = module.build_report(_full_session_rows())
    assert report["symbol_session_count"] == 1
    assert report["strict_complete_symbol_session_count"] == 1
    assert report["expected_minutes_per_symbol_session"] == {"premarket": 330, "regular_hours": 390, "total": 720}
    assert report["coverage"]["premarket"]["observed_minute_count"] == 330
    assert report["coverage"]["regular_hours"]["observed_minute_count"] == 390
    assert report["coverage"]["premarket"]["coverage_fraction"] == 1.0
    assert report["coverage"]["regular_hours"]["coverage_fraction"] == 1.0


def test_missing_minutes_are_compressed_into_diagnostic_ranges():
    rows = _full_session_rows()
    missing = {
        datetime(2026, 10, 2, 8, 0, tzinfo=module.NY),
        datetime(2026, 10, 2, 8, 1, tzinfo=module.NY),
        datetime(2026, 10, 2, 10, 15, tzinfo=module.NY),
    }
    rows = [row for row in rows if datetime.fromisoformat(row["timestamp"]) not in missing]
    report = module.build_report(rows)
    projection = report["symbol_sessions"][0]
    assert projection["strict_session_complete"] is False
    assert projection["premarket"]["missing_minute_count"] == 2
    assert projection["premarket"]["missing_minute_ranges"] == [{
        "start_et": "2026-10-02T08:00:00-04:00",
        "end_et": "2026-10-02T08:01:00-04:00",
        "minute_count": 2,
    }]
    assert projection["regular_hours"]["missing_minute_count"] == 1
    assert projection["regular_hours"]["missing_minute_ranges"][0]["minute_count"] == 1


def test_duplicate_and_out_of_session_rows_are_explicitly_counted():
    stamp = datetime(2026, 10, 2, 9, 30, tzinfo=module.NY)
    rows = [
        _row("AAPL", stamp),
        _row("AAPL", stamp),
        _row("AAPL", datetime(2026, 10, 2, 3, 59, tzinfo=module.NY)),
        {"ticker": "", "timestamp": stamp.isoformat()},
    ]
    report = module.build_report(rows)
    assert report["duplicate_ticker_minute_count"] == 1
    assert report["out_of_session_row_count"] == 1
    assert report["malformed_row_count"] == 1
    assert report["symbol_session_count"] == 1


def test_utc_timestamps_are_bucketed_by_new_york_session_time():
    rows = [
        {"ticker": "AAPL", "timestamp": "2026-10-02T08:00:00Z"},
        {"ticker": "AAPL", "timestamp": "2026-10-02T13:30:00Z"},
        {"ticker": "AAPL", "timestamp": "2026-10-02T19:59:00Z"},
    ]
    report = module.build_report(rows)
    projection = report["symbol_sessions"][0]
    assert projection["session_date"] == "2026-10-02"
    assert projection["premarket"]["observed_minute_count"] == 1
    assert projection["regular_hours"]["observed_minute_count"] == 2
