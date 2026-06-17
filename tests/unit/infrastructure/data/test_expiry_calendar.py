"""Unit tests for ExpiryCalendar — NSE FnO expiry rules and holiday adjustment."""

from __future__ import annotations

from datetime import date

from core.infrastructure.data.expiry_calendar import ExpiryCalendar, ExpiryType


def _calendar(holidays: list[date] | None = None) -> ExpiryCalendar:
    return ExpiryCalendar(holidays=set(holidays) if holidays else None)


class TestIsTradingDay:
    def test_weekday_no_holiday_is_trading(self) -> None:
        cal = _calendar()
        assert cal.is_trading_day(date(2025, 1, 2)) is True  # Thursday

    def test_saturday_not_trading(self) -> None:
        cal = _calendar()
        assert cal.is_trading_day(date(2025, 1, 4)) is False  # Saturday

    def test_sunday_not_trading(self) -> None:
        cal = _calendar()
        assert cal.is_trading_day(date(2025, 1, 5)) is False  # Sunday

    def test_holiday_not_trading(self) -> None:
        holiday = date(2025, 1, 26)
        cal = _calendar([holiday])
        assert cal.is_trading_day(holiday) is False

    def test_non_holiday_weekday_is_trading(self) -> None:
        cal = _calendar([date(2025, 1, 26)])
        assert cal.is_trading_day(date(2025, 1, 27)) is True  # Monday after Republic Day


class TestGetDte:
    def test_future_expiry_returns_days(self) -> None:
        cal = _calendar()
        expiry = date(2025, 6, 26)
        from_date = date(2025, 6, 20)
        assert cal.get_dte(expiry, from_date=from_date) == 6

    def test_expiry_day_returns_zero(self) -> None:
        cal = _calendar()
        expiry = date(2025, 6, 26)
        assert cal.get_dte(expiry, from_date=expiry) == 0

    def test_past_expiry_returns_zero(self) -> None:
        cal = _calendar()
        expiry = date(2025, 1, 1)
        assert cal.get_dte(expiry, from_date=date(2025, 6, 20)) == 0


class TestWeeklyExpiry:
    def test_nifty_weekly_is_thursday(self) -> None:
        cal = _calendar()
        # Find Thursday on or after 2025-06-16 (Monday)
        expiry = cal.get_weekly_expiry("NIFTY", date(2025, 6, 16))
        assert expiry.weekday() == 3  # Thursday

    def test_banknifty_weekly_is_wednesday(self) -> None:
        cal = _calendar()
        expiry = cal.get_weekly_expiry("BANKNIFTY", date(2025, 6, 16))
        assert expiry.weekday() == 2  # Wednesday

    def test_finnifty_weekly_is_tuesday(self) -> None:
        cal = _calendar()
        expiry = cal.get_weekly_expiry("FINNIFTY", date(2025, 6, 16))
        assert expiry.weekday() == 1  # Tuesday

    def test_midcpnifty_weekly_is_monday(self) -> None:
        cal = _calendar()
        expiry = cal.get_weekly_expiry("MIDCPNIFTY", date(2025, 6, 16))
        assert expiry.weekday() == 0  # Monday = reference day itself

    def test_holiday_adjustment_moves_to_previous_weekday(self) -> None:
        # Make Thursday 2025-06-19 a holiday
        holiday = date(2025, 6, 19)  # Thursday
        cal = _calendar([holiday])
        expiry = cal.get_weekly_expiry("NIFTY", date(2025, 6, 16))
        # Should shift to Wednesday 2025-06-18
        assert expiry == date(2025, 6, 18)

    def test_no_adjustment_needed_for_non_holiday(self) -> None:
        cal = _calendar()
        expiry = cal.get_weekly_expiry("NIFTY", date(2025, 6, 19))
        assert expiry == date(2025, 6, 19)  # Already Thursday

    def test_case_insensitive_underlying(self) -> None:
        cal = _calendar()
        assert cal.get_weekly_expiry("nifty", date(2025, 6, 16)) == cal.get_weekly_expiry(
            "NIFTY", date(2025, 6, 16)
        )


class TestMonthlyExpiry:
    def test_monthly_is_last_thursday_of_month(self) -> None:
        cal = _calendar()
        # June 2025: last Thursday is 2025-06-26
        expiry = cal.get_monthly_expiry("NIFTY", 2025, 6)
        assert expiry == date(2025, 6, 26)
        assert expiry.weekday() == 3

    def test_monthly_july_2025(self) -> None:
        cal = _calendar()
        # July 2025: last Thursday is 2025-07-31
        expiry = cal.get_monthly_expiry("NIFTY", 2025, 7)
        assert expiry.weekday() == 3
        assert expiry.month == 7

    def test_holiday_adjustment_on_monthly(self) -> None:
        # Make 2025-06-26 (last Thursday of June) a holiday
        holiday = date(2025, 6, 26)
        cal = _calendar([holiday])
        expiry = cal.get_monthly_expiry("NIFTY", 2025, 6)
        # Should shift back to Wednesday 2025-06-25
        assert expiry == date(2025, 6, 25)

    def test_usdinr_monthly_is_last_business_day(self) -> None:
        cal = _calendar()
        expiry = cal.get_monthly_expiry("USDINR", 2025, 6)
        # Last day of June 2025 is Monday 2025-06-30 (business day)
        assert expiry == date(2025, 6, 30)


class TestGetNextExpiryAfter:
    def test_weekly_returns_next_thursday_after_date(self) -> None:
        cal = _calendar()
        expiry = cal.get_next_expiry_after("NIFTY", date(2025, 6, 19), ExpiryType.WEEKLY)
        # 2025-06-19 is Thursday; next weekly is 2025-06-26
        assert expiry == date(2025, 6, 26)

    def test_monthly_returns_next_month_if_current_passed(self) -> None:
        cal = _calendar()
        # After 2025-06-26 (last Thursday of June), next monthly is July
        expiry = cal.get_next_expiry_after("NIFTY", date(2025, 6, 26), ExpiryType.MONTHLY)
        assert expiry.month == 7


class TestSetHolidays:
    def test_set_holidays_updates_calendar(self) -> None:
        cal = _calendar()
        thursday = date(2025, 6, 19)
        assert cal.is_trading_day(thursday) is True
        cal.set_holidays({thursday})
        assert cal.is_trading_day(thursday) is False
