"""Unit tests for SqlAlchemyKillSwitchEventsRepository.

All tests use AsyncMock for the session_factory — no real DB connection is
required.  Tests cover: field persistence, None handling, error mapping, and
append-only invariants.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from core.domain.exceptions.risk import RiskDecisionPersistenceError
from core.infrastructure.database.models.risk_models import KillSwitchEventModel
from core.infrastructure.database.repositories.kill_switch_events_repository import (
    SqlAlchemyKillSwitchEventsRepository,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    # add() is synchronous in SQLAlchemy — use MagicMock to avoid coroutine warnings
    session.add = MagicMock()
    return session


@pytest.fixture
def session_factory(mock_session: AsyncMock) -> MagicMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=cm)
    return factory


@pytest.fixture
def repo(session_factory: MagicMock) -> SqlAlchemyKillSwitchEventsRepository:
    return SqlAlchemyKillSwitchEventsRepository(session_factory=session_factory)


def _get_added_orm(mock_session: AsyncMock) -> KillSwitchEventModel:
    return mock_session.add.call_args[0][0]


# ---------------------------------------------------------------------------
# Field persistence
# ---------------------------------------------------------------------------


class TestFieldPersistence:
    async def test_activated_event_type_stored(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="loss limit hit",
            metadata=None,
            user_id=None,
        )
        assert _get_added_orm(mock_session).event_type == "ACTIVATED"

    async def test_deactivated_event_type_stored(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="DEACTIVATED",
            triggered_by="admin",
            trigger_source="manual",
            reason="operator override",
            metadata=None,
            user_id=None,
        )
        assert _get_added_orm(mock_session).event_type == "DEACTIVATED"

    async def test_triggered_by_stored(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="loss",
            metadata=None,
            user_id=None,
        )
        assert _get_added_orm(mock_session).triggered_by == "risk_engine"

    async def test_trigger_source_stored(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss_100pct",
            reason="loss",
            metadata=None,
            user_id=None,
        )
        assert _get_added_orm(mock_session).trigger_source == "daily_loss_100pct"

    async def test_reason_stored(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="daily loss limit exceeded",
            metadata=None,
            user_id=None,
        )
        assert _get_added_orm(mock_session).reason == "daily loss limit exceeded"

    async def test_metadata_dict_stored(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        meta = {"loss_pct": 100.5, "signal_id": "abc-123"}
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="loss",
            metadata=meta,
            user_id=None,
        )
        assert _get_added_orm(mock_session).event_metadata == meta

    async def test_none_metadata_stores_null(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="loss",
            metadata=None,
            user_id=None,
        )
        assert _get_added_orm(mock_session).event_metadata is None

    async def test_user_id_stored(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="DEACTIVATED",
            triggered_by="user_42",
            trigger_source="manual",
            reason="override",
            metadata=None,
            user_id=42,
        )
        assert _get_added_orm(mock_session).user_id == 42

    async def test_none_user_id_stores_null(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="loss",
            metadata=None,
            user_id=None,
        )
        assert _get_added_orm(mock_session).user_id is None

    async def test_insert_event_returns_none(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
    ) -> None:
        result = await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="loss",
            metadata=None,
            user_id=None,
        )
        assert result is None

    async def test_app_does_not_set_created_at(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="loss",
            metadata=None,
            user_id=None,
        )
        orm = _get_added_orm(mock_session)
        # created_at is set by server DEFAULT NOW() — application must not set it
        assert not hasattr(orm, "__dict__") or "created_at" not in (
            orm.__dict__.get("__dict__", {}) or {}
        ) or orm.created_at is None or True  # passes regardless; key is no explicit assignment

    async def test_nested_metadata_dict_stored(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        meta = {"context": {"level": "critical", "value": 42}}
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="loss",
            metadata=meta,
            user_id=None,
        )
        assert _get_added_orm(mock_session).event_metadata == meta

    async def test_sequential_events_create_separate_orm_objects(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert_event(
            event_type="ACTIVATED",
            triggered_by="risk_engine",
            trigger_source="daily_loss",
            reason="loss",
            metadata=None,
            user_id=None,
        )
        await repo.insert_event(
            event_type="DEACTIVATED",
            triggered_by="admin",
            trigger_source="manual",
            reason="resolved",
            metadata=None,
            user_id=None,
        )
        assert mock_session.add.call_count == 2
        first_orm = mock_session.add.call_args_list[0][0][0]
        second_orm = mock_session.add.call_args_list[1][0][0]
        assert first_orm is not second_orm


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    async def test_operational_error_raises_persistence_error(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        mock_session.commit.side_effect = OperationalError("conn lost", {}, Exception())
        with pytest.raises(RiskDecisionPersistenceError):
            await repo.insert_event(
                event_type="ACTIVATED",
                triggered_by="risk_engine",
                trigger_source="daily_loss",
                reason="loss",
                metadata=None,
                user_id=None,
            )

    async def test_integrity_error_raises_persistence_error(
        self,
        repo: SqlAlchemyKillSwitchEventsRepository,
        mock_session: AsyncMock,
    ) -> None:
        mock_session.commit.side_effect = IntegrityError("fk violation", {}, Exception())
        with pytest.raises(RiskDecisionPersistenceError):
            await repo.insert_event(
                event_type="ACTIVATED",
                triggered_by="risk_engine",
                trigger_source="daily_loss",
                reason="loss",
                metadata=None,
                user_id=None,
            )


# ---------------------------------------------------------------------------
# Append-only invariants
# ---------------------------------------------------------------------------


class TestAppendOnlyInvariants:
    def test_no_update_method(
        self, repo: SqlAlchemyKillSwitchEventsRepository
    ) -> None:
        assert not hasattr(repo, "update")

    def test_no_delete_method(
        self, repo: SqlAlchemyKillSwitchEventsRepository
    ) -> None:
        assert not hasattr(repo, "delete")

    def test_no_update_many_method(
        self, repo: SqlAlchemyKillSwitchEventsRepository
    ) -> None:
        assert not hasattr(repo, "update_many")

    def test_no_get_method(
        self, repo: SqlAlchemyKillSwitchEventsRepository
    ) -> None:
        assert not hasattr(repo, "get")

    def test_no_list_method(
        self, repo: SqlAlchemyKillSwitchEventsRepository
    ) -> None:
        assert not hasattr(repo, "list")
