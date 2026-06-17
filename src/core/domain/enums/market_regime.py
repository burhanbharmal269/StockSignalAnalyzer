"""MarketRegime — 5-value regime classification.

Source: docs/20_MARKET_REGIME_ENGINE.md.
"""

from __future__ import annotations

from enum import StrEnum


class MarketRegime(StrEnum):
    TRENDING_BULLISH = "TRENDING_BULLISH"
    TRENDING_BEARISH = "TRENDING_BEARISH"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
