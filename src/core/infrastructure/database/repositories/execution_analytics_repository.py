"""SqlAlchemy implementation of IExecutionAnalyticsRepository."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.interfaces.i_execution_analytics_repository import (
    AnalyticsSummary,
    ExecutionAnalyticsInsert,
    ExecutionAnalyticsRecord,
    IExecutionAnalyticsRepository,
)
from core.infrastructure.database.models.reconciliation_models import ExecutionAnalyticsOrm


class SqlAlchemyExecutionAnalyticsRepository(IExecutionAnalyticsRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        async with self._factory() as s:
            async with s.begin():
                yield s

    async def insert(self, record: ExecutionAnalyticsInsert) -> None:
        async with self._session() as s:
            row = ExecutionAnalyticsOrm(
                order_id=record.order_id,
                signal_id=record.signal_id,
                broker_name=record.broker_name,
                symbol=record.symbol,
                signal_gen_latency_ms=record.signal_gen_latency_ms,
                risk_eval_latency_ms=record.risk_eval_latency_ms,
                broker_submit_latency_ms=record.broker_submit_latency_ms,
                fill_latency_ms=record.fill_latency_ms,
                total_e2e_latency_ms=record.total_e2e_latency_ms,
                expected_price=record.expected_price,
                fill_price=record.fill_price,
                slippage_bps=record.slippage_bps,
                hold_seconds=record.hold_seconds,
                realized_pnl=record.realized_pnl,
                trading_mode=record.trading_mode,
            )
            s.add(row)

    async def get_summary(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        symbol: str | None = None,
        broker_name: str | None = None,
        trading_mode: str | None = None,
    ) -> AnalyticsSummary:
        async with self._factory() as s:
            stmt = select(
                func.count(ExecutionAnalyticsOrm.analytics_id).label("cnt"),
                func.avg(ExecutionAnalyticsOrm.broker_submit_latency_ms).label("avg_submit"),
                func.avg(ExecutionAnalyticsOrm.fill_latency_ms).label("avg_fill"),
                func.avg(ExecutionAnalyticsOrm.total_e2e_latency_ms).label("avg_e2e"),
                func.avg(ExecutionAnalyticsOrm.slippage_bps).label("avg_slippage"),
                func.avg(ExecutionAnalyticsOrm.hold_seconds).label("avg_hold"),
                func.sum(ExecutionAnalyticsOrm.realized_pnl).label("total_pnl"),
                func.sum(
                    func.cast(ExecutionAnalyticsOrm.realized_pnl > 0, sqlalchemy_integer())
                ).label("wins"),
                func.sum(
                    func.cast(ExecutionAnalyticsOrm.realized_pnl < 0, sqlalchemy_integer())
                ).label("losses"),
            )
            stmt = self._apply_filters(stmt, since, until, symbol, broker_name, trading_mode)
            row = (await s.execute(stmt)).one()

            return AnalyticsSummary(
                symbol=symbol,
                broker_name=broker_name,
                period_start=since,
                period_end=until,
                record_count=int(row.cnt or 0),
                avg_broker_submit_latency_ms=_dec(row.avg_submit),
                p50_broker_submit_latency_ms=None,  # percentiles need timescaledb
                p99_broker_submit_latency_ms=None,
                avg_fill_latency_ms=_dec(row.avg_fill),
                avg_e2e_latency_ms=_dec(row.avg_e2e),
                avg_slippage_bps=_dec(row.avg_slippage),
                avg_hold_seconds=_dec(row.avg_hold),
                total_pnl=_dec(row.total_pnl),
                win_count=int(row.wins or 0),
                loss_count=int(row.losses or 0),
            )

    async def list_records(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExecutionAnalyticsRecord]:
        async with self._factory() as s:
            stmt = (
                select(ExecutionAnalyticsOrm)
                .order_by(ExecutionAnalyticsOrm.recorded_at.desc())
                .limit(limit)
                .offset(offset)
            )
            stmt = self._apply_filters(stmt, since, until, symbol)
            rows = (await s.execute(stmt)).scalars().all()
            return [self._to_domain(r) for r in rows]

    @staticmethod
    def _apply_filters(stmt, since=None, until=None, symbol=None, broker_name=None, mode=None):
        if since:
            stmt = stmt.where(ExecutionAnalyticsOrm.recorded_at >= since)
        if until:
            stmt = stmt.where(ExecutionAnalyticsOrm.recorded_at <= until)
        if symbol:
            stmt = stmt.where(ExecutionAnalyticsOrm.symbol == symbol)
        if broker_name:
            stmt = stmt.where(ExecutionAnalyticsOrm.broker_name == broker_name)
        if mode:
            stmt = stmt.where(ExecutionAnalyticsOrm.trading_mode == mode)
        return stmt

    @staticmethod
    def _to_domain(r: ExecutionAnalyticsOrm) -> ExecutionAnalyticsRecord:
        return ExecutionAnalyticsRecord(
            analytics_id=r.analytics_id,
            order_id=r.order_id,
            signal_id=r.signal_id,
            broker_name=r.broker_name,
            symbol=r.symbol,
            signal_gen_latency_ms=r.signal_gen_latency_ms,
            risk_eval_latency_ms=r.risk_eval_latency_ms,
            broker_submit_latency_ms=r.broker_submit_latency_ms,
            fill_latency_ms=r.fill_latency_ms,
            total_e2e_latency_ms=r.total_e2e_latency_ms,
            expected_price=r.expected_price,
            fill_price=r.fill_price,
            slippage_bps=r.slippage_bps,
            hold_seconds=r.hold_seconds,
            realized_pnl=r.realized_pnl,
            trading_mode=r.trading_mode,
            recorded_at=r.recorded_at,
        )


def _dec(v) -> Decimal | None:
    return Decimal(str(v)) if v is not None else None


def sqlalchemy_integer():
    from sqlalchemy import Integer
    return Integer
