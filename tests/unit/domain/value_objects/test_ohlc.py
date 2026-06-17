"""Unit tests for OHLC value object."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.domain.value_objects.ohlc import OHLC


class TestOHLC:
    def test_construction(self) -> None:
        ohlc = OHLC(
            open=Decimal("100.00"),
            high=Decimal("110.00"),
            low=Decimal("95.00"),
            close=Decimal("105.00"),
        )
        assert ohlc.open == Decimal("100.00")
        assert ohlc.high == Decimal("110.00")
        assert ohlc.low == Decimal("95.00")
        assert ohlc.close == Decimal("105.00")

    def test_immutable(self) -> None:
        import dataclasses
        ohlc = OHLC(
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ohlc.open = Decimal("999")  # type: ignore[misc]

    def test_fields_are_decimal(self) -> None:
        ohlc = OHLC(
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("3"),
            close=Decimal("4"),
        )
        assert isinstance(ohlc.open, Decimal)
        assert isinstance(ohlc.high, Decimal)
        assert isinstance(ohlc.low, Decimal)
        assert isinstance(ohlc.close, Decimal)

    def test_equality(self) -> None:
        a = OHLC(Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"))
        b = OHLC(Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"))
        assert a == b
