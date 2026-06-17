"""Unit tests for the Price value object."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.domain.value_objects.price import Price


class TestPriceConstruction:
    def test_from_decimal(self) -> None:
        p = Price(Decimal("100.50"))
        assert p.value == Decimal("100.50")

    def test_from_int(self) -> None:
        p = Price(100)
        assert p.value == Decimal("100")

    def test_from_string(self) -> None:
        p = Price("99.95")
        assert p.value == Decimal("99.95")

    def test_float_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="float"):
            Price(100.5)  # type: ignore[arg-type]

    def test_invalid_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            Price("not_a_number")

    def test_zero_factory(self) -> None:
        assert Price.zero().value == Decimal("0")

    def test_from_str_factory(self) -> None:
        p = Price.from_str("42.10")
        assert p.value == Decimal("42.10")


class TestPriceArithmetic:
    def test_add(self) -> None:
        assert Price("10") + Price("5") == Price("15")

    def test_subtract(self) -> None:
        assert Price("10") - Price("5") == Price("5")

    def test_subtract_yields_negative(self) -> None:
        result = Price("5") - Price("10")
        assert result.value == Decimal("-5")

    def test_multiply_by_int(self) -> None:
        assert Price("10") * 3 == Price("30")

    def test_multiply_by_decimal(self) -> None:
        assert Price("10") * Decimal("1.5") == Price("15")

    def test_multiply_by_float_raises(self) -> None:
        with pytest.raises(TypeError):
            Price("10") * 1.5  # type: ignore[operator]

    def test_divide_by_int(self) -> None:
        assert Price("10") / 2 == Price("5")

    def test_divide_by_float_raises(self) -> None:
        with pytest.raises(TypeError):
            Price("10") / 2.0  # type: ignore[operator]

    def test_negate(self) -> None:
        assert -Price("10") == Price("-10")

    def test_abs(self) -> None:
        assert abs(Price("-10")) == Price("10")


class TestPriceComparison:
    def test_equal(self) -> None:
        assert Price("10") == Price("10")

    def test_not_equal(self) -> None:
        assert Price("10") != Price("11")

    def test_less_than(self) -> None:
        assert Price("9") < Price("10")

    def test_less_than_or_equal(self) -> None:
        assert Price("10") <= Price("10")
        assert Price("9") <= Price("10")

    def test_greater_than(self) -> None:
        assert Price("11") > Price("10")

    def test_greater_than_or_equal(self) -> None:
        assert Price("10") >= Price("10")
        assert Price("11") >= Price("10")

    def test_hashable(self) -> None:
        prices = {Price("10"), Price("10"), Price("20")}
        assert len(prices) == 2

    def test_repr(self) -> None:
        assert "100" in repr(Price("100"))

    def test_str(self) -> None:
        assert str(Price("42.5")) == "42.5"
