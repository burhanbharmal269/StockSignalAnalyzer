"""Market Regime Engine — domain computation components.

Public API:
    TrendLayer          — ADX/DI-based direction classification
    VolatilityLayer     — VIX/ATR-based volatility classification
    RegimeResolver      — 8-rule priority matrix → MarketRegime
    RegimeSmoother      — α-blending anti-whipsaw stateful tracker
    ConfidenceCalculator — per-regime scoring tables
"""

from core.domain.regime.confidence_calculator import ConfidenceCalculator
from core.domain.regime.regime_resolver import RegimeResolver
from core.domain.regime.regime_smoother import RegimeSmoother
from core.domain.regime.trend_layer import TrendLayer
from core.domain.regime.volatility_layer import VolatilityLayer

__all__ = [
    "ConfidenceCalculator",
    "RegimeResolver",
    "RegimeSmoother",
    "TrendLayer",
    "VolatilityLayer",
]
