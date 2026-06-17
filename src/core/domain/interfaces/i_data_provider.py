"""IDataProvider — domain port for external market data sources.

Infrastructure adapters (KiteDataProvider, NseProvider) implement this
interface. The domain and application layers depend only on the port.

Reference: docs/12_WEBSOCKET_MANAGER.md, docs/13_INSTRUMENT_MASTER.md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date


class IDataProvider(ABC):
    """Broker-agnostic interface for fetching instrument and market data."""

    @abstractmethod
    async def download_instruments(self, exchange: str) -> list[dict[str, str]]:
        """Download instrument master records for an exchange.

        Args:
            exchange: Exchange code (e.g. "NSE", "NFO", "BSE").

        Returns:
            List of raw instrument dicts parsed from the provider response.
            Each dict has at minimum: instrument_token, tradingsymbol,
            exchange_token, name, last_price, expiry, strike, tick_size,
            lot_size, instrument_type, segment, exchange.
        """

    @abstractmethod
    async def get_trading_holidays(self, exchange: str, year: int) -> list[date]:
        """Return the list of trading holidays for an exchange and year.

        Args:
            exchange: Exchange code (e.g. "NSE").
            year: Calendar year.

        Returns:
            Sorted list of holiday dates on which the exchange is closed.
        """
