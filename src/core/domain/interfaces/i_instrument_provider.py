"""IInstrumentProvider — domain port for broker instrument master downloads.

Broker adapters (KiteInstrumentProvider, …) implement this interface.
The application layer depends only on this port — never on broker SDKs.

IDataProvider (Phase 9) is a separate interface for live price data
(get_ltp, get_candles, get_option_chain). This interface is solely for
the daily instrument master sync.

Reference: docs/13_INSTRUMENT_MASTER.md §Refresh Lifecycle
           docs/09_CLAUDE_EXECUTION_RULES.md §MARKET DATA RULES
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date


class IInstrumentProvider(ABC):
    """Broker-agnostic interface for fetching instrument master data."""

    @abstractmethod
    async def download_instruments(self, exchange: str) -> list[dict[str, str]]:
        """Download raw instrument records for an exchange.

        Args:
            exchange: Exchange code (e.g. "NSE", "NFO", "BSE").

        Returns:
            List of raw instrument dicts. Each dict must contain at minimum:
            instrument_token, tradingsymbol, name, expiry, strike, tick_size,
            lot_size, instrument_type, segment, exchange.
        """

    @abstractmethod
    async def get_trading_holidays(self, exchange: str, year: int) -> list[date]:
        """Return trading holidays for an exchange and year.

        Args:
            exchange: Exchange code (e.g. "NSE").
            year: Calendar year.

        Returns:
            Sorted list of holiday dates on which the exchange is closed.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier for this provider (e.g. 'kite', 'angel')."""
