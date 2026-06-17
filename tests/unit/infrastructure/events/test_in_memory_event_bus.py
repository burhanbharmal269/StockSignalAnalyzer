"""Unit tests for InMemoryEventBus."""

from __future__ import annotations

from dataclasses import dataclass

from core.domain.events.base import DomainEvent
from core.infrastructure.events.in_memory_event_bus import InMemoryEventBus


@dataclass(frozen=True)
class _SignalScoredEvent(DomainEvent):
    signal_id: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class _OrderFilledEvent(DomainEvent):
    order_id: str = ""


class TestInMemoryEventBusPublish:
    async def test_publish_delivers_to_subscriber(self) -> None:
        bus = InMemoryEventBus()
        received: list[DomainEvent] = []

        async def handler(event: DomainEvent) -> None:
            received.append(event)

        await bus.subscribe(_SignalScoredEvent, handler, "group", "consumer-1")
        event = _SignalScoredEvent(signal_id="sig-1", score=82.0)
        await bus.publish(event)
        assert len(received) == 1
        assert received[0] is event

    async def test_publish_only_delivers_to_matching_type(self) -> None:
        bus = InMemoryEventBus()
        scored_received: list[DomainEvent] = []
        filled_received: list[DomainEvent] = []

        async def on_scored(event: DomainEvent) -> None:
            scored_received.append(event)

        async def on_filled(event: DomainEvent) -> None:
            filled_received.append(event)

        await bus.subscribe(_SignalScoredEvent, on_scored, "g", "c1")
        await bus.subscribe(_OrderFilledEvent, on_filled, "g", "c2")

        await bus.publish(_SignalScoredEvent())
        assert len(scored_received) == 1
        assert len(filled_received) == 0

    async def test_multiple_handlers_for_same_type(self) -> None:
        bus = InMemoryEventBus()
        calls: list[str] = []

        async def h1(event: DomainEvent) -> None:
            calls.append("h1")

        async def h2(event: DomainEvent) -> None:
            calls.append("h2")

        await bus.subscribe(_SignalScoredEvent, h1, "g", "c1")
        await bus.subscribe(_SignalScoredEvent, h2, "g", "c2")
        await bus.publish(_SignalScoredEvent())
        assert calls == ["h1", "h2"]

    async def test_no_handlers_no_error(self) -> None:
        bus = InMemoryEventBus()
        await bus.publish(_SignalScoredEvent())  # must not raise

    async def test_published_events_accumulated(self) -> None:
        bus = InMemoryEventBus()
        e1 = _SignalScoredEvent(signal_id="a")
        e2 = _SignalScoredEvent(signal_id="b")
        await bus.publish(e1)
        await bus.publish(e2)
        assert bus.published_events() == [e1, e2]

    async def test_published_events_filtered_by_type(self) -> None:
        bus = InMemoryEventBus()
        await bus.publish(_SignalScoredEvent())
        await bus.publish(_OrderFilledEvent())
        await bus.publish(_SignalScoredEvent())
        scored = bus.published_events(_SignalScoredEvent)
        assert len(scored) == 2
        for e in scored:
            assert isinstance(e, _SignalScoredEvent)


class TestInMemoryEventBusReplay:
    async def test_replay_yields_published_events_of_type(self) -> None:
        bus = InMemoryEventBus()
        await bus.publish(_SignalScoredEvent(signal_id="x"))
        await bus.publish(_OrderFilledEvent(order_id="y"))
        await bus.publish(_SignalScoredEvent(signal_id="z"))

        replayed = [e async for e in bus.replay(_SignalScoredEvent, "0", "+")]
        assert len(replayed) == 2
        assert all(isinstance(e, _SignalScoredEvent) for e in replayed)

    async def test_replay_empty_when_no_matching_events(self) -> None:
        bus = InMemoryEventBus()
        await bus.publish(_OrderFilledEvent())
        replayed = [e async for e in bus.replay(_SignalScoredEvent, "0", "+")]
        assert replayed == []


class TestInMemoryEventBusClear:
    async def test_clear_resets_published_events(self) -> None:
        bus = InMemoryEventBus()
        await bus.publish(_SignalScoredEvent())
        bus.clear()
        assert bus.published_events() == []

    async def test_clear_removes_subscribers(self) -> None:
        bus = InMemoryEventBus()
        received: list[DomainEvent] = []

        async def handler(event: DomainEvent) -> None:
            received.append(event)

        await bus.subscribe(_SignalScoredEvent, handler, "g", "c")
        bus.clear()
        await bus.publish(_SignalScoredEvent())
        assert received == []
