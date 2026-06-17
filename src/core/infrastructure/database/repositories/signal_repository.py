"""SQLAlchemy implementation of ISignalRepository."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.signal import Signal
from core.domain.enums.asset_type import AssetType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.market_regime import MarketRegime
from core.domain.enums.signal_state import SignalState
from core.domain.enums.signal_type import SignalType
from core.domain.enums.strategy_type import StrategyType
from core.domain.interfaces.i_signal_repository import ISignalRepository
from core.domain.value_objects.confidence import Confidence
from core.domain.value_objects.score import Score
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.database.models.signal_models import SignalOrm

_TERMINAL_STATES = {
    SignalState.EXECUTED,
    SignalState.EXPIRED,
    SignalState.CANCELLED,
    SignalState.FAILED,
    SignalState.WEAK_SIGNAL,
    SignalState.RISK_REJECTED,
}


def _to_orm(signal: Signal) -> SignalOrm:
    return SignalOrm(
        signal_id=signal.signal_id,
        ticker=signal.symbol.ticker,
        exchange=signal.symbol.exchange,
        signal_type=signal.signal_type.value,
        strategy_type=signal.strategy_type.value,
        asset_type=signal.asset_type.value,
        regime=signal.regime.value,
        state=signal.state.value,
        valid_until=signal.valid_until,
        correlation_id=signal.correlation_id,
        raw_score=Decimal(str(signal.raw_score.value)) if signal.raw_score else None,
        adjusted_score=Decimal(str(signal.adjusted_score.value)) if signal.adjusted_score else None,
        confidence=Decimal(str(signal.confidence.value)) if signal.confidence else None,
        scoring_weights_sha256=signal.scoring_weights_sha256,
        fingerprint=signal.fingerprint,
        risk_rejection_reason=signal.risk_rejection_reason,
        risk_profile_id=signal.risk_profile_id,
        allocation_id=signal.allocation_id,
        portfolio_id=signal.portfolio_id,
        capital_source_mode=signal.capital_source_mode.value if signal.capital_source_mode else None,
        created_at=signal.created_at,
    )


def _to_domain(row: SignalOrm) -> Signal:
    sig = Signal(
        signal_id=row.signal_id,
        symbol=Symbol(row.ticker, row.exchange),
        signal_type=SignalType(row.signal_type),
        strategy_type=StrategyType(row.strategy_type),
        asset_type=AssetType(row.asset_type),
        regime=MarketRegime(row.regime),
        valid_until=row.valid_until,
        correlation_id=row.correlation_id,
        state=SignalState(row.state),
        raw_score=Score(float(row.raw_score)) if row.raw_score is not None else None,
        adjusted_score=Score(float(row.adjusted_score)) if row.adjusted_score is not None else None,
        confidence=Confidence(float(row.confidence)) if row.confidence is not None else None,
        scoring_weights_sha256=row.scoring_weights_sha256,
        fingerprint=row.fingerprint,
        risk_rejection_reason=row.risk_rejection_reason,
        risk_profile_id=row.risk_profile_id,
        allocation_id=row.allocation_id,
        portfolio_id=row.portfolio_id,
        capital_source_mode=CapitalSourceMode(row.capital_source_mode) if row.capital_source_mode else None,
        created_at=row.created_at,
    )
    return sig


class SqlAlchemySignalRepository(ISignalRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, signal: Signal) -> None:
        async with self._session_factory() as session:
            existing = await session.get(SignalOrm, signal.signal_id)
            if existing is None:
                session.add(_to_orm(signal))
            else:
                orm = _to_orm(signal)
                existing.state = orm.state
                existing.raw_score = orm.raw_score
                existing.adjusted_score = orm.adjusted_score
                existing.confidence = orm.confidence
                existing.scoring_weights_sha256 = orm.scoring_weights_sha256
                existing.fingerprint = orm.fingerprint
                existing.risk_rejection_reason = orm.risk_rejection_reason
                existing.risk_profile_id = orm.risk_profile_id
                existing.allocation_id = orm.allocation_id
                existing.portfolio_id = orm.portfolio_id
                existing.capital_source_mode = orm.capital_source_mode
            await session.commit()

    async def get_by_id(self, signal_id: UUID) -> Signal | None:
        async with self._session_factory() as session:
            row = await session.get(SignalOrm, signal_id)
            return _to_domain(row) if row else None

    async def get_by_state(self, state: SignalState) -> list[Signal]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalOrm).where(SignalOrm.state == state.value)
            )
            return [_to_domain(r) for r in result.scalars()]

    async def get_active(self) -> list[Signal]:
        terminal_values = [s.value for s in _TERMINAL_STATES]
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalOrm).where(SignalOrm.state.notin_(terminal_values))
            )
            return [_to_domain(r) for r in result.scalars()]
