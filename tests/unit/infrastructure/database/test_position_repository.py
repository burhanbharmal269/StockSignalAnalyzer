"""Unit tests for SqlAlchemyPositionRepository using SQLite in-memory."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.position import Position
from core.domain.enums.position_state import PositionState
from core.domain.enums.signal_type import SignalType
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.database.repositories.position_repository import (
    SqlAlchemyPositionRepository,
)


def _open_position(ticker: str = "NIFTY") -> Position:
    return Position.open(
        symbol=Symbol(ticker),
        direction=SignalType.LONG,
        quantity=50,
        entry_price=Price("19500"),
    )


class TestPositionRepository:
    async def test_save_and_get_by_id(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyPositionRepository(session_factory)
        pos = _open_position()
        await repo.save(pos)
        loaded = await repo.get_by_id(pos.position_id)
        assert loaded is not None
        assert loaded.position_id == pos.position_id
        assert loaded.state == PositionState.OPEN

    async def test_get_by_id_missing_returns_none(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyPositionRepository(session_factory)
        assert await repo.get_by_id(uuid.uuid4()) is None

    async def test_get_open_positions(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyPositionRepository(session_factory)
        p_open = _open_position("NIFTY")
        p_closed = _open_position("BANKNIFTY")
        p_closed.close(Price("19600"), 50)
        await repo.save(p_open)
        await repo.save(p_closed)
        open_positions = await repo.get_open_positions()
        ids = {p.position_id for p in open_positions}
        assert p_open.position_id in ids
        assert p_closed.position_id not in ids

    async def test_save_updates_on_close(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyPositionRepository(session_factory)
        pos = _open_position()
        await repo.save(pos)
        pos.close(Price("19700"), 50)
        await repo.save(pos)
        loaded = await repo.get_by_id(pos.position_id)
        assert loaded is not None
        assert loaded.state == PositionState.CLOSED
        assert loaded.realized_pnl == Price("200") * 50

    async def test_get_by_symbol(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyPositionRepository(session_factory)
        nifty = _open_position("NIFTY")
        bank = _open_position("BANKNIFTY")
        await repo.save(nifty)
        await repo.save(bank)
        results = await repo.get_by_symbol(Symbol("NIFTY"))
        assert len(results) == 1
        assert results[0].position_id == nifty.position_id
