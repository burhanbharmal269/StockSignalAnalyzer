"""IMarketDataProvider — abstraction over live + historical market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle
    from core.domain.value_objects.broker_dtos import OptionChainEntry


class IMarketDataProvider(ABC):
    """Pluggable market data source.  Primary: Kite.  Fallback: NSE."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[HistoricalCandle]: ...

    @abstractmethod
    async def get_ltp(self, symbols: list[str]) -> dict[str, Decimal]: ...

    @abstractmethod
    async def get_option_chain(
        self,
        underlying: str,
        expiry: date | None = None,
        include_futures: bool = False,
    ) -> list[OptionChainEntry]: ...

    @abstractmethod
    async def subscribe_live(
        self,
        symbols: list[str],
        on_tick: Callable[[str, Decimal, dict], None],
    ) -> None: ...

    @abstractmethod
    async def unsubscribe_live(self, symbols: list[str]) -> None: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
