"""Unit tests for MarketDepth value object."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.domain.value_objects.market_depth import DepthLevel, MarketDepth


def _make_level(price: str = "100.00", qty: int = 10, orders: int = 2) -> DepthLevel:
    return DepthLevel(price=Decimal(price), quantity=qty, orders=orders)


class TestDepthLevel:
    def test_construction(self) -> None:
        level = _make_level("100.50", 50, 3)
        assert level.price == Decimal("100.50")
        assert level.quantity == 50
        assert level.orders == 3

    def test_immutable(self) -> None:
        import dataclasses
        level = _make_level()
        with pytest.raises(dataclasses.FrozenInstanceError):
            level.price = Decimal("999")  # type: ignore[misc]

    def test_price_is_decimal(self) -> None:
        level = _make_level("123.45")
        assert isinstance(level.price, Decimal)


class TestMarketDepth:
    def test_construction_with_five_levels(self) -> None:
        levels = tuple(_make_level(str(100 + i)) for i in range(5))
        depth = MarketDepth(buy=levels, sell=levels)
        assert len(depth.buy) == 5
        assert len(depth.sell) == 5

    def test_immutable(self) -> None:
        import dataclasses
        levels = tuple(_make_level() for _ in range(5))
        depth = MarketDepth(buy=levels, sell=levels)
        with pytest.raises(dataclasses.FrozenInstanceError):
            depth.buy = ()  # type: ignore[misc]

    def test_best_bid_is_first(self) -> None:
        levels = tuple(_make_level(str(100 + i)) for i in range(5))
        depth = MarketDepth(buy=levels, sell=levels)
        assert depth.buy[0].price == Decimal("100")

    def test_equality(self) -> None:
        levels = tuple(_make_level() for _ in range(5))
        a = MarketDepth(buy=levels, sell=levels)
        b = MarketDepth(buy=levels, sell=levels)
        assert a == b
