"""Pydantic-backed loader for config/regime.yaml.

Pattern mirrors risk_config.py — YAML on disk, Pydantic for validation,
factory function returns a singleton-safe instance.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_CONFIG_PATH = Path(__file__).parents[4] / "config" / "regime.yaml"


class _AdxConfig(BaseModel):
    trend_strong: float = Field(gt=0)
    trend_weak: float = Field(gt=0)
    sideways: float = Field(gt=0)


class _VixConfig(BaseModel):
    panic: float = Field(gt=0)
    high: float = Field(gt=0)
    elevated: float = Field(gt=0)
    low: float = Field(gt=0)
    very_low: float = Field(gt=0)


class _AtrRatioConfig(BaseModel):
    very_high: float = Field(gt=0)
    high: float = Field(gt=0)
    moderate_high: float = Field(gt=0)
    low: float = Field(gt=0)
    very_low: float = Field(gt=0)
    very_very_low: float = Field(gt=0)


class _BbWidthConfig(BaseModel):
    low: float = Field(gt=0)
    very_low: float = Field(gt=0)
    extreme_low: float = Field(gt=0)


class _IvPercentileConfig(BaseModel):
    extreme: float = Field(gt=0)
    very_high: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    very_low: float = Field(gt=0)


class _AdvanceDeclineConfig(BaseModel):
    strong_bull: float = Field(gt=0)
    bull: float = Field(gt=0)
    neutral_upper: float = Field(gt=0)
    neutral_lower: float = Field(gt=0)
    bear: float = Field(gt=0)
    strong_bear: float = Field(gt=0)
    panic_high: float = Field(gt=0)
    panic_low: float = Field(gt=0)


class _PcrConfig(BaseModel):
    neutral_upper: float = Field(gt=0)
    neutral_lower: float = Field(gt=0)


class _DiSpreadConfig(BaseModel):
    hard_gate_min: float = Field(gt=0)
    strong: float = Field(gt=0)


class _Nifty200DmaConfig(BaseModel):
    bull_strong: float = Field(gt=0)
    bull: float = Field(gt=0)
    bear: float = Field(gt=0)


class _ConfidenceConfig(BaseModel):
    full_multiplier: int = Field(gt=0)
    blend_75_pct: int = Field(gt=0)
    blend_40_pct: int = Field(gt=0)


class _ActivationConfig(BaseModel):
    trending: int = Field(gt=0)
    sideways: int = Field(gt=0)
    high_volatility: int = Field(gt=0)
    low_volatility: int = Field(gt=0)


class _TransitionMinBarsConfig(BaseModel):
    sideways_to_trending: int = Field(gt=0)
    trending_to_sideways: int = Field(gt=0)
    any_to_high_vol: int = Field(gt=0)
    high_vol_exit: int = Field(gt=0)
    any_to_low_vol: int = Field(gt=0)


class RegimeConfig(BaseModel):
    """All market regime thresholds — source of truth is config/regime.yaml."""

    version: str
    adx: _AdxConfig
    vix: _VixConfig
    atr_ratio: _AtrRatioConfig
    bb_width_percentile: _BbWidthConfig
    iv_percentile: _IvPercentileConfig
    advance_decline: _AdvanceDeclineConfig
    pcr: _PcrConfig
    di_spread: _DiSpreadConfig
    nifty_above_200dma: _Nifty200DmaConfig
    fii_consecutive_days: int = Field(gt=0)
    confidence: _ConfidenceConfig
    activation: _ActivationConfig
    transition_min_bars: _TransitionMinBarsConfig


@lru_cache(maxsize=1)
def load_regime_config(path: Path = _CONFIG_PATH) -> RegimeConfig:
    """Load and validate regime.yaml. Cached after first call."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return RegimeConfig.model_validate(raw)
