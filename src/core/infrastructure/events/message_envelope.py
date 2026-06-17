"""MessageEnvelope — wire format for every event on every Redis stream.

Reference: docs/11_EVENT_BUS_ARCHITECTURE.md §Message Envelope Schema
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from types import UnionType
from typing import Any, get_args, get_origin, get_type_hints

from core.domain.events.base import DomainEvent


@dataclass
class MessageEnvelope:
    """Transport envelope that wraps a DomainEvent for Redis Streams.

    Producers serialize to this before XADD; consumers deserialize after XREAD.
    The envelope is what travels on the wire — the domain layer never sees it.
    """

    event_id: str
    event_type: str
    event_version: str
    topic: str
    source: str
    correlation_id: str
    timestamp: str
    payload: dict[str, Any]

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_redis_fields(self) -> dict[str, str]:
        """Convert to flat string dict for XADD (Redis Streams require str values)."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "topic": self.topic,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "payload": json.dumps(self.payload),
        }

    @classmethod
    def from_redis_fields(cls, fields: dict[str, str | bytes]) -> MessageEnvelope:
        """Reconstruct envelope from XREAD response fields."""
        normalized = {
            _decode_if_bytes(key): _decode_if_bytes(value)
            for key, value in fields.items()
        }
        return cls(
            event_id=normalized["event_id"],
            event_type=normalized["event_type"],
            event_version=normalized["event_version"],
            topic=normalized["topic"],
            source=normalized["source"],
            correlation_id=normalized["correlation_id"],
            timestamp=normalized["timestamp"],
            payload=json.loads(normalized["payload"]),
        )

    # -------------------------------------------------------------------------
    # Factory
    # -------------------------------------------------------------------------

    @classmethod
    def wrap(
        cls,
        event: DomainEvent,
        topic: str,
        source: str,
        version: str = "1.0.0",
    ) -> MessageEnvelope:
        """Create an envelope from a domain event."""
        return cls(
            event_id=str(event.event_id),
            event_type=event.event_type,
            event_version=version,
            topic=topic,
            source=source,
            correlation_id=event.correlation_id,
            timestamp=event.occurred_at.isoformat(),
            payload=_extract_payload(event),
        )


def _extract_payload(event: DomainEvent) -> dict[str, Any]:
    """Serialize event dataclass fields (excluding base fields) to a plain dict."""
    base_field_names = {f.name for f in dataclasses.fields(DomainEvent)}
    result: dict[str, Any] = {}
    for f in dataclasses.fields(event):
        if f.name in base_field_names:
            continue
        result[f.name] = _to_json_value(getattr(event, f.name))
    return result


def reconstruct_event(
    event_type: type[DomainEvent],
    envelope: MessageEnvelope,
) -> DomainEvent:
    """Rebuild a typed domain event from a transport envelope."""
    type_hints = get_type_hints(event_type)
    kwargs: dict[str, Any] = {
        "event_id": uuid.UUID(envelope.event_id),
        "occurred_at": datetime.fromisoformat(envelope.timestamp),
        "correlation_id": envelope.correlation_id,
    }
    for field in dataclasses.fields(event_type):
        if field.name in kwargs:
            continue
        if field.name not in envelope.payload:
            continue
        expected_type = type_hints.get(field.name, field.type)
        kwargs[field.name] = _from_json_value(envelope.payload[field.name], expected_type)
    return event_type(**kwargs)


def _to_json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value):
        return {
            field.name: _to_json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    return value


def _from_json_value(value: Any, expected_type: Any) -> Any:
    if value is None:
        return None

    origin = get_origin(expected_type)
    args = get_args(expected_type)
    if origin in {UnionType, None} and args:
        return _from_union_value(value, args)
    if origin is list:
        item_type = args[0] if args else Any
        return [_from_json_value(item, item_type) for item in value]
    if origin is tuple:
        item_type = args[0] if args else Any
        return tuple(_from_json_value(item, item_type) for item in value)

    if expected_type is uuid.UUID:
        return uuid.UUID(str(value))
    if expected_type is datetime:
        return datetime.fromisoformat(str(value))
    if expected_type is date:
        return date.fromisoformat(str(value))
    if expected_type is Decimal:
        return Decimal(str(value))
    if isinstance(expected_type, type) and issubclass(expected_type, Enum):
        return expected_type(value)
    return value


def _from_union_value(value: Any, union_args: tuple[Any, ...]) -> Any:
    non_none_args = [arg for arg in union_args if arg is not type(None)]
    if not non_none_args:
        return value
    last_error: Exception | None = None
    for candidate in non_none_args:
        try:
            return _from_json_value(value, candidate)
        except (TypeError, ValueError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return value


def _decode_if_bytes(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value
