"""IEventBus — domain port for the event bus.

Infrastructure provides the adapter (RedisStreamEventBus, InMemoryEventBus).
The domain and application layers depend only on this interface.

Dependency direction: infrastructure → domain/interfaces (correct)
                      application  → domain/interfaces (correct)
                      domain       → nothing (correct)

Reference: docs/11_EVENT_BUS_ARCHITECTURE.md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from core.domain.events.base import DomainEvent

EventHandler = Callable[[DomainEvent], Coroutine[Any, Any, None]]


class IEventBus(ABC):
    """Async event bus port.

    All implementations must honour at-least-once delivery semantics.
    Consumers must be idempotent.
    """

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        """Publish a domain event to the bus.

        Args:
            event: The immutable domain event to publish.
        """

    @abstractmethod
    async def subscribe(
        self,
        event_type: type[DomainEvent],
        handler: EventHandler,
        consumer_group: str,
        consumer_name: str,
    ) -> None:
        """Register a handler for a specific event type.

        Args:
            event_type:     The domain event class to subscribe to.
            handler:        Async callable invoked for each message.
            consumer_group: Logical group name (e.g. 'oms', 'risk_engine').
            consumer_name:  Unique name within the group for this process.
        """

    @abstractmethod
    async def replay(
        self,
        event_type: type[DomainEvent],
        from_id: str,
        to_id: str,
    ) -> AsyncIterator[DomainEvent]:
        """Replay historical events between two stream IDs.

        Args:
            event_type: The event class whose stream to replay.
            from_id:    Inclusive start stream ID (e.g. '0-0').
            to_id:      Inclusive end stream ID (e.g. '+').

        Yields:
            Domain events in chronological order.
        """
