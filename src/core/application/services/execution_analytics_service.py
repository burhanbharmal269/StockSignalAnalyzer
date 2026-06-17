"""ExecutionAnalyticsService — records and queries per-trade execution metrics.

Records are appended after each order fill. Queries support dashboard APIs.
All writes are fire-and-forget (errors logged, never re-raised).
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from decimal import Decimal
from uuid import UUID

from core.domain.interfaces.i_execution_analytics_repository import (
    AnalyticsSummary,
    ExecutionAnalyticsInsert,
    ExecutionAnalyticsRecord,
    IExecutionAnalyticsRepository,
)

_log = logging.getLogger(__name__)


class ExecutionAnalyticsService:
    """Writes and reads execution analytics."""

    def __init__(self, repository: IExecutionAnalyticsRepository) -> None:
        self._repo = repository

    async def record_fill(
        self,
        *,
        order_id: UUID | None = None,
        signal_id: UUID | None = None,
        broker_name: str,
        symbol: str,
        expected_price: Decimal | None = None,
        fill_price: Decimal | None = None,
        broker_submit_latency_ms: float | None = None,
        fill_latency_ms: float | None = None,
        signal_gen_latency_ms: float | None = None,
        risk_eval_latency_ms: float | None = None,
        hold_seconds: float | None = None,
        realized_pnl: Decimal | None = None,
        trading_mode: str = "PAPER",
    ) -> None:
        """Append analytics for a completed fill. Never raises."""
        slippage_bps: Decimal | None = None
        if expected_price and fill_price and expected_price > 0:
            slippage_bps = abs(fill_price - expected_price) / expected_price * Decimal("10000")

        total_e2e: Decimal | None = None
        parts = [broker_submit_latency_ms, fill_latency_ms,
                 signal_gen_latency_ms, risk_eval_latency_ms]
        if any(p is not None for p in parts):
            total_e2e = Decimal(str(sum(p for p in parts if p is not None)))

        record = ExecutionAnalyticsInsert(
            order_id=order_id,
            signal_id=signal_id,
            broker_name=broker_name,
            symbol=symbol,
            signal_gen_latency_ms=Decimal(str(signal_gen_latency_ms)) if signal_gen_latency_ms is not None else None,
            risk_eval_latency_ms=Decimal(str(risk_eval_latency_ms)) if risk_eval_latency_ms is not None else None,
            broker_submit_latency_ms=Decimal(str(broker_submit_latency_ms)) if broker_submit_latency_ms is not None else None,
            fill_latency_ms=Decimal(str(fill_latency_ms)) if fill_latency_ms is not None else None,
            total_e2e_latency_ms=total_e2e,
            expected_price=expected_price,
            fill_price=fill_price,
            slippage_bps=slippage_bps,
            hold_seconds=Decimal(str(hold_seconds)) if hold_seconds is not None else None,
            realized_pnl=realized_pnl,
            trading_mode=trading_mode,
        )
        try:
            await self._repo.insert(record)
        except Exception:
            _log.warning("execution_analytics.record_fill failed silently", exc_info=True)

    async def get_summary(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        symbol: str | None = None,
        broker_name: str | None = None,
        trading_mode: str | None = None,
    ) -> AnalyticsSummary:
        return await self._repo.get_summary(
            since=since,
            until=until,
            symbol=symbol,
            broker_name=broker_name,
            trading_mode=trading_mode,
        )

    async def list_records(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExecutionAnalyticsRecord]:
        return await self._repo.list_records(
            since=since, until=until, symbol=symbol, limit=limit, offset=offset
        )
