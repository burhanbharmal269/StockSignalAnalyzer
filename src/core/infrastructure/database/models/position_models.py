"""ORM model for the positions table."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class PositionOrm(Base):
    __tablename__ = "positions"

    position_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)

    # Signal / order linkage
    signal_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    order_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    # Instrument identification
    instrument_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tradingsymbol: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    ticker: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    underlying: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    # Position parameters
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    lots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Prices
    entry_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stop_loss_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    target_1_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    target_2_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # P&L
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    current_mtm_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    # State
    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    outcome: Mapped[str | None] = mapped_column(String(15), nullable=True)
    trading_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="LIVE")
    regime_at_open: Mapped[str] = mapped_column(String(30), nullable=False, default="")

    # Exit order linkage
    stop_order_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    target_order_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    # Phase 17 audit columns
    risk_profile_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    allocation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    portfolio_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    capital_source_mode: Mapped[str | None] = mapped_column(String(15), nullable=True)
    effective_capital: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    effective_margin: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)

    # Timestamps
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_positions_state", "state"),
        Index("idx_positions_signal_id", "signal_id"),
    )
