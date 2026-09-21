from __future__ import annotations

from datetime import date
import tempfile
from pathlib import Path
import unittest

from collect_alpaca_session_data import (
    SESSION_WINDOWS,
    build_receipt,
    normalized_rows,
    utc_bounds,
    write_csv,
)


class SessionCollectorTests(unittest.TestCase):
    def test_dst_safe_regular_bounds(self):
        summer = utc_bounds(date(2026, 9, 21), SESSION_WINDOWS["regular"])
        winter = utc_bounds(date(2026, 12, 21), SESSION_WINDOWS["regular"])
        self.assertEqual(summer, ("2026-09-21T13:30:00Z", "2026-09-21T20:00:00Z"))
        self.assertEqual(winter, ("2026-12-21T14:30:00Z", "2026-12-21T21:00:00Z"))

    def test_after_hours_filters_boundaries_and_duplicates(self):
        rows = {
            "AAPL": [
                {"t": "2026-09-21T19:59:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 10},
                {"t": "2026-09-21T20:00:00Z", "o": 2, "h": 3, "l": 2, "c": 3, "v": 11},
                {"t": "2026-09-21T20:00:00Z", "o": 2, "h": 3, "l": 2, "c": 3, "v": 11},
                {"t": "2026-09-21T23:59:00Z", "o": 3, "h": 4, "l": 3, "c": 4, "v": 12},
                {"t": "2026-09-22T00:00:00Z", "o": 4, "h": 5, "l": 4, "c": 5, "v": 13},
            ]
        }
        output = normalized_rows(rows, date(2026, 9, 21), SESSION_WINDOWS["after_hours"])
        self.assertEqual([row["timestamp"] for row in output], ["2026-09-21T20:00:00Z", "2026-09-21T23:59:00Z"])

    def test_receipt_fails_closed_when_symbol_is_missing(self):
        rows = [{"ticker": "AAPL", "timestamp": "2026-09-21T13:30:00Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bars.csv"
            write_csv(output, rows)
            receipt = build_receipt(
                output=output,
                rows=rows,
                symbols=["AAPL", "MSFT"],
                session_date=date(2026, 9, 21),
                window=SESSION_WINDOWS["regular"],
                feed="iex",
                collected_at_utc="2026-09-21T20:17:00Z",
                github_run_id="123",
                github_run_attempt="1",
                github_head_sha="a" * 40,
            )
        self.assertFalse(receipt["valid"])
        self.assertFalse(receipt["self_improvement_eligible"])

    def test_market_holiday_is_valid_but_not_learning_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bars.csv"
            write_csv(output, [])
            receipt = build_receipt(
                output=output,
                rows=[],
                symbols=["AAPL"],
                session_date=date(2026, 12, 25),
                window=SESSION_WINDOWS["regular"],
                feed="iex",
                collected_at_utc="2026-12-25T21:17:00Z",
                github_run_id="124",
                github_run_attempt="1",
                github_head_sha="b" * 40,
                market_day=False,
            )
        self.assertTrue(receipt["valid"])
        self.assertFalse(receipt["self_improvement_eligible"])
        self.assertEqual(receipt["eligibility_reason"], "market_closed")


if __name__ == "__main__":
    unittest.main()
