"""InMemoryWebSocketManager — synchronous in-process adapter for unit tests.

No real network I/O. Tests inject ticks via inject_tick() and verify
downstream behaviour by inspecting the InMemoryEventBus.

Reference: docs/12_WEBSOCKET_MANAGER.md §Testing Strategy
"""

from __future__ import annotations

from datetime import datetime

from core.domain.enums.connection_state import ConnectionState
from core.domain.enums.subscription_mode import SubscriptionMode
from core.domain.events.tick_received import TickReceivedEvent
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_websocket_manager import InstrumentToken, IWebSocketManager


class InMemoryWebSocketManager(IWebSocketManager):
    """Test-only WebSocket manager with no external dependencies.

    Usage in tests:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        await manager.start()
        await manager.subscribe([256265], SubscriptionMode.FULL)
        tick = TickReceivedEvent(instrument_token=256265, ...)
        await manager.inject_tick(tick)
        assert bus.published_events(TickReceivedEvent) == [tick]
    """

    def __init__(self, event_bus: IEventBus) -> None:
        self._event_bus = event_bus
        self._state: ConnectionState = ConnectionState.DISCONNECTED
        self._subscriptions: dict[InstrumentToken, SubscriptionMode] = {}
        self._last_tick_times: dict[InstrumentToken, datetime] = {}

    # ------------------------------------------------------------------
    # IWebSocketManager implementation
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Simulate a successful connect → authenticate → subscribe cycle."""
        self._state = ConnectionState.STREAMING

    async def stop(self) -> None:
        """Simulate graceful disconnect."""
        self._state = ConnectionState.DISCONNECTED

    async def subscribe(
        self,
        instruments: list[InstrumentToken],
        mode: SubscriptionMode,
    ) -> None:
        """Record subscriptions without contacting any broker."""
        for token in instruments:
            self._subscriptions[token] = mode

    async def unsubscribe(self, instruments: list[InstrumentToken]) -> None:
        """Remove instruments from the tracked subscription set."""
        for token in instruments:
            self._subscriptions.pop(token, None)

    def get_connection_state(self) -> ConnectionState:
        return self._state

    def get_subscription_count(self) -> int:
        return len(self._subscriptions)

    def get_last_tick_time(self, instrument: InstrumentToken) -> datetime | None:
        return self._last_tick_times.get(instrument)

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    async def inject_tick(self, tick: TickReceivedEvent) -> None:
        """Publish a synthetic tick as if it arrived from the broker.

        Updates the last-tick-time tracker and publishes to the event bus.
        """
        self._last_tick_times[tick.instrument_token] = tick.occurred_at
        await self._event_bus.publish(tick)

    def set_state(self, state: ConnectionState) -> None:
        """Directly set the connection state for testing error paths."""
        self._state = state

    def get_subscriptions(self) -> dict[InstrumentToken, SubscriptionMode]:
        """Return a snapshot of all active subscriptions (test helper)."""
        return dict(self._subscriptions)
