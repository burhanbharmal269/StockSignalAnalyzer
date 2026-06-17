"""Unit tests for the base DomainEvent."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from core.domain.events.base import DomainEvent


@dataclass(frozen=True)
class _TestEvent(DomainEvent):
    """Concrete event used only in these tests."""

    payload: str = ""


class TestDomainEventDefaults:
    def test_event_id_is_uuid(self) -> None:
        event = _TestEvent()
        assert isinstance(event.event_id, uuid.UUID)

    def test_each_event_gets_unique_id(self) -> None:
        a = _TestEvent()
        b = _TestEvent()
        assert a.event_id != b.event_id

    def test_occurred_at_is_utc(self) -> None:
        event = _TestEvent()
        assert event.occurred_at.tzinfo is UTC

    def test_occurred_at_is_recent(self) -> None:
        before = datetime.now(UTC)
        event = _TestEvent()
        after = datetime.now(UTC)
        assert before <= event.occurred_at <= after

    def test_event_type_returns_class_name(self) -> None:
        event = _TestEvent()
        assert event.event_type == "_TestEvent"

    def test_default_correlation_id_is_empty_string(self) -> None:
        event = _TestEvent()
        assert event.correlation_id == ""

    def test_correlation_id_can_be_set(self) -> None:
        event = _TestEvent(correlation_id="req-abc-123")
        assert event.correlation_id == "req-abc-123"

    def test_event_is_immutable(self) -> None:
        event = _TestEvent()
        with pytest.raises((AttributeError, TypeError)):
            event.payload = "changed"  # type: ignore[misc]
