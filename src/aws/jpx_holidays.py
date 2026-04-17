"""JPX (Tokyo Stock Exchange) holiday calendar.

Provides a check for whether a given date is a JPX trading day.
Holidays are maintained as a static set per year; add future years as they become available.
"""
from datetime import date, timedelta
from typing import Set


# JPX holidays (non-trading days excluding weekends).
# Source: https://www.jpx.co.jp/english/corporate/about-jpx/calendar/
_JPX_HOLIDAYS: Set[date] = {
    # 2025
    date(2025, 1, 1),
    date(2025, 1, 2),
    date(2025, 1, 3),
    date(2025, 1, 13),
    date(2025, 2, 11),
    date(2025, 2, 23),
    date(2025, 2, 24),
    date(2025, 3, 20),
    date(2025, 4, 29),
    date(2025, 5, 3),
    date(2025, 5, 4),
    date(2025, 5, 5),
    date(2025, 5, 6),
    date(2025, 7, 21),
    date(2025, 8, 11),
    date(2025, 9, 15),
    date(2025, 9, 23),
    date(2025, 10, 13),
    date(2025, 11, 3),
    date(2025, 11, 23),
    date(2025, 11, 24),
    date(2025, 12, 31),
    # 2026
    date(2026, 1, 1),
    date(2026, 1, 2),
    date(2026, 1, 3),
    date(2026, 1, 12),
    date(2026, 2, 11),
    date(2026, 2, 23),
    date(2026, 3, 20),
    date(2026, 4, 29),
    date(2026, 5, 3),
    date(2026, 5, 4),
    date(2026, 5, 5),
    date(2026, 5, 6),
    date(2026, 7, 20),
    date(2026, 8, 11),
    date(2026, 9, 21),
    date(2026, 9, 22),
    date(2026, 9, 23),
    date(2026, 10, 12),
    date(2026, 11, 3),
    date(2026, 11, 23),
    date(2026, 12, 31),
    # 2027
    date(2027, 1, 1),
    date(2027, 1, 2),
    date(2027, 1, 3),
    date(2027, 1, 11),
    date(2027, 2, 11),
    date(2027, 2, 23),
    date(2027, 3, 21),
    date(2027, 3, 22),
    date(2027, 4, 29),
    date(2027, 5, 3),
    date(2027, 5, 4),
    date(2027, 5, 5),
    date(2027, 7, 19),
    date(2027, 8, 11),
    date(2027, 9, 20),
    date(2027, 9, 23),
    date(2027, 10, 11),
    date(2027, 11, 3),
    date(2027, 11, 23),
    date(2027, 12, 31),
}


def is_jpx_trading_day(d: date) -> bool:
    """Return True if the given date is a JPX trading day (weekday and not a holiday)."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d not in _JPX_HOLIDAYS


def next_trading_day(d: date) -> date:
    """Return the next JPX trading day on or after the given date."""
    while not is_jpx_trading_day(d):
        d += timedelta(days=1)
    return d
