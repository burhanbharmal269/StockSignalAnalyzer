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

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
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

    # Phase 14 — MTF attribution (allows post-hoc aligned vs conflicted trade analysis)
    # mtf_alignment: 5m candle bias at signal time ("BULLISH", "BEARISH", "NEUTRAL")
    # mtf_score_bonus: raw bonus applied by TrendComponent (-4 to +4, pre-regime scaling)
    # mtf_confidence_bonus: confidence adjustment applied to momentum_adj (-5 to +5)
    mtf_alignment: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mtf_score_bonus: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    mtf_confidence_bonus: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)

    # Phase 15 — Data quality + realized P&L
    # pnl_pct: realized P&L % for closed trade (set by outcome tracker)
    # data_quality_score: 0-100 feed quality score at signal generation time (monitoring only)
    # missing_sources: JSON list of sources unavailable at signal time
    pnl_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    data_quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_sources: Mapped[str | None] = mapped_column(String(200), nullable=True)

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

    # Option contract recommendation (from signal_analytics migration 20260618_1000)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True)
    option_strike: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    option_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    option_symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    option_entry: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    option_sl: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    option_target: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Phase 21.1 — context overlay attribution (added migration 20260626_1000)
    market_context: Mapped[str | None] = mapped_column(String(20), nullable=True)
    market_context_adj: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    event_adj: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    event_overlay_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    regime_stability: Mapped[str | None] = mapped_column(String(20), nullable=True)
    regime_stability_adj: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_attribution_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_size_multiplier: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    overlay_adjusted_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    execution_grade: Mapped[str | None] = mapped_column(String(5), nullable=True)

    # Phase 21.2 — decision trace + versions (added migration 20260626_1100)
    decision_trace_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    overlay_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Phase 23 — signal qualification + deployment stage (added migration 20260627_1000)
    qualification_grade: Mapped[str | None] = mapped_column(String(5), nullable=True)
    qualification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualification_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qualification_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deployment_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Phase 21.1 — Futures OI context at signal time (added migration 20260701_1000)
    futures_oi:              Mapped[int | None]   = mapped_column(BigInteger, nullable=True)
    oi_change:               Mapped[int | None]   = mapped_column(BigInteger, nullable=True)
    oi_change_pct:           Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    oi_direction:            Mapped[str | None]   = mapped_column(String(20), nullable=True)
    oi_regime:               Mapped[str | None]   = mapped_column(String(30), nullable=True)
    futures_contract:        Mapped[str | None]   = mapped_column(String(50), nullable=True)
    oi_quality_score:        Mapped[str | None]   = mapped_column(String(20), nullable=True)
    quote_freshness_seconds: Mapped[int | None]   = mapped_column(Integer, nullable=True)

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
