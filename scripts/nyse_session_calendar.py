from __future__ import annotations

from datetime import date, timedelta


MONDAY = 0
THURSDAY = 3
FRIDAY = 4
SATURDAY = 5
SUNDAY = 6


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (occurrence - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    # Anonymous Gregorian computus. NYSE Good Friday is two days before Easter.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed_fixed(month: int, day: int, year: int, *, saturday_to_friday: bool = True) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == SATURDAY and saturday_to_friday:
        return holiday - timedelta(days=1)
    if holiday.weekday() == SUNDAY:
        return holiday + timedelta(days=1)
    return holiday


def nyse_full_day_holidays(year: int) -> frozenset[date]:
    """Return recurring NYSE full-day closures for a calendar year.

    This intentionally models regular published holiday rules only. One-off
    emergency closures must be handled as collection failures rather than
    silently counted as forward validation sessions.
    """
    holidays = {
        # NYSE does not shift a Saturday New Year's Day back into the prior
        # calendar year; a Sunday New Year's Day is observed on Monday.
        _observed_fixed(1, 1, year, saturday_to_friday=False),
        _nth_weekday(year, 1, MONDAY, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, MONDAY, 3),  # Washington's Birthday
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, MONDAY),  # Memorial Day
        _observed_fixed(7, 4, year),  # Independence Day
        _nth_weekday(year, 9, MONDAY, 1),  # Labor Day
        _nth_weekday(year, 11, THURSDAY, 4),  # Thanksgiving Day
        _observed_fixed(12, 25, year),  # Christmas Day
    }
    if year >= 2022:
        holidays.add(_observed_fixed(6, 19, year))  # Juneteenth National Independence Day
    return frozenset(holidays)


def is_nyse_trading_day(day: date) -> bool:
    if day.weekday() >= SATURDAY:
        return False
    return day not in nyse_full_day_holidays(day.year)
