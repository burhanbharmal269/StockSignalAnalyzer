"""RegimeSnapshot — immutable output contract of the Market Regime Engine.

Strategies and downstream consumers depend only on this value object,
never on internal engine state. This design allows multiple engine
implementations behind IMarketRegimeEngine without breaking consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.domain.enums.market_regime import MarketRegime


@dataclass(frozen=True)
class RegimeSnapshot:
    """Complete regime classification result for one (instrument, timeframe) bar.

    Attributes:
        primary_regime:       The authoritative regime for strategy consumption.
        secondary_regime:     Optional modifier (e.g., HIGH_VOLATILITY when
                              trending in a volatile market).
        direction_layer:      Raw output from TrendLayer evaluation.
        volatility_layer:     Raw output from VolatilityLayer evaluation.
        confidence:           0–100 integer — probability-proxy for regime strength.
        score:                Raw weighted score before clamping to 0–100.
        stability_score:      0.0–1.0 — ratio of observed duration to minimum
                              required bars; 1.0 = fully confirmed.
        regime_duration_bars: Number of consecutive bars in current primary regime.
        transition_signal:    True if a regime change just occurred this bar.
        explanation:          Human-readable list of the factors that drove the
                              classification (for logging / debugging).
        evaluated_at:         UTC timestamp of the bar that triggered this snapshot.
    """

    primary_regime: MarketRegime
    secondary_regime: MarketRegime | None = None
    direction_layer: str = "NEUTRAL"        # BULLISH | BEARISH | NEUTRAL
    volatility_layer: str = "NORMAL"        # HIGH | NORMAL | LOW
    confidence: int = 0                     # 0–100
    score: float = 0.0
    stability_score: float = 0.0            # 0.0–1.0
    regime_duration_bars: int = 0
    transition_signal: bool = False
    explanation: tuple[str, ...] = field(default_factory=tuple)
    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    instrument_token: int = 0
    timeframe: str = ""
