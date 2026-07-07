"""ORM models for Phase 24 — Strategy Research, Optimization & Versioning Framework.

All tables prefixed with research_. These are append-only analytics tables
that read from signal_analytics — production scoring is never modified.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class ResearchStrategyVersionOrm(Base):
    __tablename__ = "research_strategy_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weights_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    params_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scoring_weights_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_rsv_name", "name"),
        Index("ix_rsv_is_immutable", "is_immutable"),
    )


class ResearchRunOrm(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    run_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_research_runs_created_at", "created_at"),
    )


class ResearchOptimizationRunOrm(Base):
    __tablename__ = "research_optimization_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    param_grid: Mapped[dict] = mapped_column(JSONB, nullable=False)
    metric: Mapped[str] = mapped_column(String(30), nullable=False, default="sharpe")
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=252)
    combos_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    combos_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    best_metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ResearchOptimizationResultOrm(Base):
    __tablename__ = "research_optimization_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    sortino: Mapped[float | None] = mapped_column(Float, nullable=True)
    calmar: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_trade_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_ror_sharpe", "run_id", "sharpe"),
    )


class ResearchWalkForwardWindowOrm(Base):
    __tablename__ = "research_walk_forward_windows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    window_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    train_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    train_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    validate_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    validate_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    test_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    test_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    oos_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    oos_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    oos_trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oos_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ResearchMonteCarloRunOrm(Base):
    __tablename__ = "research_monte_carlo_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    n_sims: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=252)
    percentile_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_25: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_75: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_95: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_positive: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ResearchMonteCarloResultOrm(Base):
    __tablename__ = "research_monte_carlo_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sim_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    terminal_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_rmcr_run_id", "run_id"),
    )


class ResearchPerformanceSnapshotOrm(Base):
    __tablename__ = "research_performance_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    sortino: Mapped[float | None] = mapped_column(Float, nullable=True)
    calmar: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_trade_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_rps_computed_at", "computed_at"),
    )


class ResearchComponentCorrelationOrm(Base):
    __tablename__ = "research_component_correlations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    component_a: Mapped[str] = mapped_column(String(50), nullable=False)
    component_b: Mapped[str] = mapped_column(String(50), nullable=False)
    pearson_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_rcc_computed_at", "computed_at"),
    )


class ResearchFeatureImportanceOrm(Base):
    __tablename__ = "research_feature_importance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    component: Mapped[str] = mapped_column(String(50), nullable=False)
    importance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_rfi_computed_at", "computed_at"),
    )


class ResearchRegimePerformanceOrm(Base):
    __tablename__ = "research_regime_performance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    regime: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_rrp_computed_at", "computed_at"),
    )


class ResearchSymbolRankingOrm(Base):
    __tablename__ = "research_symbol_rankings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    signal_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_mfe: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_rank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_rsr_computed_at", "computed_at"),
        Index("ix_rsr_rank", "rank"),
    )


class ResearchFalsePositiveAnalysisOrm(Base):
    __tablename__ = "research_false_positive_analysis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    score_bucket: Mapped[str] = mapped_column(String(20), nullable=False)
    false_positive_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    false_negative_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_rfpa_computed_at", "computed_at"),
    )


class ResearchPromotionRequestOrm(Base):
    __tablename__ = "research_promotion_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requested_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    stat_test_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    oos_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    oos_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    walk_forward_windows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promotion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_rpr_status", "status"),
        Index("ix_rpr_created_at", "created_at"),
    )


class ResearchThresholdAnalysisOrm(Base):
    __tablename__ = "research_threshold_analysis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    threshold_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    optimal_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_improvement_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_name: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_rta_computed_at", "computed_at"),
    )
