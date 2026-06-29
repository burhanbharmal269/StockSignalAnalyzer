"""SQLAlchemy implementation of ISignalRepository."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from uuid import UUID

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select, text
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

if TYPE_CHECKING:
    from redis.asyncio import Redis

_log = logging.getLogger(__name__)

_CH_CREATED = "ssa:signal.created"
_CH_UPDATED = "ssa:signal.updated"
_STREAM_MAXLEN = 200

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


async def _attach_prices(session: AsyncSession, signals: list[Signal]) -> None:
    """Bulk-fetch entry/sl/target + option fields from signal_analytics."""
    if not signals:
        return
    ids = [str(s.signal_id) for s in signals]
    result = await session.execute(
        text("""
            SELECT DISTINCT ON (signal_id)
                signal_id, entry_price, stop_loss_price, target_price,
                option_type, option_strike, option_expiry, option_symbol,
                option_entry, option_sl, option_target,
                execution_grade
            FROM signal_analytics
            WHERE signal_id = ANY(:ids)
            ORDER BY signal_id, id DESC
        """),
        {"ids": ids},
    )
    price_map = {row.signal_id: row for row in result.mappings().fetchall()}
    for sig in signals:
        row = price_map.get(str(sig.signal_id))
        if row:
            sig.entry_price      = float(row["entry_price"])      if row["entry_price"]      is not None else None
            sig.stop_loss_price  = float(row["stop_loss_price"])  if row["stop_loss_price"]  is not None else None
            sig.target_price     = float(row["target_price"])     if row["target_price"]     is not None else None
            sig.option_type      = row["option_type"]
            sig.option_strike    = float(row["option_strike"])    if row["option_strike"]    is not None else None
            sig.option_expiry    = str(row["option_expiry"])      if row["option_expiry"]    is not None else None
            sig.option_symbol    = row["option_symbol"]
            sig.option_entry     = float(row["option_entry"])     if row["option_entry"]     is not None else None
            sig.option_sl        = float(row["option_sl"])        if row["option_sl"]        is not None else None
            sig.option_target    = float(row["option_target"])    if row["option_target"]    is not None else None
            sig.execution_grade  = row["execution_grade"]


class SqlAlchemySignalRepository(ISignalRepository):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: "Redis | None" = None,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client

    async def save(self, signal: Signal) -> None:
        is_new: bool = False
        async with self._session_factory() as session:
            existing = await session.get(SignalOrm, signal.signal_id)
            if existing is None:
                is_new = True
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

        await self._broadcast(signal, is_new=is_new)

    async def _broadcast(self, signal: Signal, *, is_new: bool) -> None:
        """Publish a minimal signal payload to Redis Pub/Sub + Stream for WS gateway."""
        if self._redis is None:
            return
        channel = _CH_CREATED if is_new else _CH_UPDATED
        payload = json.dumps({
            "signal_id":     str(signal.signal_id),
            "symbol":        signal.symbol.ticker,
            "exchange":      signal.symbol.exchange,
            "state":         signal.state.value,
            "signal_type":   signal.signal_type.value,
            "strategy_type": signal.strategy_type.value,
            "regime":        signal.regime.value,
            "confidence":    signal.confidence.value if signal.confidence else None,
            "adjusted_score": signal.adjusted_score.value if signal.adjusted_score else None,
        })
        try:
            # Pub/Sub — live push to connected WebSocket clients
            await self._redis.publish(channel, payload)
            # Stream — replay buffer for clients that reconnect (ws_router._replay_recent_events)
            await self._redis.xadd(channel, {"data": payload}, maxlen=_STREAM_MAXLEN, approximate=True)
        except Exception:
            _log.warning("signal_repository.broadcast_failed signal_id=%s channel=%s", signal.signal_id, channel, exc_info=True)

    async def get_by_id(self, signal_id: UUID) -> Signal | None:
        async with self._session_factory() as session:
            row = await session.get(SignalOrm, signal_id)
            if row is None:
                return None
            sig = _to_domain(row)
            await _attach_prices(session, [sig])
            return sig

    async def get_by_state(self, state: SignalState) -> list[Signal]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalOrm)
                .where(SignalOrm.state == state.value)
                .order_by(SignalOrm.created_at.desc())
            )
            signals = [_to_domain(r) for r in result.scalars()]
            await _attach_prices(session, signals)
            return signals

    async def get_active(self) -> list[Signal]:
        # Show all signals from the last 24h so users can review today's activity,
        # including RISK_REJECTED and WEAK_SIGNAL terminal states (read-only reference).
        yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalOrm)
                .where(SignalOrm.created_at >= yesterday)
                .order_by(SignalOrm.created_at.desc())
                .limit(500)
            )
            signals = [_to_domain(r) for r in result.scalars()]
            await _attach_prices(session, signals)
            return signals
