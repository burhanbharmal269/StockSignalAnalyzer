"""Unit tests for SqlAlchemyBrokerSessionRepository (SQLite in-memory)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.broker_session import BrokerSession
from core.infrastructure.database.repositories.broker_session_repository import (
    SqlAlchemyBrokerSessionRepository,
)


def _make_session(
    broker_name: str = "kite",
    is_active: bool = True,
    expires_in_hours: int = 8,
) -> BrokerSession:
    return BrokerSession.create(
        broker_name=broker_name,
        api_key="test_api_key",
        encrypted_access_token="enc_token_xyz",
        expires_at=datetime.now(UTC) + timedelta(hours=expires_in_hours),
    )


@pytest.fixture
def repo(session_factory: async_sessionmaker[AsyncSession]) -> SqlAlchemyBrokerSessionRepository:
    return SqlAlchemyBrokerSessionRepository(session_factory=session_factory)


class TestSave:
    async def test_save_persists_session(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        session = _make_session()
        await repo.save(session)
        retrieved = await repo.get_by_id(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    async def test_save_preserves_broker_name(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        session = _make_session(broker_name="kite")
        await repo.save(session)
        retrieved = await repo.get_by_id(session.session_id)
        assert retrieved.broker_name == "kite"

    async def test_save_preserves_encrypted_token(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        session = _make_session()
        await repo.save(session)
        retrieved = await repo.get_by_id(session.session_id)
        assert retrieved.encrypted_access_token == "enc_token_xyz"

    async def test_save_update_changes_token(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        session = _make_session()
        await repo.save(session)
        session.encrypted_access_token = "updated_token"  # type: ignore[misc]
        await repo.save(session)
        retrieved = await repo.get_by_id(session.session_id)
        assert retrieved.encrypted_access_token == "updated_token"

    async def test_save_multiple_sessions(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        s1 = _make_session()
        s2 = _make_session()
        await repo.save(s1)
        await repo.save(s2)
        r1 = await repo.get_by_id(s1.session_id)
        r2 = await repo.get_by_id(s2.session_id)
        assert r1 is not None
        assert r2 is not None
        assert r1.session_id != r2.session_id


class TestGetActive:
    async def test_get_active_returns_active_session(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        session = _make_session(broker_name="kite")
        await repo.save(session)
        active = await repo.get_active("kite")
        assert active is not None
        assert active.session_id == session.session_id

    async def test_get_active_returns_none_when_no_session(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        result = await repo.get_active("kite")
        assert result is None

    async def test_get_active_returns_none_after_deactivation(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        session = _make_session(broker_name="kite")
        await repo.save(session)
        await repo.deactivate_all("kite")
        result = await repo.get_active("kite")
        assert result is None

    async def test_get_active_filters_by_broker_name(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        kite_session = _make_session(broker_name="kite")
        paper_session = _make_session(broker_name="paper")
        await repo.save(kite_session)
        await repo.save(paper_session)
        active_kite = await repo.get_active("kite")
        active_paper = await repo.get_active("paper")
        assert active_kite.session_id == kite_session.session_id
        assert active_paper.session_id == paper_session.session_id


class TestGetById:
    async def test_get_by_id_returns_session(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        session = _make_session()
        await repo.save(session)
        retrieved = await repo.get_by_id(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    async def test_get_by_id_returns_none_for_unknown_id(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        result = await repo.get_by_id(uuid.uuid4())
        assert result is None


class TestDeactivateAll:
    async def test_deactivate_all_disables_active_session(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        session = _make_session(broker_name="kite")
        await repo.save(session)
        await repo.deactivate_all("kite")
        retrieved = await repo.get_by_id(session.session_id)
        assert retrieved.is_active is False

    async def test_deactivate_all_is_noop_when_no_sessions(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        await repo.deactivate_all("kite")

    async def test_deactivate_all_only_affects_named_broker(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        kite = _make_session(broker_name="kite")
        paper = _make_session(broker_name="paper")
        await repo.save(kite)
        await repo.save(paper)
        await repo.deactivate_all("kite")
        kite_retrieved = await repo.get_by_id(kite.session_id)
        paper_retrieved = await repo.get_by_id(paper.session_id)
        assert kite_retrieved.is_active is False
        assert paper_retrieved.is_active is True

    async def test_deactivate_all_deactivates_multiple_sessions(
        self, repo: SqlAlchemyBrokerSessionRepository
    ) -> None:
        s1 = _make_session(broker_name="kite")
        s2 = _make_session(broker_name="kite")
        await repo.save(s1)
        await repo.save(s2)
        await repo.deactivate_all("kite")
        r1 = await repo.get_by_id(s1.session_id)
        r2 = await repo.get_by_id(s2.session_id)
        assert r1.is_active is False
        assert r2.is_active is False
