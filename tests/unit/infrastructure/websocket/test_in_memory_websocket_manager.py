"""Unit tests for InMemoryWebSocketManager."""

from __future__ import annotations

from decimal import Decimal

from core.domain.enums.connection_state import ConnectionState
from core.domain.enums.subscription_mode import SubscriptionMode
from core.domain.events.tick_received import TickReceivedEvent
from core.infrastructure.events.in_memory_event_bus import InMemoryEventBus
from core.infrastructure.websocket.in_memory_websocket_manager import InMemoryWebSocketManager


class TestInMemoryWebSocketManagerLifecycle:
    async def test_initial_state_disconnected(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        assert manager.get_connection_state() == ConnectionState.DISCONNECTED

    async def test_start_sets_streaming(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        await manager.start()
        assert manager.get_connection_state() == ConnectionState.STREAMING

    async def test_stop_sets_disconnected(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        await manager.start()
        await manager.stop()
        assert manager.get_connection_state() == ConnectionState.DISCONNECTED

    async def test_set_state_helper(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        manager.set_state(ConnectionState.RECONNECTING)
        assert manager.get_connection_state() == ConnectionState.RECONNECTING


class TestInMemoryWebSocketManagerSubscriptions:
    async def test_subscribe_records_tokens(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        await manager.subscribe([256265, 260105], SubscriptionMode.FULL)
        assert manager.get_subscription_count() == 2

    async def test_subscribe_records_mode(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        await manager.subscribe([256265], SubscriptionMode.QUOTE)
        subs = manager.get_subscriptions()
        assert subs[256265] == SubscriptionMode.QUOTE

    async def test_unsubscribe_removes_token(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        await manager.subscribe([1, 2, 3], SubscriptionMode.LTP)
        await manager.unsubscribe([2])
        assert manager.get_subscription_count() == 2
        assert 2 not in manager.get_subscriptions()

    async def test_unsubscribe_nonexistent_is_noop(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        await manager.unsubscribe([99999])  # must not raise
        assert manager.get_subscription_count() == 0


class TestInMemoryWebSocketManagerTicks:
    async def test_inject_tick_publishes_to_bus(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        tick = TickReceivedEvent(
            instrument_token=256265,
            tradingsymbol="NIFTY",
            last_price=Decimal("22000"),
        )
        await manager.inject_tick(tick)
        published = bus.published_events(TickReceivedEvent)
        assert len(published) == 1
        assert published[0] is tick

    async def test_inject_tick_updates_last_tick_time(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        tick = TickReceivedEvent(instrument_token=256265)
        await manager.inject_tick(tick)
        last_time = manager.get_last_tick_time(256265)
        assert last_time is not None
        assert last_time == tick.occurred_at

    async def test_get_last_tick_time_none_before_any_tick(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        assert manager.get_last_tick_time(256265) is None

    async def test_multiple_ticks_update_time(self) -> None:
        bus = InMemoryEventBus()
        manager = InMemoryWebSocketManager(bus)
        tick1 = TickReceivedEvent(instrument_token=256265, last_price=Decimal("100"))
        tick2 = TickReceivedEvent(instrument_token=256265, last_price=Decimal("101"))
        await manager.inject_tick(tick1)
        await manager.inject_tick(tick2)
        assert manager.get_last_tick_time(256265) == tick2.occurred_at
        assert len(bus.published_events(TickReceivedEvent)) == 2
