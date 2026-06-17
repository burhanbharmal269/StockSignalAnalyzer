"""Unit tests for BrokerSession entity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.domain.entities.broker_session import BrokerSession


def _make_session(
    expires_at: datetime | None = None,
    is_active: bool = True,
) -> BrokerSession:
    return BrokerSession.create(
        broker_name="kite",
        api_key="test_key",
        encrypted_access_token="encrypted_token_abc",
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=8),
    )


class TestBrokerSessionCreate:
    def test_create_sets_broker_name(self) -> None:
        s = _make_session()
        assert s.broker_name == "kite"

    def test_create_sets_api_key(self) -> None:
        s = _make_session()
        assert s.api_key == "test_key"

    def test_create_sets_encrypted_token(self) -> None:
        s = _make_session()
        assert s.encrypted_access_token == "encrypted_token_abc"

    def test_create_is_active_by_default(self) -> None:
        s = _make_session()
        assert s.is_active is True

    def test_create_assigns_unique_session_ids(self) -> None:
        s1 = _make_session()
        s2 = _make_session()
        assert s1.session_id != s2.session_id

    def test_created_at_is_utc_aware(self) -> None:
        s = _make_session()
        assert s.created_at.tzinfo is not None


class TestBrokerSessionIsExpired:
    def test_not_expired_when_future_expiry(self) -> None:
        s = _make_session(expires_at=datetime.now(UTC) + timedelta(hours=1))
        assert s.is_expired() is False

    def test_expired_when_past_expiry(self) -> None:
        s = _make_session(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        assert s.is_expired() is True

    def test_expired_at_exact_expiry_time(self) -> None:
        past = datetime.now(UTC) - timedelta(microseconds=1)
        s = _make_session(expires_at=past)
        assert s.is_expired() is True


class TestBrokerSessionDeactivate:
    def test_deactivate_sets_is_active_false(self) -> None:
        s = _make_session()
        s.deactivate()
        assert s.is_active is False

    def test_deactivate_idempotent(self) -> None:
        s = _make_session()
        s.deactivate()
        s.deactivate()
        assert s.is_active is False

    def test_active_session_is_active(self) -> None:
        s = _make_session()
        assert s.is_active is True
