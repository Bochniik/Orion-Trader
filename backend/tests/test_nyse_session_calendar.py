from __future__ import annotations

from datetime import date
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "nyse_session_calendar.py"
spec = importlib.util.spec_from_file_location("nyse_session_calendar", SCRIPT)
calendar = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = calendar
spec.loader.exec_module(calendar)


def test_2026_recurring_nyse_full_day_closures_are_not_sessions():
    expected = {
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }

    assert expected <= calendar.nyse_full_day_holidays(2026)
    assert all(calendar.is_nyse_trading_day(day) is False for day in expected)


def test_good_friday_is_exchange_specific_not_a_federal_weekday_proxy():
    assert calendar.is_nyse_trading_day(date(2026, 4, 3)) is False
    assert calendar.is_nyse_trading_day(date(2026, 4, 2)) is True
    assert calendar.is_nyse_trading_day(date(2026, 4, 6)) is True


def test_weekends_and_normal_weekdays_are_classified_deterministically():
    assert calendar.is_nyse_trading_day(date(2026, 9, 12)) is False
    assert calendar.is_nyse_trading_day(date(2026, 9, 13)) is False
    assert calendar.is_nyse_trading_day(date(2026, 9, 11)) is True


def test_new_years_saturday_is_not_shifted_back_into_prior_year():
    # 2022-01-01 was Saturday; NYSE did not close Friday 2021-12-31 for it.
    assert date(2021, 12, 31) not in calendar.nyse_full_day_holidays(2021)
    assert calendar.is_nyse_trading_day(date(2021, 12, 31)) is True
