"""Pydantic-backed loader for config/strategy.yaml.

Pattern mirrors regime_config.py — YAML on disk, Pydantic for validation,
factory function returns a singleton-safe instance.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_CONFIG_PATH = Path(__file__).parents[4] / "config" / "strategy.yaml"


class _BaseWeightsConfig(BaseModel):
    OI_BUILDUP: int = Field(gt=0)
    TREND: int = Field(gt=0)
    OPTION_CHAIN: int = Field(gt=0)
    VOLUME: int = Field(gt=0)
    VWAP: int = Field(gt=0)
    SENTIMENT: int = Field(gt=0)
    IV_ANALYSIS: int = Field(gt=0)


class _RegimeMultiplierRow(BaseModel):
    OI_BUILDUP: float = Field(gt=0)
    TREND: float = Field(gt=0)
    OPTION_CHAIN: float = Field(gt=0)
    VOLUME: float = Field(gt=0)
    VWAP: float = Field(gt=0)
    SENTIMENT: float = Field(gt=0)
    IV_ANALYSIS: float = Field(gt=0)


class _RegimeMultipliersConfig(BaseModel):
    TRENDING_BULLISH: _RegimeMultiplierRow
    TRENDING_BEARISH: _RegimeMultiplierRow
    SIDEWAYS: _RegimeMultiplierRow
    HIGH_VOLATILITY: _RegimeMultiplierRow
    LOW_VOLATILITY: _RegimeMultiplierRow


class _WeightsConfig(BaseModel):
    base: _BaseWeightsConfig
    regime_multipliers: _RegimeMultipliersConfig


class _GatesConfig(BaseModel):
    min_score_to_execute: int = Field(gt=0)
    min_confidence_to_execute: int = Field(gt=0)
    data_completeness_min_pct: float = Field(gt=0)
    direction_conviction_min: float = Field(gt=0)


class _OIBuildupConfig(BaseModel):
    oi_change_strong_pct: float = Field(gt=0)
    price_change_min_pct: float = Field(gt=0)
    long_oi_multiplier: float = Field(gt=0)
    long_price_multiplier: float = Field(gt=0)
    covering_oi_multiplier: float = Field(gt=0)
    covering_price_multiplier: float = Field(gt=0)
    max_strong_score: float = Field(gt=0)
    max_weak_score: float = Field(gt=0)
    ambiguous_floor: float = Field(ge=0)
    pcr_bullish_low: float = Field(gt=0)
    pcr_bullish_high: float = Field(gt=0)
    pcr_strong_bullish: float = Field(gt=0)
    pcr_adjustment_against: float
    pcr_adjustment_with: float
    pcr_adjustment_strong: float
    fii_net_threshold_contracts: int = Field(gt=0)
    fii_adjustment: float
    max_pain_distance_pct: float = Field(gt=0)
    max_pain_adjustment: float
    dte_max_pain_dominant: int = Field(gt=0)
    ofi_bullish_pcr_min: float = Field(gt=0)
    ofi_bearish_pcr_max: float = Field(gt=0)
    ofi_confluence_bonus: float = Field(ge=0)


class _TrendConfig(BaseModel):
    adx_gate: float = Field(gt=0)
    adx_weak: float = Field(gt=0)
    adx_moderate: float = Field(gt=0)
    adx_strong: float = Field(gt=0)
    adx_very_strong: float = Field(gt=0)
    adx_score_gate_to_weak: float = Field(ge=0)
    adx_score_weak_to_moderate: float = Field(ge=0)
    adx_score_moderate_to_strong: float = Field(ge=0)
    adx_score_strong_to_very_strong: float = Field(ge=0)
    adx_score_very_strong: float = Field(ge=0)
    di_spread_no_signal: float = Field(ge=0)
    di_spread_moderate: float = Field(gt=0)
    di_spread_strong: float = Field(gt=0)
    di_spread_score_moderate: float = Field(ge=0)
    di_spread_score_strong: float = Field(ge=0)
    di_spread_score_very_strong: float = Field(ge=0)
    ema_full_alignment_score: float = Field(ge=0)
    ema_partial_20_50_score: float = Field(ge=0)
    ema_partial_20_200_score: float = Field(ge=0)
    supertrend_score: float = Field(ge=0)
    mtf_3_of_4_score: float = Field(ge=0)
    mtf_2_of_4_score: float = Field(ge=0)
    rsi_long_min: float = Field(gt=0)
    rsi_long_max: float = Field(gt=0)
    rsi_short_min: float = Field(gt=0)
    rsi_short_max: float = Field(gt=0)
    rsi_gate_score: float = Field(ge=0)


class _OptionChainConfig(BaseModel):
    iv_long_tier_1_max: float = Field(gt=0)
    iv_long_tier_2_max: float = Field(gt=0)
    iv_long_tier_3_max: float = Field(gt=0)
    iv_long_tier_4_max: float = Field(gt=0)
    iv_long_score_tier_1: float = Field(ge=0)
    iv_long_score_tier_2: float = Field(ge=0)
    iv_long_score_tier_3: float = Field(ge=0)
    iv_long_score_tier_4: float = Field(ge=0)
    iv_long_score_tier_5: float = Field(ge=0)
    iv_short_tier_1_max: float = Field(gt=0)
    iv_short_tier_2_max: float = Field(gt=0)
    iv_short_tier_3_max: float = Field(gt=0)
    iv_short_score_tier_1: float = Field(ge=0)
    iv_short_score_tier_2: float = Field(ge=0)
    iv_short_score_tier_3: float = Field(ge=0)
    iv_short_score_tier_4: float = Field(ge=0)
    iv_skew_threshold: float = Field(gt=0)
    iv_skew_score: float = Field(ge=0)
    gex_aligned_score: float
    gex_against_score: float
    gex_squeeze_score: float
    oi_wall_close_pct: float = Field(gt=0)
    oi_wall_medium_pct: float = Field(gt=0)
    oi_wall_far_pct: float = Field(gt=0)
    oi_wall_close_score: float
    oi_wall_medium_score: float
    oi_wall_far_score: float
    oi_wall_very_far_score: float
    pcr_trend_confirms_score: float
    pcr_trend_against_score: float


class _VolumeConfig(BaseModel):
    volume_ratio_tier_1: float = Field(gt=0)
    volume_ratio_tier_2: float = Field(gt=0)
    volume_ratio_tier_3: float = Field(gt=0)
    volume_ratio_tier_4: float = Field(gt=0)
    volume_ratio_score_1: float = Field(ge=0)
    volume_ratio_score_2: float = Field(ge=0)
    volume_ratio_score_3: float = Field(ge=0)
    volume_ratio_score_4: float = Field(ge=0)
    volume_ratio_score_5: float = Field(ge=0)
    divergence_penalty: float = Field(ge=0)
    obv_confirms_score: float = Field(ge=0)
    obv_against_score: float
    delta_confirms_score: float = Field(ge=0)
    delta_against_score: float
    vpoc_threshold_pct: float = Field(gt=0)
    vpoc_bonus: float = Field(ge=0)


class _VWAPConfig(BaseModel):
    mode_a_extreme_sigma: float = Field(gt=0)
    mode_a_strong_sigma: float = Field(gt=0)
    mode_a_moderate_sigma: float = Field(gt=0)
    mode_a_score_extreme: float = Field(ge=0)
    mode_a_score_strong: float = Field(ge=0)
    mode_a_score_moderate: float = Field(ge=0)
    mode_a_volume_ratio_extreme: float = Field(gt=0)
    mode_a_volume_ratio_strong: float = Field(gt=0)
    mode_a_rsi_long_extreme: float = Field(gt=0)
    mode_a_rsi_long_strong: float = Field(gt=0)
    mode_a_rsi_long_moderate: float = Field(gt=0)
    mode_a_rsi_short_extreme: float = Field(gt=0)
    mode_a_rsi_short_strong: float = Field(gt=0)
    mode_a_rsi_short_moderate: float = Field(gt=0)
    touch_count_multiplier_0: float = Field(gt=0)
    touch_count_multiplier_1: float = Field(gt=0)
    touch_count_multiplier_2: float = Field(gt=0)
    touch_count_multiplier_3_plus: float = Field(gt=0)
    mode_b_score_bouncing: float = Field(ge=0)
    mode_b_score_above_only: float = Field(ge=0)
    mode_b_score_caution: float = Field(ge=0)
    mode_b_bounce_proximity_sigma: float = Field(gt=0)


class _SentimentConfig(BaseModel):
    neutral_score: int = Field(ge=0)
    max_weight: int = Field(gt=0)
    strongly_bullish_min: int = Field(gt=0)
    bullish_min: int = Field(gt=0)
    neutral_min: int = Field(gt=0)
    bearish_min: int = Field(ge=0)
    strongly_bullish_long_score: float = Field(ge=0)
    strongly_bullish_short_score: float = Field(ge=0)
    bullish_long_score: float = Field(ge=0)
    bullish_short_score: float = Field(ge=0)
    neutral_long_score: float = Field(ge=0)
    neutral_short_score: float = Field(ge=0)
    bearish_long_score: float = Field(ge=0)
    bearish_short_score: float = Field(ge=0)
    strongly_bearish_long_score: float = Field(ge=0)
    strongly_bearish_short_score: float = Field(ge=0)
    max_age_minutes: int = Field(gt=0)


class _IVAnalysisConfig(BaseModel):
    iv_buy_percentile_max: float = Field(gt=0)
    iv_buy_score_max: float = Field(ge=0)
    iv_buy_percentile_mid: float = Field(gt=0)
    iv_buy_score_mid: float = Field(ge=0)
    iv_buy_percentile_low: float = Field(gt=0)
    iv_buy_score_low: float = Field(ge=0)
    iv_sell_percentile_min: float = Field(gt=0)
    iv_sell_score_max: float = Field(ge=0)
    iv_sell_percentile_mid: float = Field(gt=0)
    iv_sell_score_mid: float = Field(ge=0)
    iv_sell_percentile_low: float = Field(gt=0)
    iv_sell_score_low: float = Field(ge=0)
    hv_iv_ratio_buy_threshold: float = Field(gt=0)
    hv_iv_ratio_sell_threshold: float = Field(gt=0)
    hv_iv_bonus: float = Field(ge=0)
    vix_high_threshold: float = Field(gt=0)
    vix_short_vol_penalty: float = Field(ge=0)


class StrategyConfig(BaseModel):
    """All strategy scoring thresholds — source of truth is config/strategy.yaml."""

    version: str
    weights: _WeightsConfig
    gates: _GatesConfig
    oi_buildup: _OIBuildupConfig
    trend: _TrendConfig
    option_chain: _OptionChainConfig
    volume: _VolumeConfig
    vwap: _VWAPConfig
    sentiment: _SentimentConfig
    iv_analysis: _IVAnalysisConfig


@lru_cache(maxsize=1)
def load_strategy_config(path: Path = _CONFIG_PATH) -> StrategyConfig:
    """Load and validate strategy.yaml. Cached after first call."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return StrategyConfig.model_validate(raw)
