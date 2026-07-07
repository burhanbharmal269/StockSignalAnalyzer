"""Pydantic schemas for Phase 24 Research API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Strategy Versions ─────────────────────────────────────────────────────────

class VersionResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    weights_snapshot: dict = Field(default_factory=dict)
    params_snapshot: dict | None = None
    is_immutable: bool = False
    base_version_id: str | None = None
    scoring_weights_sha256: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class VersionListResponse(BaseModel):
    versions: list[VersionResponse]
    total: int


class CreateVariantRequest(BaseModel):
    name: str
    base_version_id: str
    weights: dict
    params: dict | None = None
    description: str | None = None


class UpdateVariantRequest(BaseModel):
    weights: dict | None = None
    params: dict | None = None


# ── Optimization ──────────────────────────────────────────────────────────────

class StartGridSearchRequest(BaseModel):
    version_id: str
    param_grid: dict
    metric: str = "sharpe"
    lookback_days: int = 252


class RunStatusResponse(BaseModel):
    id: str | None = None
    version_id: str | None = None
    run_type: str | None = None
    status: str | None = None
    params: dict | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class OptimizationResultResponse(BaseModel):
    id: int | None = None
    run_id: str | None = None
    params: dict = Field(default_factory=dict)
    sharpe: float | None = None
    sortino: float | None = None
    calmar: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    trade_count: int | None = None
    avg_trade_pnl: float | None = None


class OptimizationResultsResponse(BaseModel):
    run_id: str
    results: list[OptimizationResultResponse]
    total: int


# ── Walk-Forward ──────────────────────────────────────────────────────────────

class StartWalkForwardRequest(BaseModel):
    version_id: str
    from_dt: datetime
    to_dt: datetime
    n_windows: int = 5


class WalkForwardWindowResponse(BaseModel):
    id: int | None = None
    run_id: str | None = None
    window_idx: int | None = None
    train_from: Any = None
    train_to: Any = None
    test_from: Any = None
    test_to: Any = None
    is_sharpe: float | None = None
    oos_sharpe: float | None = None
    oos_win_rate: float | None = None
    oos_trade_count: int | None = None
    oos_pnl: float | None = None
    best_params: dict | None = None


class WalkForwardWindowsResponse(BaseModel):
    run_id: str
    windows: list[WalkForwardWindowResponse]
    aggregate: dict | None = None


# ── Monte Carlo ───────────────────────────────────────────────────────────────

class StartMonteCarloRequest(BaseModel):
    version_id: str
    n_sims: int = Field(default=1000, ge=10, le=10000)
    lookback_days: int = 252
    seed: int | None = None


class MonteCarloResultsResponse(BaseModel):
    run_id: str
    summary: dict
    simulations: list[dict]


# ── Performance ───────────────────────────────────────────────────────────────

class PerformanceResponse(BaseModel):
    version_id: str
    sharpe: float | None = None
    sortino: float | None = None
    calmar: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    avg_trade_pnl: float | None = None
    trade_count: int | None = None
    lookback_days: int | None = None


class CompareVersionsRequest(BaseModel):
    version_ids: list[str]
    lookback_days: int = 252


class CompareVersionsResponse(BaseModel):
    comparisons: list[PerformanceResponse]


# ── Correlations ──────────────────────────────────────────────────────────────

class CorrelationResponse(BaseModel):
    component_a: str
    component_b: str
    pearson_r: float | None = None
    p_value: float | None = None
    computed_at: datetime | None = None


class CorrelationListResponse(BaseModel):
    correlations: list[CorrelationResponse]
    total: int


# ── Feature Importance ────────────────────────────────────────────────────────

class FeatureImportanceResponse(BaseModel):
    component: str
    importance_score: float | None = None
    rank: int | None = None
    lookback_days: int | None = None
    computed_at: datetime | None = None


class FeatureImportanceListResponse(BaseModel):
    importance: list[FeatureImportanceResponse]


# ── Regime Performance ────────────────────────────────────────────────────────

class RegimePerformanceResponse(BaseModel):
    regime: str
    direction: str
    strategy_type: str | None = None
    win_rate: float | None = None
    avg_score: float | None = None
    avg_pnl: float | None = None
    sample_size: int | None = None
    computed_at: datetime | None = None


class RegimePerformanceListResponse(BaseModel):
    breakdown: list[RegimePerformanceResponse]
    total: int


# ── Symbol Rankings ───────────────────────────────────────────────────────────

class SymbolRankingResponse(BaseModel):
    ticker: str
    signal_count: int | None = None
    win_rate: float | None = None
    avg_score: float | None = None
    avg_pnl: float | None = None
    avg_mfe: float | None = None
    composite_rank_score: float | None = None
    rank: int | None = None
    computed_at: datetime | None = None


class SymbolRankingsResponse(BaseModel):
    rankings: list[SymbolRankingResponse]
    total: int


# ── False Positive Analysis ───────────────────────────────────────────────────

class FalsePositiveResponse(BaseModel):
    component: str
    score_bucket: str
    false_positive_rate: float | None = None
    false_negative_rate: float | None = None
    sample_size: int | None = None
    computed_at: datetime | None = None


class FalsePositiveListResponse(BaseModel):
    analysis: list[FalsePositiveResponse]
    total: int


# ── Promotion ─────────────────────────────────────────────────────────────────

class RequestPromotionRequest(BaseModel):
    version_id: str
    requested_by: str | None = None
    notes: str | None = None


class ApprovePromotionRequest(BaseModel):
    reviewer: str | None = None


class RejectPromotionRequest(BaseModel):
    reviewer: str | None = None
    reason: str | None = None


class PromotionRequestResponse(BaseModel):
    id: str
    version_id: str
    version_name: str | None = None
    requested_by: str | None = None
    status: str
    stat_test_passed: bool | None = None
    oos_sharpe: float | None = None
    oos_win_rate: float | None = None
    walk_forward_windows: int | None = None
    promotion_notes: str | None = None
    rejection_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime | None = None


class PromotionQueueResponse(BaseModel):
    queue: list[PromotionRequestResponse]
    total: int
