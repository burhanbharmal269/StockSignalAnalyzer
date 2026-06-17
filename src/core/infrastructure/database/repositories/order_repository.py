"""SQLAlchemy implementation of IOrderRepository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.order import Order
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.order_state import OrderState
from core.domain.enums.order_type import OrderType
from core.domain.enums.position_state import PositionState
from core.domain.enums.product_type import ProductType
from core.domain.enums.trading_mode import TradingMode
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.interfaces.i_order_repository import IOrderRepository
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.database.models.order_models import OrderOrm


def _to_orm(order: Order) -> OrderOrm:
    return OrderOrm(
        order_id=order.order_id,
        signal_id=order.signal_id,
        instrument_token=order.instrument_token,
        tradingsymbol=order.tradingsymbol,
        ticker=order.symbol.ticker,
        exchange=order.symbol.exchange,
        underlying=order.tradingsymbol.split("-")[0] if "-" in order.tradingsymbol else order.symbol.ticker,
        transaction_type=order.transaction_type.value,
        order_type=order.order_type.value,
        product=order.product.value,
        quantity=order.quantity,
        lots=order.lots,
        limit_price=order.limit_price.value if order.limit_price else None,
        trigger_price=order.trigger_price.value if order.trigger_price else None,
        validity=order.validity.value,
        risk_decision_id=order.risk_decision_id,
        broker_order_id=order.broker_order_id,
        state=order.state.value,
        rejection_reason=order.rejection_reason,
        trading_mode=order.trading_mode.value,
        filled_quantity=order.filled_quantity,
        average_fill_price=(
            order.average_fill_price.value if order.average_fill_price else None
        ),
        parent_position_id=order.parent_position_id,
        risk_profile_id=order.risk_profile_id,
        allocation_id=order.allocation_id,
        portfolio_id=order.portfolio_id,
        capital_source_mode=order.capital_source_mode.value if order.capital_source_mode else None,
        effective_capital=order.effective_capital,
        effective_margin=order.effective_margin,
        created_at=order.created_at,
        updated_at=order.updated_at,
        submitted_at=order.submitted_at,
        filled_at=order.filled_at,
        cancelled_at=order.cancelled_at,
    )


def _to_domain(row: OrderOrm) -> Order:
    return Order(
        order_id=row.order_id,
        signal_id=row.signal_id,
        symbol=Symbol(row.ticker, row.exchange),
        quantity=row.quantity,
        limit_price=Price(row.limit_price) if row.limit_price is not None else None,
        risk_decision_id=row.risk_decision_id,
        instrument_token=row.instrument_token,
        tradingsymbol=row.tradingsymbol,
        transaction_type=TransactionType(row.transaction_type),
        order_type=OrderType(row.order_type),
        product=ProductType(row.product),
        lots=row.lots,
        trigger_price=Price(row.trigger_price) if row.trigger_price is not None else None,
        validity=Validity(row.validity),
        trading_mode=TradingMode(row.trading_mode),
        parent_position_id=row.parent_position_id,
        state=OrderState(row.state),
        broker_order_id=row.broker_order_id,
        filled_quantity=row.filled_quantity,
        average_fill_price=(
            Price(row.average_fill_price) if row.average_fill_price is not None else None
        ),
        rejection_reason=row.rejection_reason,
        risk_profile_id=row.risk_profile_id,
        allocation_id=row.allocation_id,
        portfolio_id=row.portfolio_id,
        capital_source_mode=CapitalSourceMode(row.capital_source_mode) if row.capital_source_mode else None,
        effective_capital=row.effective_capital,
        effective_margin=row.effective_margin,
        created_at=row.created_at,
        updated_at=row.updated_at,
        submitted_at=row.submitted_at,
        filled_at=row.filled_at,
        cancelled_at=row.cancelled_at,
    )


class SqlAlchemyOrderRepository(IOrderRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, order: Order) -> None:
        async with self._session_factory() as session:
            existing = await session.get(OrderOrm, order.order_id)
            if existing is None:
                session.add(_to_orm(order))
            else:
                orm = _to_orm(order)
                existing.state = orm.state
                existing.broker_order_id = orm.broker_order_id
                existing.filled_quantity = orm.filled_quantity
                existing.average_fill_price = orm.average_fill_price
                existing.rejection_reason = orm.rejection_reason
                existing.updated_at = orm.updated_at
                existing.submitted_at = orm.submitted_at
                existing.filled_at = orm.filled_at
                existing.cancelled_at = orm.cancelled_at
                existing.parent_position_id = orm.parent_position_id
                existing.stop_loss_price = getattr(orm, "trigger_price", None)
            await session.commit()

    async def get_by_id(self, order_id: UUID) -> Order | None:
        async with self._session_factory() as session:
            row = await session.get(OrderOrm, order_id)
            return _to_domain(row) if row else None

    async def get_by_signal_id(self, signal_id: UUID) -> list[Order]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderOrm).where(OrderOrm.signal_id == signal_id)
            )
            return [_to_domain(r) for r in result.scalars()]

    async def get_by_broker_order_id(self, broker_order_id: str) -> Order | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderOrm).where(OrderOrm.broker_order_id == broker_order_id)
            )
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def get_by_state(self, state: OrderState) -> list[Order]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderOrm).where(OrderOrm.state == state.value)
            )
            return [_to_domain(r) for r in result.scalars()]

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Order]:
        from sqlalchemy import desc

        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderOrm)
                .order_by(desc(OrderOrm.created_at))
                .limit(limit)
                .offset(offset)
            )
            return [_to_domain(r) for r in result.scalars()]
