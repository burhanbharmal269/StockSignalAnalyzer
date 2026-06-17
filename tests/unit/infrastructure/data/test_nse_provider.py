"""Unit tests for NseHolidayProvider — static holiday seed data."""

from __future__ import annotations

from datetime import date

from core.infrastructure.data.nse_provider import get_nse_holidays, get_nse_holidays_as_set


class TestGetNseHolidays:
    def test_returns_list_for_2025(self) -> None:
        holidays = get_nse_holidays(2025)
        assert isinstance(holidays, list)
        assert len(holidays) > 0

    def test_republic_day_2025_is_holiday(self) -> None:
        holidays = get_nse_holidays(2025)
        assert date(2025, 1, 26) in holidays

    def test_returns_empty_list_for_unknown_year(self) -> None:
        holidays = get_nse_holidays(2099)
        assert holidays == []

    def test_does_not_mutate_internal_list(self) -> None:
        h1 = get_nse_holidays(2025)
        h1.append(date(2025, 1, 1))
        h2 = get_nse_holidays(2025)
        assert date(2025, 1, 1) not in h2


class TestGetNseHolidaysAsSet:
    def test_returns_set(self) -> None:
        result = get_nse_holidays_as_set(2025)
        assert isinstance(result, set)

    def test_membership_check(self) -> None:
        holidays = get_nse_holidays_as_set(2025)
        assert date(2025, 1, 26) in holidays

    def test_empty_set_for_unknown_year(self) -> None:
        assert get_nse_holidays_as_set(2099) == set()
