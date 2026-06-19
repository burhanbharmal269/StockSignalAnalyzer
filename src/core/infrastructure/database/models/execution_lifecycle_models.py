"""ExecutionLifecycleOrm — per-order execution lifecycle tracking.

One row per order. Status transitions and timestamps are updated in-place
as the order progresses through its lifecycle:

  SIGNAL_GENERATED → ORDER_SUBMITTED → ORDER_FILLED
                   ↘ ORDER_REJECTED
                   ↘ ORDER_CANCELLED

Slippage columns are computed and stored when fills arrive:
  entry_slippage_pct = (actual_entry - expected_entry) / expected_entry × 100
  exit_slippage_pct  = (expected_exit - actual_exit)  / expected_exit  × 100
  total_slippage_pct = entry_slippage_pct + exit_slippage_pct

Latency columns are computed from timestamp deltas:
  signal_to_order_ms = (order_submitted_at - signal_generated_at) in ms
  order_to_fill_ms   = (order_filled_at - order_submitted_at) in ms
  signal_to_fill_ms  = (order_filled_at - signal_generated_at) in ms

Phase 17 — Sections D (slippage), E (fill quality), F (broker latency).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class ExecutionLifecycleOrm(Base):
    __tablename__ = "execution_lifecycle"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # References (soft — no FK constraint to allow independent truncation)
    signal_id:  Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    order_id:   Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # Context
    symbol:      Mapped[str]        = mapped_column(String(50), nullable=False, index=True)
    regime:      Mapped[str | None] = mapped_column(String(30), nullable=True)
    direction:   Mapped[str | None] = mapped_column(String(10), nullable=True)
    broker_name: Mapped[str]        = mapped_column(String(30), nullable=False, default="zerodha")

    # Status chain
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SIGNAL_GENERATED")

    # Timestamps for each lifecycle stage
    signal_generated_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_submitted_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_filled_at:      Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_rejected_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_cancelled_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Price levels
    expected_entry_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    actual_entry_price:   Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    expected_exit_price:  Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    actual_exit_price:    Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Slippage (computed on fill, stored for fast querying)
    entry_slippage_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    exit_slippage_pct:  Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    total_slippage_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Latency in milliseconds (computed from timestamp deltas, stored for fast querying)
    signal_to_order_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    order_to_fill_ms:   Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    signal_to_fill_ms:  Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Rejection / cancellation reason
    rejection_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("idx_el_symbol_created",  "symbol",    "created_at"),
        Index("idx_el_regime_created",  "regime",    "created_at"),
        Index("idx_el_status_created",  "status",    "created_at"),
        Index("idx_el_signal_id",       "signal_id"),
    )
