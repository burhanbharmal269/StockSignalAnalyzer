"""ORM models for risk_decisions and kill_switch_events tables (Phase 13)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class RiskDecisionModel(Base):
    """Append-only TimescaleDB hypertable for risk evaluation records.

    Application DB user has SELECT + INSERT only — UPDATE and DELETE are
    revoked in migration 004_phase13.  Partitioned by evaluated_at (1-day
    chunks) when TimescaleDB extension is present.
    """

    __tablename__ = "risk_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rejection_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    position_size_lots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_reduction_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    checks: Mapped[dict] = mapped_column(_JsonType, nullable=False)
    account_snapshot: Mapped[dict] = mapped_column(_JsonType, nullable=False)
    portfolio_snapshot: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    sizing_snapshot: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    failed_data_sources: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    risk_config_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_config_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Phase 17 audit columns
    risk_profile_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    allocation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_risk_decisions_signal_id", "signal_id"),
        Index("idx_risk_decisions_approved", "approved", "evaluated_at"),
        Index("idx_risk_decisions_evaluated_at", "evaluated_at"),
    )


class KillSwitchEventModel(Base):
    """Append-only audit table for kill switch lifecycle events.

    Application DB user has SELECT + INSERT only — UPDATE and DELETE are
    revoked in migration 004_phase13.  created_at is set by the database
    server; the application never sets it explicitly.
    """

    __tablename__ = "kill_switch_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[dict | None] = mapped_column("metadata", _JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_kill_switch_events_created_at", "created_at"),
        Index("idx_kill_switch_events_event_type", "event_type", "created_at"),
    )
