"""ORM model for signal_analytics table.

Stores rich signal metadata + outcome tracking for every generated signal,
regardless of whether an order was placed.

Written at signal generation time (by SignalAnalyticsService).
Updated by SignalOutcomeTrackerService as price data becomes available.

Enables:
  - StrategyPerformanceService: win rate, Sharpe, profit factor per strategy
  - FilterAnalyticsService: filter rejection rates and their impact
  - Dashboard analytics: signals today, top symbols, sector distribution
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class SignalAnalyticsOrm(Base):
    __tablename__ = "signal_analytics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[UUID | None] = mapped_column(String(36), nullable=True, index=True)

    # Identity
    ticker: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    strategy_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    regime: Mapped[str] = mapped_column(String(30), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    is_index: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")

    # Signal levels
    entry_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    stop_loss_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    target_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dte: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Composite scores
    raw_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    adjusted_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Component score breakdown (from ScoreBreakdown)
    trend_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    volume_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    vwap_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    oi_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    iv_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    option_chain_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Technical context at signal time (for filter analytics)
    adx_at_signal: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    volume_ratio_at_signal: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    rsi_at_signal: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Rejection tracking (for filter analytics)
    was_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Outcome tracking (filled by SignalOutcomeTrackerService)
    # Values: WIN (target hit) | LOSS (stop hit) | PARTIAL (positive move, no target) | OPEN | EXPIRED
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    stop_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mfe_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)   # Max Favorable Excursion %
    mae_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)   # Max Adverse Excursion %
    current_return_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    return_1h_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    return_1d_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    return_5d_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    time_to_target_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_to_stop_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    outcome_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("idx_sa_ticker_created", "ticker", "created_at"),
        Index("idx_sa_strategy_created", "strategy_type", "created_at"),
        Index("idx_sa_direction_regime", "direction", "regime"),
        Index("idx_sa_outcome", "outcome", "strategy_type"),
        Index("idx_sa_accepted", "was_accepted", "created_at"),
    )
