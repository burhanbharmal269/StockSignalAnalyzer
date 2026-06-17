"""InMemoryEventBus — synchronous in-process adapter for unit tests.

Reference: docs/11_EVENT_BUS_ARCHITECTURE.md §Phase 1 Implementation Constraints
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator

from core.domain.events.base import DomainEvent
from core.domain.interfaces.i_event_bus import EventHandler, IEventBus


class InMemoryEventBus(IEventBus):
    """In-process event bus with no external dependencies.

    All events are dispatched synchronously within the same async task.
    No delivery guarantees — events are lost on process restart.
    Use ONLY in unit tests or local development.
    """

    def __init__(self) -> None:
        # topic → list of handlers (consumer_group+consumer_name ignored in-memory)
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = defaultdict(list)
        # All published events in insertion order — used by replay().
        self._published: list[tuple[str, DomainEvent]] = []

    async def publish(self, event: DomainEvent) -> None:
        topic = event.event_type
        self._published.append((topic, event))
        for handler in self._handlers.get(type(event), []):
            await handler(event)

    async def subscribe(
        self,
        event_type: type[DomainEvent],
        handler: EventHandler,
        consumer_group: str,
        consumer_name: str,
    ) -> None:
        self._handlers[event_type].append(handler)

    async def replay(
        self,
        event_type: type[DomainEvent],
        from_id: str,
        to_id: str,
    ) -> AsyncIterator[DomainEvent]:
        # In-memory replay ignores stream IDs; yields all matching events.
        for _topic, event in self._published:
            if type(event) is event_type:
                yield event

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def published_events(self, event_type: type[DomainEvent] | None = None) -> list[DomainEvent]:
        """Return all published events, optionally filtered by type."""
        events = [e for _, e in self._published]
        if event_type is not None:
            events = [e for e in events if type(e) is event_type]
        return events

    def clear(self) -> None:
        """Reset all state — call between test cases."""
        self._published.clear()
        self._handlers.clear()
