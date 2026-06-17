"""Unit tests for the Symbol value object."""

from __future__ import annotations

import pytest

from core.domain.value_objects.symbol import Symbol


class TestSymbolConstruction:
    def test_basic_symbol(self) -> None:
        s = Symbol("NIFTY")
        assert s.ticker == "NIFTY"
        assert s.exchange == "NSE"

    def test_lowercase_is_uppercased(self) -> None:
        s = Symbol("nifty", "nse")
        assert s.ticker == "NIFTY"
        assert s.exchange == "NSE"

    def test_whitespace_is_stripped(self) -> None:
        s = Symbol("  NIFTY  ", "  NSE  ")
        assert s.ticker == "NIFTY"
        assert s.exchange == "NSE"

    def test_custom_exchange(self) -> None:
        s = Symbol("BANKNIFTY", "NSE_FO")
        assert s.exchange == "NSE_FO"

    def test_empty_ticker_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Symbol("")

    def test_empty_exchange_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Symbol("NIFTY", "")

    def test_invalid_characters_raise(self) -> None:
        with pytest.raises(ValueError):
            Symbol("NIFTY 50")

    def test_ampersand_allowed(self) -> None:
        s = Symbol("M&M")
        assert s.ticker == "M&M"

    def test_hyphen_allowed(self) -> None:
        s = Symbol("NIFTY-50")
        assert s.ticker == "NIFTY-50"


class TestSymbolEquality:
    def test_equal_symbols(self) -> None:
        assert Symbol("NIFTY") == Symbol("NIFTY")

    def test_different_ticker(self) -> None:
        assert Symbol("NIFTY") != Symbol("BANKNIFTY")

    def test_different_exchange(self) -> None:
        assert Symbol("NIFTY", "NSE") != Symbol("NIFTY", "BSE")

    def test_hashable(self) -> None:
        symbols = {Symbol("NIFTY"), Symbol("NIFTY"), Symbol("BANKNIFTY")}
        assert len(symbols) == 2

    def test_full_property(self) -> None:
        assert Symbol("NIFTY").full == "NIFTY:NSE"

    def test_str(self) -> None:
        assert str(Symbol("NIFTY")) == "NIFTY:NSE"

    def test_repr(self) -> None:
        assert "NIFTY" in repr(Symbol("NIFTY"))
