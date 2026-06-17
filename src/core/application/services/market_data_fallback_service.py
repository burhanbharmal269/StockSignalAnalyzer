"""MarketDataFallbackService — priority-chain market data with automatic failover.

Priority chain (highest → lowest):
  1. Kite WebSocket / REST  (primary live data)
  2. Angel One SmartAPI REST (secondary live data)
  3. NSE public endpoint     (tertiary; rate-limited, no options)
  4. Redis cache             (last resort; returns stale data with age tag)

Each provider implements IMarketDataProvider.
The service tries providers in order and returns the first successful result.
On cache hit from layer 4, the result carries `is_stale=True`.

Architecture:
  - No provider is imported directly here — DI injects the list.
  - Provider failures are counted per symbol for circuit-break purposes (future).
  - All methods are async.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@dataclass
class MarketQuote:
    symbol: str
    last_price: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: str
    is_stale: bool = False
    source: str = ""


@dataclass
class OptionChainEntry:
    strike: float
    call_ltp: float | None
    put_ltp: float | None
    call_oi: int | None
    put_oi: int | None
    call_iv: float | None
    put_iv: float | None


@dataclass
class OptionChain:
    underlying: str
    expiry: str
    entries: list[OptionChainEntry] = field(default_factory=list)
    source: str = ""
    is_stale: bool = False


@runtime_checkable
class IMarketDataProvider(Protocol):
    provider_name: str

    async def get_quote(self, symbol: str, exchange: str) -> MarketQuote | None: ...

    async def get_option_chain(self, underlying: str, expiry: str) -> OptionChain | None: ...

    async def is_available(self) -> bool: ...


class MarketDataFallbackService:
    """Attempts each provider in priority order; returns first successful result."""

    def __init__(self, providers: list[IMarketDataProvider]) -> None:
        self._providers = providers

    async def get_quote(self, symbol: str, exchange: str = "NSE") -> MarketQuote | None:
        for provider in self._providers:
            try:
                if not await provider.is_available():
                    continue
                quote = await provider.get_quote(symbol, exchange)
                if quote is not None:
                    quote.source = provider.provider_name
                    log.debug(
                        "market_data.quote_hit",
                        extra={"symbol": symbol, "provider": provider.provider_name},
                    )
                    return quote
            except Exception:  # noqa: BLE001
                log.warning(
                    "market_data.provider_failed",
                    extra={"symbol": symbol, "provider": provider.provider_name},
                    exc_info=True,
                )
        log.error("market_data.all_providers_failed", extra={"symbol": symbol})
        return None

    async def get_option_chain(self, underlying: str, expiry: str) -> OptionChain | None:
        for provider in self._providers:
            try:
                if not await provider.is_available():
                    continue
                chain = await provider.get_option_chain(underlying, expiry)
                if chain is not None:
                    chain.source = provider.provider_name
                    return chain
            except Exception:  # noqa: BLE001
                log.warning(
                    "market_data.option_chain_provider_failed",
                    extra={"underlying": underlying, "provider": provider.provider_name},
                    exc_info=True,
                )
        return None
