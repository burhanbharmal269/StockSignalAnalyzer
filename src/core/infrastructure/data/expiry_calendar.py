"""ExpiryCalendar — NSE FnO expiry date computation with holiday adjustment.

Implements the expiry rules defined in docs/13_INSTRUMENT_MASTER.md
§Expiry Calendar Management. All logic is pure (no I/O); holiday lists
are injected so the class is fully testable without network calls.

Reference: docs/13_INSTRUMENT_MASTER.md
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from enum import StrEnum


class ExpiryType(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


# Standard expiry weekdays per underlying (0=Monday … 6=Sunday).
# These are the canonical expiry days before holiday adjustment.
_WEEKLY_EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY": 3,         # Thursday
    "BANKNIFTY": 2,     # Wednesday
    "FINNIFTY": 1,      # Tuesday
    "MIDCPNIFTY": 0,    # Monday
    "SENSEX": 4,        # Friday (BSE)
    "BANKEX": 4,        # Friday (BSE)
}
_DEFAULT_WEEKLY_WEEKDAY = 3  # Thursday for unknown underlyings


class ExpiryCalendar:
    """Computes NSE/BSE FnO expiry dates with holiday adjustment.

    Holiday list is injected at construction time (sourced from the
    IDataProvider.get_trading_holidays call during refresh).
    """

    def __init__(self, holidays: set[date] | None = None) -> None:
        self._holidays: set[date] = holidays or set()

    def set_holidays(self, holidays: set[date]) -> None:
        """Replace the holiday set (called after each annual update)."""
        self._holidays = set(holidays)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_weekly_expiry(self, underlying: str, reference_date: date) -> date:
        """Return the weekly expiry on or after reference_date.

        The returned date is holiday-adjusted per the spec.
        """
        weekday = _WEEKLY_EXPIRY_WEEKDAY.get(underlying.upper(), _DEFAULT_WEEKLY_WEEKDAY)
        days_ahead = (weekday - reference_date.weekday()) % 7
        candidate = reference_date + timedelta(days=days_ahead)
        return self._adjust_for_holiday(candidate, underlying)

    def get_monthly_expiry(self, underlying: str, year: int, month: int) -> date:
        """Return the last-Thursday-of-month expiry, holiday-adjusted.

        For USDINR/currency: returns the last business day of the month.
        """
        if underlying.upper() in {"USDINR", "EURINR", "GBPINR", "JPYINR"}:
            return self._last_business_day(year, month)
        return self._last_thursday(year, month, underlying)

    def is_trading_day(self, check_date: date) -> bool:
        """Return True if the date is a weekday and not a market holiday."""
        if check_date.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return check_date not in self._holidays

    def get_dte(self, expiry: date, from_date: date | None = None) -> int:
        """Return calendar days from from_date to expiry (0 on expiry day)."""
        base = from_date or date.today()
        delta = (expiry - base).days
        return max(0, delta)

    def get_next_expiry_after(
        self, underlying: str, after_date: date, expiry_type: ExpiryType
    ) -> date:
        """Return the first expiry strictly after after_date."""
        if expiry_type == ExpiryType.WEEKLY:
            candidate = self.get_weekly_expiry(underlying, after_date)
            if candidate <= after_date:
                candidate = self.get_weekly_expiry(
                    underlying, after_date + timedelta(days=1)
                )
            return candidate
        # Monthly
        year, month = after_date.year, after_date.month
        candidate = self.get_monthly_expiry(underlying, year, month)
        if candidate <= after_date:
            # Move to next month
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1
            candidate = self.get_monthly_expiry(underlying, year, month)
        return candidate

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _adjust_for_holiday(self, expiry: date, underlying: str) -> date:
        """Move expiry backward one business day if it falls on a holiday."""
        candidate = expiry
        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def _last_thursday(self, year: int, month: int, underlying: str) -> date:
        """Return the last Thursday of the given month, holiday-adjusted."""
        # Find last day of month
        last_day = calendar.monthrange(year, month)[1]
        candidate = date(year, month, last_day)
        # Walk back to Thursday (weekday 3)
        while candidate.weekday() != 3:
            candidate -= timedelta(days=1)
        return self._adjust_for_holiday(candidate, underlying)

    def _last_business_day(self, year: int, month: int) -> date:
        """Return the last business day (non-holiday weekday) of the month."""
        last_day = calendar.monthrange(year, month)[1]
        candidate = date(year, month, last_day)
        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate
