"""SqlAlchemy implementation of IPaperTradingStatsRepository."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.interfaces.i_paper_trading_stats_repository import (
    IPaperTradingStatsRepository,
    PaperTradingStats,
    PaperTradingStatsUpsert,
)
from core.infrastructure.database.models.reconciliation_models import PaperTradingStatsOrm


class SqlAlchemyPaperTradingStatsRepository(IPaperTradingStatsRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        async with self._factory() as s:
            async with s.begin():
                yield s

    async def upsert(self, stats: PaperTradingStatsUpsert) -> None:
        async with self._session() as s:
            existing = await s.execute(
                select(PaperTradingStatsOrm).where(
                    PaperTradingStatsOrm.period_type == stats.period_type,
                    PaperTradingStatsOrm.period_label == stats.period_label,
                )
            )
            row = existing.scalar_one_or_none()
            if row is None:
                row = PaperTradingStatsOrm(
                    period_type=stats.period_type,
                    period_label=stats.period_label,
                )
                s.add(row)
            row.signals_generated = stats.signals_generated
            row.signals_approved = stats.signals_approved
            row.signals_rejected = stats.signals_rejected
            row.orders_placed = stats.orders_placed
            row.orders_filled = stats.orders_filled
            row.orders_cancelled = stats.orders_cancelled
            row.positions_opened = stats.positions_opened
            row.positions_closed = stats.positions_closed
            row.gross_pnl = stats.gross_pnl
            row.win_count = stats.win_count
            row.loss_count = stats.loss_count
            row.max_drawdown = stats.max_drawdown
            row.avg_hold_seconds = stats.avg_hold_seconds
            row.avg_slippage_bps = stats.avg_slippage_bps
            row.broker_latency_p50_ms = stats.broker_latency_p50_ms
            row.broker_latency_p99_ms = stats.broker_latency_p99_ms
            row.snapshot = stats.snapshot

    async def get(self, period_type: str, period_label: str) -> PaperTradingStats | None:
        async with self._factory() as s:
            result = await s.execute(
                select(PaperTradingStatsOrm).where(
                    PaperTradingStatsOrm.period_type == period_type,
                    PaperTradingStatsOrm.period_label == period_label,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._to_domain(row)

    async def list_by_type(
        self, period_type: str, limit: int = 30, offset: int = 0
    ) -> list[PaperTradingStats]:
        async with self._factory() as s:
            stmt = (
                select(PaperTradingStatsOrm)
                .where(PaperTradingStatsOrm.period_type == period_type)
                .order_by(PaperTradingStatsOrm.period_label.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = (await s.execute(stmt)).scalars().all()
            return [self._to_domain(r) for r in rows]

    @staticmethod
    def _to_domain(r: PaperTradingStatsOrm) -> PaperTradingStats:
        return PaperTradingStats(
            stat_id=r.stat_id,
            period_type=r.period_type,
            period_label=r.period_label,
            signals_generated=r.signals_generated,
            signals_approved=r.signals_approved,
            signals_rejected=r.signals_rejected,
            orders_placed=r.orders_placed,
            orders_filled=r.orders_filled,
            orders_cancelled=r.orders_cancelled,
            positions_opened=r.positions_opened,
            positions_closed=r.positions_closed,
            gross_pnl=r.gross_pnl,
            win_count=r.win_count,
            loss_count=r.loss_count,
            max_drawdown=r.max_drawdown,
            avg_hold_seconds=r.avg_hold_seconds,
            avg_slippage_bps=r.avg_slippage_bps,
            broker_latency_p50_ms=r.broker_latency_p50_ms,
            broker_latency_p99_ms=r.broker_latency_p99_ms,
            snapshot=r.snapshot,
            created_at=r.created_at,
        )
