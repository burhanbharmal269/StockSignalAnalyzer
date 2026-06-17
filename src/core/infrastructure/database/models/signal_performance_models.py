"""ORM model for signal_performance_stats table.

Regular relational table (not a hypertable) — queried by fingerprint
and regime, not by time range. Append-only; no updates or deletes.

Reference: docs/18_TIMESCALEDB_ARCHITECTURE.md §signal_performance_stats
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base

# ARRAY(String) renders as TEXT[] on PostgreSQL and is not supported by
# SQLite. Unit tests mock the repository; integration tests use PostgreSQL.
_StringArray = ARRAY(String(50))


class SignalPerformanceStatsOrm(Base):
    """signal_performance_stats — per-signal outcome records.

    Written once per closed position (by outcome recorder, Phase 14+).
    Read by Confidence Engine for win-rate, historical accuracy, and
    loss-streak queries.
    """

    __tablename__ = "signal_performance_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    instrument: Mapped[str] = mapped_column(String(30), nullable=False)
    instrument_class: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)
    regime_at_signal: Mapped[str] = mapped_column(String(30), nullable=False)
    score_bucket: Mapped[str] = mapped_column(String(10), nullable=False)
    vix_bucket: Mapped[str] = mapped_column(String(10), nullable=False)
    top_2_components: Mapped[list] = mapped_column(_StringArray, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    outcome: Mapped[str] = mapped_column(String(15), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    exit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    pnl_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    hold_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    dte_at_signal: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_calibration_error: Mapped[float | None] = mapped_column(
        Numeric(6, 3), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_spstats_fingerprint", "fingerprint", "recorded_at"),
        Index(
            "idx_spstats_regime_direction",
            "regime_at_signal",
            "direction",
            "instrument_class",
            "recorded_at",
        ),
        Index("idx_spstats_instrument", "instrument", "recorded_at"),
        Index("idx_spstats_outcome", "outcome", "regime_at_signal"),
    )
