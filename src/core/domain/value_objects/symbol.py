"""Symbol value object — normalized exchange instrument identifier."""

from __future__ import annotations

import re

_VALID_SYMBOL = re.compile(r"^[A-Z0-9&\-]{1,30}$")


class Symbol:
    """Immutable, normalized instrument symbol.

    Symbols are uppercased on construction. Spaces are rejected.
    Exchange is normalized to uppercase and stripped.
    """

    __slots__ = ("_ticker", "_exchange")

    def __init__(self, ticker: str, exchange: str = "NSE") -> None:
        normalized_ticker = ticker.strip().upper()
        normalized_exchange = exchange.strip().upper()

        if not normalized_ticker:
            msg = "Symbol ticker cannot be empty"
            raise ValueError(msg)
        if not _VALID_SYMBOL.match(normalized_ticker):
            msg = (
                f"Invalid symbol ticker {ticker!r}: must be 1–30 chars, "
                "uppercase letters, digits, '&', or '-' only"
            )
            raise ValueError(msg)
        if not normalized_exchange:
            msg = "Symbol exchange cannot be empty"
            raise ValueError(msg)

        self._ticker = normalized_ticker
        self._exchange = normalized_exchange

    @property
    def ticker(self) -> str:
        return self._ticker

    @property
    def exchange(self) -> str:
        return self._exchange

    @property
    def full(self) -> str:
        """Return 'TICKER:EXCHANGE' canonical form."""
        return f"{self._ticker}:{self._exchange}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Symbol):
            return NotImplemented
        return self._ticker == other._ticker and self._exchange == other._exchange

    def __hash__(self) -> int:
        return hash((self._ticker, self._exchange))

    def __repr__(self) -> str:
        return f"Symbol({self._ticker!r}, {self._exchange!r})"

    def __str__(self) -> str:
        return self.full
