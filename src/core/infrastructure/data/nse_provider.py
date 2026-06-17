"""NseHolidayProvider — static NSE holiday calendar seed data.

Provides a hardcoded bootstrap list of NSE trading holidays for the
current year. The primary source is always the IDataProvider (Kite API);
this seed is a fallback for offline startup and unit tests.

Holidays are updated annually when NSE publishes the schedule.
Reference: docs/13_INSTRUMENT_MASTER.md §Holiday Adjustment
"""

from __future__ import annotations

from datetime import date

# NSE trading holidays for 2025 (published by NSE)
# Source: NSE circular list — update annually.
NSE_HOLIDAYS_2025: list[date] = [
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramzan)
    date(2025, 4, 10),   # Shri Ram Navami
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti / Good Friday
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti / Mahatma Gandhi Birthday
    date(2025, 10, 21),  # Diwali (Laxmi Pujan) — Muhurat trading day
    date(2025, 10, 23),  # Diwali (Balipratipada)
    date(2025, 11, 5),   # Gurunanak Jayanti
    date(2025, 12, 25),  # Christmas
]

# NSE trading holidays for 2026 — to be updated when NSE publishes schedule.
NSE_HOLIDAYS_2026: list[date] = []

_HOLIDAY_MAP: dict[int, list[date]] = {
    2025: NSE_HOLIDAYS_2025,
    2026: NSE_HOLIDAYS_2026,
}


def get_nse_holidays(year: int) -> list[date]:
    """Return the seeded NSE holiday list for a given year.

    Returns an empty list if the year has no seed data yet.
    The caller should supplement with live data from IDataProvider.
    """
    return list(_HOLIDAY_MAP.get(year, []))


def get_nse_holidays_as_set(year: int) -> set[date]:
    """Return the holiday list as a set for O(1) membership tests."""
    return set(get_nse_holidays(year))
