from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from collect_alpaca_extended_history import (
    filter_training_hours,
    parse_symbols,
    request_window,
)


def test_parse_symbols_deduplicates_and_normalizes():
    assert parse_symbols(["aapl, msft", "AAPL", " nvda "]) == ["AAPL", "MSFT", "NVDA"]


def test_request_window_tracks_new_york_dst():
    winter_start, winter_end = request_window(date(2026, 1, 5), date(2026, 1, 5))
    summer_start, summer_end = request_window(date(2026, 7, 6), date(2026, 7, 6))

    assert winter_start.startswith("2026-01-05T09:00:00")
    assert winter_end.startswith("2026-01-05T21:01:00")
    assert summer_start.startswith("2026-07-06T08:00:00")
    assert summer_end.startswith("2026-07-06T20:01:00")


def test_filter_training_hours_keeps_0400_through_1559_new_york():
    rows = [
        {"t": "2026-07-06T07:59:00Z"},  # 03:59 ET
        {"t": "2026-07-06T08:00:00Z"},  # 04:00 ET
        {"t": "2026-07-06T13:30:00Z"},  # 09:30 ET
        {"t": "2026-07-06T19:59:00Z"},  # 15:59 ET
        {"t": "2026-07-06T20:00:00Z"},  # 16:00 ET
    ]
    kept = filter_training_hours(rows)
    assert [row["t"] for row in kept] == [
        "2026-07-06T08:00:00Z",
        "2026-07-06T13:30:00Z",
        "2026-07-06T19:59:00Z",
    ]
