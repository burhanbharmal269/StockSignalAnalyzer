"""SQLAlchemy implementation of ISignalPerformanceRepository.

All queries are read-only from the Confidence Engine's perspective.
The ``save`` method is provided for the Phase 14+ outcome recorder.

Reference: docs/18_TIMESCALEDB_ARCHITECTURE.md §signal_performance_stats
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.interfaces.i_signal_performance_repository import (
    ISignalPerformanceRepository,
    KellySizingStats,
    SignalPerformanceRecord,
)
from core.infrastructure.database.models.signal_performance_models import (
    SignalPerformanceStatsOrm,
)

_log = logging.getLogger(__name__)


class SqlAlchemySignalPerformanceRepository(ISignalPerformanceRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_win_rate(
        self,
        regime: str,
        direction: str,
        instrument_class: str,
        lookback_days: int,
        min_samples: int,
    ) -> float | None:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    func.count().label("total"),
                    func.sum(
                        func.cast(
                            SignalPerformanceStatsOrm.outcome == "WIN", type_=None
                        )
                    ).label("wins"),
                ).where(
                    and_(
                        SignalPerformanceStatsOrm.regime_at_signal == regime,
                        SignalPerformanceStatsOrm.direction == direction,
                        SignalPerformanceStatsOrm.instrument_class == instrument_class,
                        SignalPerformanceStatsOrm.recorded_at >= cutoff,
                    )
                )
            )
            row = result.one()
            total: int = row.total or 0
            wins: int = row.wins or 0
        if total < min_samples:
            return None
        return wins / total

    async def get_historical_accuracy(
        self,
        fingerprint: str,
        min_samples: int,
        lookback_days: int,
    ) -> tuple[float, int] | None:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    func.count().label("total"),
                    func.sum(
                        func.cast(
                            SignalPerformanceStatsOrm.outcome == "WIN", type_=None
                        )
                    ).label("wins"),
                ).where(
                    and_(
                        SignalPerformanceStatsOrm.fingerprint == fingerprint,
                        SignalPerformanceStatsOrm.recorded_at >= cutoff,
                    )
                )
            )
            row = result.one()
            total: int = row.total or 0
            wins: int = row.wins or 0
        if total < min_samples:
            return None
        return wins / total, total

    async def get_consecutive_losses(
        self,
        instrument: str,
        lookback_trading_days: int,
    ) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_trading_days * 2)
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalPerformanceStatsOrm.outcome)
                .where(
                    and_(
                        SignalPerformanceStatsOrm.instrument == instrument,
                        SignalPerformanceStatsOrm.recorded_at >= cutoff,
                    )
                )
                .order_by(SignalPerformanceStatsOrm.recorded_at.desc())
                .limit(lookback_trading_days * 5)
            )
            outcomes = [r[0] for r in result.fetchall()]
        streak = 0
        for outcome in outcomes:
            if outcome == "LOSS":
                streak += 1
            else:
                break
        return streak

    async def get_recent_outcomes(self, instrument: str, limit: int) -> list[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalPerformanceStatsOrm.outcome)
                .where(SignalPerformanceStatsOrm.instrument == instrument)
                .order_by(SignalPerformanceStatsOrm.recorded_at.desc())
                .limit(limit)
            )
            return [r[0] for r in result.fetchall()]

    async def get_sizing_stats(
        self,
        instrument: str,
        instrument_class: str,
        lookback_days: int,
        min_samples: int = 30,
    ) -> KellySizingStats | None:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        win_pnl = case(
            (SignalPerformanceStatsOrm.outcome == "WIN", SignalPerformanceStatsOrm.pnl_bps),
            else_=None,
        )
        loss_pnl = case(
            (SignalPerformanceStatsOrm.outcome == "LOSS", func.abs(SignalPerformanceStatsOrm.pnl_bps)),
            else_=None,
        )
        win_count_expr = func.count(
            case((SignalPerformanceStatsOrm.outcome == "WIN", 1), else_=None)
        )
        loss_count_expr = func.count(
            case((SignalPerformanceStatsOrm.outcome == "LOSS", 1), else_=None)
        )
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    func.count().label("total"),
                    win_count_expr.label("wins"),
                    loss_count_expr.label("losses"),
                    func.avg(win_pnl).label("avg_win"),
                    func.avg(loss_pnl).label("avg_loss"),
                ).where(
                    and_(
                        SignalPerformanceStatsOrm.instrument == instrument,
                        SignalPerformanceStatsOrm.instrument_class == instrument_class,
                        SignalPerformanceStatsOrm.recorded_at >= cutoff,
                    )
                )
            )
            row = result.one()
        total: int = row.total or 0
        if total < min_samples:
            return None
        wins: int = row.wins or 0
        losses: int = row.losses or 0
        avg_win: float = float(row.avg_win) if row.avg_win is not None else 0.0
        avg_loss: float = float(row.avg_loss) if row.avg_loss is not None else 0.0
        win_loss_ratio: float | None = (avg_win / avg_loss) if avg_loss > 0 else None
        return KellySizingStats(
            sample_count=total,
            win_count=wins,
            loss_count=losses,
            win_rate=wins / total,
            win_loss_ratio=win_loss_ratio,
        )

    async def save(self, record: SignalPerformanceRecord) -> None:
        async with self._session_factory() as session:
            orm = SignalPerformanceStatsOrm(
                fingerprint=record.fingerprint,
                signal_id=record.signal_id,
                instrument=record.instrument,
                instrument_class=record.instrument_class,
                direction=record.direction,
                regime_at_signal=record.regime_at_signal,
                score_bucket=record.score_bucket,
                vix_bucket=record.vix_bucket,
                top_2_components=record.top_2_components,
                score=record.score,
                confidence=record.confidence,
                outcome=record.outcome,
                entry_price=record.entry_price,
                exit_price=record.exit_price,
                pnl_bps=record.pnl_bps,
                hold_duration_minutes=record.hold_duration_minutes,
                dte_at_signal=record.dte_at_signal,
                confidence_calibration_error=record.confidence_calibration_error,
                recorded_at=record.recorded_at,
            )
            session.add(orm)
            await session.commit()
