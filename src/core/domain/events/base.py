"""Base domain event definition.

Domain events are immutable facts — something that happened in the domain.
They are pure Python dataclasses with no framework imports.

The event bus (infrastructure) transports these events; it does not define
them. Producers and consumers depend only on these definitions.

Reference: docs/11_EVENT_BUS_ARCHITECTURE.md (Design Principles)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events.

    Attributes:
        event_id:   Unique identifier for this specific event instance.
        occurred_at: UTC timestamp when the event was raised.
        correlation_id: Propagated trace ID for request correlation.
    """

    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = field(default="")

    @property
    def event_type(self) -> str:
        """Fully qualified event type name used as the stream topic key."""
        return type(self).__name__
