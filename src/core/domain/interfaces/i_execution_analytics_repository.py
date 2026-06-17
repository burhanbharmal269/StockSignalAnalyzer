"""IExecutionAnalyticsRepository — port for per-trade execution analytics."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass
class ExecutionAnalyticsRecord:
    analytics_id: int
    order_id: UUID | None
    signal_id: UUID | None
    broker_name: str
    symbol: str
    signal_gen_latency_ms: Decimal | None
    risk_eval_latency_ms: Decimal | None
    broker_submit_latency_ms: Decimal | None
    fill_latency_ms: Decimal | None
    total_e2e_latency_ms: Decimal | None
    expected_price: Decimal | None
    fill_price: Decimal | None
    slippage_bps: Decimal | None
    hold_seconds: Decimal | None
    realized_pnl: Decimal | None
    trading_mode: str
    recorded_at: datetime


@dataclass
class ExecutionAnalyticsInsert:
    order_id: UUID | None = None
    signal_id: UUID | None = None
    broker_name: str = "paper"
    symbol: str = ""
    signal_gen_latency_ms: Decimal | None = None
    risk_eval_latency_ms: Decimal | None = None
    broker_submit_latency_ms: Decimal | None = None
    fill_latency_ms: Decimal | None = None
    total_e2e_latency_ms: Decimal | None = None
    expected_price: Decimal | None = None
    fill_price: Decimal | None = None
    slippage_bps: Decimal | None = None
    hold_seconds: Decimal | None = None
    realized_pnl: Decimal | None = None
    trading_mode: str = "PAPER"


@dataclass
class AnalyticsSummary:
    symbol: str | None
    broker_name: str | None
    period_start: datetime | None
    period_end: datetime | None
    record_count: int
    avg_broker_submit_latency_ms: Decimal | None
    p50_broker_submit_latency_ms: Decimal | None
    p99_broker_submit_latency_ms: Decimal | None
    avg_fill_latency_ms: Decimal | None
    avg_e2e_latency_ms: Decimal | None
    avg_slippage_bps: Decimal | None
    avg_hold_seconds: Decimal | None
    total_pnl: Decimal | None
    win_count: int
    loss_count: int


class IExecutionAnalyticsRepository(ABC):
    @abstractmethod
    async def insert(self, record: ExecutionAnalyticsInsert) -> None:
        """Append a new analytics record."""

    @abstractmethod
    async def get_summary(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        symbol: str | None = None,
        broker_name: str | None = None,
        trading_mode: str | None = None,
    ) -> AnalyticsSummary:
        """Aggregate metrics over the given filter window."""

    @abstractmethod
    async def list_records(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExecutionAnalyticsRecord]:
        """Return individual analytics records."""
