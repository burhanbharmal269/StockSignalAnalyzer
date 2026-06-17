"""Unit tests for Position entity."""

from __future__ import annotations

import pytest

from core.domain.entities.position import Position
from core.domain.enums.position_state import PositionState
from core.domain.enums.signal_type import SignalType
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol


def _long_position(quantity: int = 50, entry: str = "19500") -> Position:
    return Position.open(
        symbol=Symbol("NIFTY"),
        direction=SignalType.LONG,
        quantity=quantity,
        entry_price=Price(entry),
    )


def _short_position(quantity: int = 50, entry: str = "19500") -> Position:
    return Position.open(
        symbol=Symbol("NIFTY"),
        direction=SignalType.SHORT,
        quantity=quantity,
        entry_price=Price(entry),
    )


class TestPositionFactory:
    def test_open_sets_open_state(self) -> None:
        p = _long_position()
        assert p.state == PositionState.OPEN

    def test_current_price_equals_entry_on_open(self) -> None:
        p = _long_position(entry="19500")
        assert p.current_price == Price("19500")

    def test_zero_quantity_raises(self) -> None:
        with pytest.raises(ValueError):
            Position.open(
                symbol=Symbol("NIFTY"),
                direction=SignalType.LONG,
                quantity=0,
                entry_price=Price("19500"),
            )


class TestUnrealizedPnl:
    def test_long_profit(self) -> None:
        p = _long_position(quantity=50, entry="19500")
        p.update_price(Price("19600"))
        expected = Price("100") * 50
        assert p.unrealized_pnl == expected

    def test_long_loss(self) -> None:
        p = _long_position(quantity=50, entry="19500")
        p.update_price(Price("19400"))
        expected = -(Price("100") * 50)
        assert p.unrealized_pnl == expected

    def test_short_profit(self) -> None:
        p = _short_position(quantity=50, entry="19500")
        p.update_price(Price("19400"))
        expected = Price("100") * 50
        assert p.unrealized_pnl == expected

    def test_short_loss(self) -> None:
        p = _short_position(quantity=50, entry="19500")
        p.update_price(Price("19600"))
        expected = -(Price("100") * 50)
        assert p.unrealized_pnl == expected

    def test_no_price_change_zero_pnl(self) -> None:
        p = _long_position(entry="19500")
        assert p.unrealized_pnl == Price.zero()


class TestPositionClose:
    def test_close_sets_closed_state(self) -> None:
        p = _long_position(quantity=50, entry="19500")
        p.close(Price("19600"), 50)
        assert p.state == PositionState.CLOSED

    def test_close_sets_closed_at(self) -> None:
        p = _long_position()
        p.close(Price("19600"), 50)
        assert p.closed_at is not None

    def test_close_computes_realized_pnl_long(self) -> None:
        p = _long_position(quantity=50, entry="19500")
        p.close(Price("19600"), 50)
        assert p.realized_pnl == Price("100") * 50

    def test_close_computes_realized_pnl_short(self) -> None:
        p = _short_position(quantity=50, entry="19500")
        p.close(Price("19400"), 50)
        assert p.realized_pnl == Price("100") * 50

    def test_partial_close_reduces_quantity(self) -> None:
        p = _long_position(quantity=50, entry="19500")
        p.partial_close(Price("19600"), 25)
        assert p.quantity == 25
        assert p.state == PositionState.PARTIALLY_CLOSED

    def test_partial_close_quantity_ge_total_raises(self) -> None:
        p = _long_position(quantity=50, entry="19500")
        with pytest.raises(ValueError):
            p.partial_close(Price("19600"), 50)

    def test_total_pnl_after_partial_then_close(self) -> None:
        p = _long_position(quantity=50, entry="19500")
        p.partial_close(Price("19600"), 25)  # +100 × 25 = +2500
        p.close(Price("19700"), 25)  # +200 × 25 = +5000
        assert p.realized_pnl == Price("7500")
