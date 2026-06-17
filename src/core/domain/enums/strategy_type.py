"""StrategyType — classification of the strategy that generated a signal."""

from __future__ import annotations

from enum import StrEnum


class StrategyType(StrEnum):
    DIRECTIONAL = "DIRECTIONAL"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"
    RANGE_BOUND = "RANGE_BOUND"
    VOLATILITY = "VOLATILITY"
    OI_DRIVEN = "OI_DRIVEN"
