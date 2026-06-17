"""SQLAlchemy implementation of IPositionRepository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.position import Position
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.position_state import PositionState
from core.domain.enums.signal_type import SignalType
from core.domain.enums.trading_mode import TradingMode
from core.domain.interfaces.i_position_repository import IPositionRepository
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.database.models.position_models import PositionOrm

_OPEN_STATES = {PositionState.OPEN.value, PositionState.PARTIALLY_CLOSED.value}


def _to_orm(position: Position) -> PositionOrm:
    return PositionOrm(
        position_id=position.position_id,
        signal_id=position.signal_id,
        order_id=position.order_id,
        instrument_token=position.instrument_token,
        tradingsymbol=position.symbol.ticker,
        ticker=position.symbol.ticker,
        exchange=position.symbol.exchange,
        underlying=position.symbol.ticker,
        direction=position.direction.value,
        quantity=position.quantity,
        lots=position.lots,
        entry_price=position.entry_price.value,
        current_price=position.current_price.value,
        stop_loss_price=position.stop_loss_price.value if position.stop_loss_price else None,
        target_1_price=position.target_1_price.value if position.target_1_price else None,
        target_2_price=position.target_2_price.value if position.target_2_price else None,
        realized_pnl=position.realized_pnl.value,
        current_mtm_pnl=position.current_mtm_pnl.value,
        state=position.state.value,
        outcome=position.outcome.value if position.outcome else None,
        trading_mode=position.trading_mode.value,
        regime_at_open=position.regime_at_open,
        stop_order_id=position.stop_order_id,
        target_order_id=position.target_order_id,
        risk_profile_id=position.risk_profile_id,
        allocation_id=position.allocation_id,
        portfolio_id=position.portfolio_id,
        capital_source_mode=position.capital_source_mode.value if position.capital_source_mode else None,
        effective_capital=position.effective_capital,
        effective_margin=position.effective_margin,
        opened_at=position.opened_at,
        closed_at=position.closed_at,
    )


def _to_domain(row: PositionOrm) -> Position:
    return Position(
        position_id=row.position_id,
        symbol=Symbol(row.ticker, row.exchange),
        direction=SignalType(row.direction),
        quantity=row.quantity,
        entry_price=Price(row.entry_price),
        current_price=Price(row.current_price),
        signal_id=row.signal_id,
        order_id=row.order_id,
        instrument_token=row.instrument_token,
        lots=row.lots,
        stop_loss_price=Price(row.stop_loss_price) if row.stop_loss_price else None,
        target_1_price=Price(row.target_1_price) if row.target_1_price else None,
        target_2_price=Price(row.target_2_price) if row.target_2_price else None,
        realized_pnl=Price(row.realized_pnl),
        current_mtm_pnl=Price(row.current_mtm_pnl),
        state=PositionState(row.state),
        outcome=PositionOutcome(row.outcome) if row.outcome else None,
        trading_mode=TradingMode(row.trading_mode),
        regime_at_open=row.regime_at_open,
        stop_order_id=row.stop_order_id,
        target_order_id=row.target_order_id,
        risk_profile_id=row.risk_profile_id,
        allocation_id=row.allocation_id,
        portfolio_id=row.portfolio_id,
        capital_source_mode=CapitalSourceMode(row.capital_source_mode) if row.capital_source_mode else None,
        effective_capital=row.effective_capital,
        effective_margin=row.effective_margin,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
    )


class SqlAlchemyPositionRepository(IPositionRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, position: Position) -> None:
        async with self._session_factory() as session:
            existing = await session.get(PositionOrm, position.position_id)
            if existing is None:
                session.add(_to_orm(position))
            else:
                orm = _to_orm(position)
                existing.state = orm.state
                existing.quantity = orm.quantity
                existing.current_price = orm.current_price
                existing.stop_loss_price = orm.stop_loss_price
                existing.target_1_price = orm.target_1_price
                existing.target_2_price = orm.target_2_price
                existing.realized_pnl = orm.realized_pnl
                existing.current_mtm_pnl = orm.current_mtm_pnl
                existing.outcome = orm.outcome
                existing.stop_order_id = orm.stop_order_id
                existing.target_order_id = orm.target_order_id
                existing.closed_at = orm.closed_at
            await session.commit()

    async def get_by_id(self, position_id: UUID) -> Position | None:
        async with self._session_factory() as session:
            row = await session.get(PositionOrm, position_id)
            return _to_domain(row) if row else None

    async def get_open_positions(self) -> list[Position]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PositionOrm).where(PositionOrm.state.in_(_OPEN_STATES))
            )
            return [_to_domain(r) for r in result.scalars()]

    async def get_by_symbol(self, symbol: Symbol) -> list[Position]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PositionOrm).where(
                    PositionOrm.ticker == symbol.ticker,
                    PositionOrm.exchange == symbol.exchange,
                )
            )
            return [_to_domain(r) for r in result.scalars()]

    async def get_by_signal_id(self, signal_id: UUID) -> Position | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PositionOrm).where(PositionOrm.signal_id == signal_id)
            )
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None
