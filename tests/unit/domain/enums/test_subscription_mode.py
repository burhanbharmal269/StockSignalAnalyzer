"""Unit tests for SubscriptionMode enum."""

from __future__ import annotations

from core.domain.enums.subscription_mode import SubscriptionMode


class TestSubscriptionMode:
    def test_all_modes_defined(self) -> None:
        assert set(SubscriptionMode) == {
            SubscriptionMode.LTP,
            SubscriptionMode.QUOTE,
            SubscriptionMode.FULL,
        }

    def test_is_str_enum(self) -> None:
        assert isinstance(SubscriptionMode.LTP, str)
        assert SubscriptionMode.LTP == "LTP"

    def test_values(self) -> None:
        assert SubscriptionMode.LTP.value == "LTP"
        assert SubscriptionMode.QUOTE.value == "QUOTE"
        assert SubscriptionMode.FULL.value == "FULL"

    def test_count(self) -> None:
        assert len(SubscriptionMode) == 3
