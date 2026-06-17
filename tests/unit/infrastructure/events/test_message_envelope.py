"""Unit tests for MessageEnvelope serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass

from core.domain.events.base import DomainEvent
from core.infrastructure.events.message_envelope import MessageEnvelope


@dataclass(frozen=True)
class _SampleEvent(DomainEvent):
    instrument: str = "NIFTY"
    score: float = 82.5


class TestMessageEnvelopeWrap:
    def test_wrap_sets_event_type(self) -> None:
        event = _SampleEvent()
        env = MessageEnvelope.wrap(event, topic="signal.score.computed", source="scoring-engine")
        assert env.event_type == "_SampleEvent"

    def test_wrap_sets_topic_and_source(self) -> None:
        event = _SampleEvent()
        env = MessageEnvelope.wrap(event, topic="test.topic", source="test-source")
        assert env.topic == "test.topic"
        assert env.source == "test-source"

    def test_wrap_event_id_matches(self) -> None:
        event = _SampleEvent()
        env = MessageEnvelope.wrap(event, topic="t", source="s")
        assert env.event_id == str(event.event_id)

    def test_wrap_correlation_id_propagated(self) -> None:
        event = _SampleEvent(correlation_id="trace-abc")
        env = MessageEnvelope.wrap(event, topic="t", source="s")
        assert env.correlation_id == "trace-abc"

    def test_payload_contains_domain_fields(self) -> None:
        event = _SampleEvent(instrument="BANKNIFTY", score=75.0)
        env = MessageEnvelope.wrap(event, topic="t", source="s")
        assert env.payload["instrument"] == "BANKNIFTY"
        assert env.payload["score"] == 75.0

    def test_payload_excludes_base_fields(self) -> None:
        event = _SampleEvent()
        env = MessageEnvelope.wrap(event, topic="t", source="s")
        assert "event_id" not in env.payload
        assert "occurred_at" not in env.payload
        assert "correlation_id" not in env.payload


class TestRedisRoundTrip:
    def test_to_and_from_redis_fields(self) -> None:
        event = _SampleEvent(instrument="NIFTY", score=82.5)
        env = MessageEnvelope.wrap(event, topic="signal.score", source="test")
        fields = env.to_redis_fields()
        restored = MessageEnvelope.from_redis_fields(fields)
        assert restored.event_id == env.event_id
        assert restored.event_type == env.event_type
        assert restored.topic == env.topic
        assert restored.source == env.source
        assert restored.correlation_id == env.correlation_id
        assert restored.payload == env.payload

    def test_redis_fields_are_all_strings(self) -> None:
        event = _SampleEvent()
        fields = MessageEnvelope.wrap(event, topic="t", source="s").to_redis_fields()
        for key, value in fields.items():
            assert isinstance(value, str), f"Field {key!r} is {type(value)}, expected str"

    def test_payload_json_roundtrip(self) -> None:
        event = _SampleEvent(instrument="NIFTY", score=90.0)
        fields = MessageEnvelope.wrap(event, topic="t", source="s").to_redis_fields()
        payload = json.loads(fields["payload"])
        assert payload["score"] == 90.0
