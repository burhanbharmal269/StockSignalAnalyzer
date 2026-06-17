"""ORM models for signals and signal_events tables.

signals — relational table for the signal lifecycle.
signal_events — TimescaleDB hypertable for immutable state-transition log.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID
from uuid import UUID

from sqlalchemy import JSON, DateTime, Index, Numeric, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base

# Renders as JSONB on PostgreSQL, JSON on SQLite (for unit tests).
_JsonType = JSONB().with_variant(JSON(), "sqlite")


class SignalOrm(Base):
    __tablename__ = "signals"

    signal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(30), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    regime: Mapped[str] = mapped_column(String(30), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    raw_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    adjusted_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    scoring_weights_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    risk_rejection_reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    # Phase 17 audit columns
    risk_profile_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    allocation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    portfolio_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    capital_source_mode: Mapped[str | None] = mapped_column(String(15), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SignalEventOrm(Base):
    """Hypertable: signal_events. Immutable event log for signal state transitions."""

    __tablename__ = "signal_events"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    signal_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(30), primary_key=True, nullable=False)
    event_data: Mapped[dict] = mapped_column(_JsonType, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("idx_signal_events_signal_id", "signal_id", "timestamp"),
    )
