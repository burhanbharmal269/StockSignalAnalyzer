"""ConfidenceConfig — typed representation of config/confidence.yaml.

Reference: docs/21_SIGNAL_ENGINE.md §Stage 3 — Confidence Engine
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_CONFIG_PATH = Path(__file__).parents[4] / "config" / "confidence.yaml"


class BaseConfidenceConfig(BaseModel):
    ceiling: float = Field(ge=0.0, le=100.0)
    score_multiplier: float = Field(ge=0.0, le=1.0)


class WinRateConfig(BaseModel):
    lookback_days: int = Field(ge=1)
    min_signals: int = Field(ge=1)
    threshold_high: float = Field(ge=0.0, le=100.0)
    adj_high: float
    threshold_mid: float = Field(ge=0.0, le=100.0)
    adj_mid: float
    threshold_low: float = Field(ge=0.0, le=100.0)
    adj_low: float
    adj_below_low: float


class RegimeAlignmentConfig(BaseModel):
    adj_aligned: float
    adj_misaligned: float
    adj_neutral: float


class ScoreQualityScores(BaseModel):
    HIGH: float = 100.0
    MEDIUM: float = 70.0
    LOW: float = 40.0
    INSUFFICIENT: float = 0.0


class DataQualityConfig(BaseModel):
    # 3-part composite weights
    weight_score_quality: float = Field(ge=0.0, le=1.0)
    weight_data_completeness: float = Field(ge=0.0, le=1.0)
    weight_data_freshness: float = Field(ge=0.0, le=1.0)
    score_quality_scores: ScoreQualityScores
    # Freshness sub-score deduction points
    staleness_mild_min_seconds: int = Field(ge=0)
    staleness_mild_max_seconds: int = Field(ge=0)
    staleness_mild_pts: float
    staleness_severe_pts: float
    staleness_cap_pts: float
    option_chain_missing_pts: float
    oi_grace_seconds: int = Field(ge=0)
    # Composite score → adjustment thresholds
    threshold_high: float = Field(ge=0.0, le=100.0)
    adj_high: float
    threshold_mid: float = Field(ge=0.0, le=100.0)
    adj_mid: float
    threshold_low: float = Field(ge=0.0, le=100.0)
    adj_low: float
    adj_below_low: float


class MomentumConfig(BaseModel):
    adj_confirms: float
    adj_neutral: float
    adj_diverges: float


class BreakoutConfig(BaseModel):
    adj_confirmed: float
    adj_retest: float
    adj_failed: float
    adj_none: float


class LossStreakConfig(BaseModel):
    adj_per_loss: float
    floor: float
    lookback_trading_days: int = Field(ge=1)


class HistoricalAccuracyConfig(BaseModel):
    lookback_days: int = Field(ge=1)
    min_samples_full: int = Field(ge=1)
    min_samples_partial: int = Field(ge=1)
    threshold_high: float = Field(ge=0.0, le=100.0)
    threshold_mid: float = Field(ge=0.0, le=100.0)
    threshold_neutral: float = Field(ge=0.0, le=100.0)
    adj_high_full: float
    adj_high_partial: float
    adj_mid_full: float
    adj_mid_partial: float
    adj_neutral: float
    adj_low_full: float
    adj_low_partial: float


class CalibrationConfig(BaseModel):
    lookback_days: int = Field(ge=1)
    min_bucket_size: int = Field(ge=1)
    error_threshold_pct: float = Field(ge=0.0, le=100.0)


class GateConfig(BaseModel):
    min_score: float = Field(ge=0.0, le=100.0)
    min_confidence: float = Field(ge=0.0, le=100.0)


class CeilingConfig(BaseModel):
    strong_score_threshold: float = Field(ge=0.0, le=100.0)
    standard_max_confidence: float = Field(ge=0.0, le=100.0)


class SignalAgreementConfig(BaseModel):
    threshold_high: float = Field(ge=0.0, le=100.0)
    adj_high: float
    threshold_mid: float = Field(ge=0.0, le=100.0)
    adj_mid: float
    threshold_low: float = Field(ge=0.0, le=100.0)
    adj_low: float
    adj_below_low: float


class RecentPerformanceConfig(BaseModel):
    window_short: int = Field(ge=1)
    window_long: int = Field(ge=1)
    weight_short: float = Field(ge=0.0, le=1.0)
    weight_long: float = Field(ge=0.0, le=1.0)
    threshold_high: float = Field(ge=0.0, le=100.0)
    adj_high: float
    threshold_mid: float = Field(ge=0.0, le=100.0)
    adj_mid: float
    threshold_low: float = Field(ge=0.0, le=100.0)
    adj_low: float
    adj_below_low: float


class DedupConfig(BaseModel):
    ttl_seconds: int = Field(ge=1)
    score_delta_threshold: float = Field(ge=0.0)
    key_prefix: str


class ConfidenceConfig(BaseModel):
    version: str
    base: BaseConfidenceConfig
    win_rate: WinRateConfig
    regime_alignment: RegimeAlignmentConfig
    data_quality: DataQualityConfig
    momentum: MomentumConfig
    breakout: BreakoutConfig
    loss_streak: LossStreakConfig
    historical_accuracy: HistoricalAccuracyConfig
    signal_agreement: SignalAgreementConfig
    recent_performance: RecentPerformanceConfig
    calibration: CalibrationConfig
    gate: GateConfig
    ceiling: CeilingConfig
    dedup: DedupConfig


def load_confidence_config(path: Path = _CONFIG_PATH) -> ConfidenceConfig:
    """Load config/confidence.yaml and return a validated ConfidenceConfig."""
    raw: dict[str, object] = yaml.safe_load(path.read_bytes())
    return ConfidenceConfig.model_validate(raw)
