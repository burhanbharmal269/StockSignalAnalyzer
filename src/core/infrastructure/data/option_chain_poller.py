"""OptionChainPoller — periodic REST-based option chain snapshot fetcher.

Polls IBroker.get_option_chain() every ``poll_interval_seconds`` (default 60)
for each configured (symbol, expiry) pair and publishes OptionChainUpdatedEvent
to the event bus.

Per docs/12_WEBSOCKET_MANAGER.md §Option Chain Polling:
    "Real-time option chain updates for the full chain are not available via
     the Kite WebSocket. The manager uses a hybrid approach."

This service handles the REST side of that hybrid.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.events.market_events import OptionChainUpdatedEvent
from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from core.domain.entities.broker_session import BrokerSession
    from core.domain.interfaces.i_broker import IBroker
    from core.domain.interfaces.i_event_bus import IEventBus

logger = get_logger(__name__)


class OptionChainPoller:
    """Background service that polls option chains and publishes update events.

    Lifecycle:
        poller.configure(broker, session, symbols)
        await poller.start()
        ...
        await poller.stop()
    """

    def __init__(
        self,
        event_bus: IEventBus,
        poll_interval_seconds: int = 60,
    ) -> None:
        self._bus = event_bus
        self._poll_interval = poll_interval_seconds
        self._symbols: list[tuple[str, date]] = []
        self._broker: IBroker | None = None
        self._session: BrokerSession | None = None
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]

    def configure(
        self,
        broker: IBroker,
        session: BrokerSession,
        symbols: list[tuple[str, date]],
    ) -> None:
        """Set the broker, session, and symbol/expiry pairs to poll.

        Call this after login and before start(). Can be called again
        mid-session to change the watched symbols.
        """
        self._broker = broker
        self._session = session
        self._symbols = list(symbols)
        logger.info(
            "option_chain_poller.configured",
            symbol_count=len(self._symbols),
            poll_interval_seconds=self._poll_interval,
        )

    async def start(self) -> None:
        """Start background polling loop."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("option_chain_poller.started")

    async def stop(self) -> None:
        """Cancel the polling loop gracefully."""
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        logger.info("option_chain_poller.stopped")

    async def poll_once(self) -> None:
        """Fetch and publish all configured option chains immediately.

        Useful for testing or manual triggers outside the background loop.
        """
        await self._poll()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while True:
            await self._poll()
            await asyncio.sleep(self._poll_interval)

    async def _poll(self) -> None:
        if self._broker is None or self._session is None:
            logger.warning("option_chain_poller.not_configured")
            return

        for symbol, expiry in self._symbols:
            try:
                entries = await self._broker.get_option_chain(
                    self._session, symbol, expiry
                )
                pcr = _compute_pcr(entries)
                event = OptionChainUpdatedEvent(
                    symbol=symbol,
                    expiry_date=expiry.isoformat(),
                    entry_count=len(entries),
                    pcr=pcr,
                )
                await self._bus.publish(event)
                logger.debug(
                    "option_chain_poller.published",
                    symbol=symbol,
                    expiry=expiry.isoformat(),
                    entries=len(entries),
                    pcr=str(pcr),
                )
            except Exception:
                logger.exception(
                    "option_chain_poller.poll_failed",
                    symbol=symbol,
                    expiry=expiry.isoformat(),
                )


def _compute_pcr(entries: list) -> Decimal:
    """Compute Put/Call Ratio from open interest of all strikes."""
    call_oi = sum(e.open_interest for e in entries if e.option_type == "CE")
    put_oi = sum(e.open_interest for e in entries if e.option_type == "PE")
    if call_oi == 0:
        return Decimal("0")
    return Decimal(str(put_oi)) / Decimal(str(call_oi))
