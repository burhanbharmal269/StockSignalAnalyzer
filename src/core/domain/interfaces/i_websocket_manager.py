"""IWebSocketManager — domain port for broker WebSocket connections.

Infrastructure provides the adapter (KiteWebSocketManager, InMemoryWebSocketManager).
The domain and application layers depend only on this interface.

Reference: docs/12_WEBSOCKET_MANAGER.md §Interface Definition
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from core.domain.enums.connection_state import ConnectionState
from core.domain.enums.subscription_mode import SubscriptionMode

# Type alias — broker-assigned integer token identifying one instrument.
InstrumentToken = int


class IWebSocketManager(ABC):
    """Broker-agnostic WebSocket connection manager.

    Lifecycle:
        await manager.start()          — connect and authenticate
        await manager.subscribe(...)   — declare instruments to stream
        await manager.stop()           — graceful disconnect

    Ticks are published to IEventBus as TickReceivedEvent; callers never
    receive ticks directly from this interface.
    """

    @abstractmethod
    async def start(self) -> None:
        """Initiate connection and authenticate with the broker."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully disconnect and release all resources."""

    @abstractmethod
    async def subscribe(
        self,
        instruments: list[InstrumentToken],
        mode: SubscriptionMode,
    ) -> None:
        """Add instruments to the active subscription set.

        Args:
            instruments: Broker token integers to subscribe.
            mode:        Data density for the subscription.
        """

    @abstractmethod
    async def unsubscribe(self, instruments: list[InstrumentToken]) -> None:
        """Remove instruments from the active subscription set."""

    @abstractmethod
    def get_connection_state(self) -> ConnectionState:
        """Return the current connection state (non-blocking)."""

    @abstractmethod
    def get_subscription_count(self) -> int:
        """Return the total number of currently subscribed instruments."""

    @abstractmethod
    def get_last_tick_time(self, instrument: InstrumentToken) -> datetime | None:
        """Return UTC time of the last tick received for an instrument.

        Returns None if no tick has been received for that instrument yet.
        """
