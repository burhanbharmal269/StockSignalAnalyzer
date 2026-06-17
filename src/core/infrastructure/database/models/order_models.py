"""ORM models for orders, order_events, and executions tables."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class OrderOrm(Base):
    __tablename__ = "orders"

    order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    signal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)

    # Instrument identification
    instrument_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tradingsymbol: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    ticker: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    underlying: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    # Order parameters
    transaction_type: Mapped[str] = mapped_column(String(4), nullable=False, default="BUY")
    order_type: Mapped[str] = mapped_column(String(15), nullable=False, default="MARKET")
    product: Mapped[str] = mapped_column(String(10), nullable=False, default="MIS")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    lots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    validity: Mapped[str] = mapped_column(String(5), nullable=False, default="DAY")

    # Risk linkage
    risk_decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Broker tracking
    broker_order_id: Mapped[str] = mapped_column(String(50), default="", nullable=False)

    # State
    state: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    trading_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="LIVE")

    # Fill tracking
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Parent position (for SL/target child orders)
    parent_position_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    # Phase 17 audit columns
    risk_profile_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    allocation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    portfolio_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    capital_source_mode: Mapped[str | None] = mapped_column(String(15), nullable=True)
    effective_capital: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    effective_margin: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_orders_state_created", "state", "created_at"),
        Index(
            "idx_orders_broker_order_id",
            "broker_order_id",
            postgresql_where=("broker_order_id != ''"),
        ),
    )


class OrderEventOrm(Base):
    """Hypertable: order_events. Immutable event log for order state transitions."""

    __tablename__ = "order_events"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), primary_key=True, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_data: Mapped[dict] = mapped_column(_JsonType, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("idx_order_events_order_id", "order_id", "timestamp"),
    )


class ExecutionOrm(Base):
    """Individual fill records — one per execution at the exchange.

    Multiple rows per order are normal (partial fills).
    Append-only: fills are never modified.
    """

    __tablename__ = "executions"

    fill_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    broker_order_id: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_trade_id: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fill_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trading_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="LIVE")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_executions_order_id_fill_time", "order_id", "fill_time"),
    )
