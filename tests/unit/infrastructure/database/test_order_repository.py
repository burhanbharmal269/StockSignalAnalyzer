"""Unit tests for SqlAlchemyOrderRepository using SQLite in-memory."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.order import Order
from core.domain.enums.order_state import OrderState
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.database.repositories.order_repository import SqlAlchemyOrderRepository


def _make_order(signal_id: uuid.UUID | None = None) -> Order:
    return Order.create(
        signal_id=signal_id or uuid.uuid4(),
        symbol=Symbol("NIFTY"),
        quantity=50,
        limit_price=Price("19500"),
    )


class TestOrderRepository:
    async def test_save_and_get_by_id(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyOrderRepository(session_factory)
        order = _make_order()
        await repo.save(order)
        loaded = await repo.get_by_id(order.order_id)
        assert loaded is not None
        assert loaded.order_id == order.order_id
        assert loaded.quantity == 50
        assert loaded.state == OrderState.PENDING

    async def test_get_by_id_missing_returns_none(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyOrderRepository(session_factory)
        assert await repo.get_by_id(uuid.uuid4()) is None

    async def test_get_by_signal_id(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyOrderRepository(session_factory)
        sig_id = uuid.uuid4()
        o1 = _make_order(sig_id)
        o2 = _make_order(sig_id)
        o3 = _make_order()  # different signal
        await repo.save(o1)
        await repo.save(o2)
        await repo.save(o3)
        results = await repo.get_by_signal_id(sig_id)
        ids = {r.order_id for r in results}
        assert o1.order_id in ids
        assert o2.order_id in ids
        assert o3.order_id not in ids

    async def test_save_updates_state(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyOrderRepository(session_factory)
        order = _make_order()
        await repo.save(order)
        order.start_submission()
        order.confirm_submitted("broker_abc")
        await repo.save(order)
        loaded = await repo.get_by_id(order.order_id)
        assert loaded is not None
        assert loaded.state == OrderState.SUBMITTED
        assert loaded.broker_order_id == "broker_abc"

    async def test_get_by_broker_order_id(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyOrderRepository(session_factory)
        order = _make_order()
        order.start_submission()
        order.confirm_submitted("BROKER-XYZ")
        await repo.save(order)
        found = await repo.get_by_broker_order_id("BROKER-XYZ")
        assert found is not None
        assert found.order_id == order.order_id

    async def test_get_by_state(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyOrderRepository(session_factory)
        pending = _make_order()
        submitted = _make_order()
        submitted.start_submission()
        submitted.confirm_submitted("B1")
        await repo.save(pending)
        await repo.save(submitted)
        results = await repo.get_by_state(OrderState.PENDING)
        assert len(results) == 1
        assert results[0].order_id == pending.order_id
