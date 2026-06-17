"""ORM models for reconciliation engine tables."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class ReconciliationRunOrm(Base):
    __tablename__ = "reconciliation_runs"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker_name: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger: Mapped[str] = mapped_column(String(15), nullable=False, default="SCHEDULED")
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="RUNNING")
    orders_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    positions_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fills_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rogue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repaired_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_reconciliation_runs_broker_started", "broker_name", "started_at"),
        Index("idx_reconciliation_runs_status", "status"),
    )


class ReconciliationDiscrepancyOrm(Base):
    __tablename__ = "reconciliation_discrepancies"

    discrepancy_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    discrepancy_type: Mapped[str] = mapped_column(String(30), nullable=False)
    order_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oms_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    broker_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    repair_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    repaired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    repaired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_reconciliation_discrepancies_type", "discrepancy_type", "created_at"),
        Index("idx_reconciliation_discrepancies_repaired", "repaired"),
    )


class PaperTradingStatsOrm(Base):
    __tablename__ = "paper_trading_stats"

    stat_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    signals_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_approved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orders_placed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orders_filled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orders_cancelled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    positions_opened: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    positions_closed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    win_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    avg_hold_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    avg_slippage_bps: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    broker_latency_p50_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    broker_latency_p99_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_paper_trading_stats_period", "period_type", "period_label"),
    )


class ExecutionAnalyticsOrm(Base):
    __tablename__ = "execution_analytics"

    analytics_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    signal_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    broker_name: Mapped[str] = mapped_column(String(30), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    signal_gen_latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    risk_eval_latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    broker_submit_latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fill_latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_e2e_latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    expected_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fill_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    slippage_bps: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    hold_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    trading_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="PAPER")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_execution_analytics_symbol_recorded", "symbol", "recorded_at"),
        Index("idx_execution_analytics_broker", "broker_name", "recorded_at"),
    )


class LiveTradingRampUpOrm(Base):
    __tablename__ = "live_trading_ramp_up"

    ramp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    current_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stage_capital: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=5000)
    stage_entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    performance_snapshot: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
