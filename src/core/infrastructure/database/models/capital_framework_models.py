"""ORM models for Phase 17 Capital Allocation Framework.

New tables:
  risk_profiles         — named risk parameter bundles
  capital_allocations   — operator-configured capital envelopes
  portfolios            — named position/order groups
  allocation_history    — append-only audit trail for allocation changes
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import BIGINT as PG_BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class RiskProfileOrm(Base):
    __tablename__ = "risk_profiles"

    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    profile_type: Mapped[str] = mapped_column(String(20), nullable=False)
    universe_scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ALL_FNO")

    # Per-trade risk
    risk_per_trade_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    max_open_positions: Mapped[int] = mapped_column(Integer, nullable=False)

    # Loss limits
    daily_loss_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    weekly_loss_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    # Position sizing
    max_position_size_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    min_position_size_lots: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_risk_profiles_active", "is_active"),
        Index("idx_risk_profiles_type", "profile_type"),
    )


class CapitalAllocationOrm(Base):
    __tablename__ = "capital_allocations"

    allocation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    allocation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    universe_scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ALL_FNO")
    capital_source_mode: Mapped[str] = mapped_column(String(15), nullable=False, server_default="HYBRID")

    # Capital amounts
    allocated_capital: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    allocated_margin: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)

    # Optional strategy scope
    strategy_type: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_capital_allocations_active", "is_active"),
        Index("idx_capital_allocations_type", "allocation_type"),
    )


class PortfolioOrm(Base):
    __tablename__ = "portfolios"

    portfolio_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    portfolio_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Capital framework links
    risk_profile_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    allocation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    # Future multi-user
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_portfolios_active", "is_active"),
        Index("idx_portfolios_type", "portfolio_type"),
        Index("idx_portfolios_owner", "owner_user_id"),
    )


class AllocationHistoryOrm(Base):
    """Append-only audit trail for capital allocation changes.

    No UPDATE, no DELETE — ever.  One row per change event.
    """

    __tablename__ = "allocation_history"

    # Use Integer for SQLite compat (autoincrement); PostgreSQL migration uses BIGINT.
    id: Mapped[int] = mapped_column(Integer().with_variant(BigInteger, "postgresql"), primary_key=True, autoincrement=True)
    allocation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_capital: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    new_capital: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    previous_margin: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    new_margin: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    changed_by: Mapped[str] = mapped_column(String(50), nullable=False, server_default="system")
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_allocation_history_allocation_id", "allocation_id", "changed_at"),
    )
