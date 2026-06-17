"""Domain events emitted by the Market Regime Engine.

Topic routing (see docs/11_EVENT_SYSTEM.md):
  MarketRegimeEvaluatedEvent → features.regime.detected   (every bar)
  MarketRegimeChangedEvent   → features.regime.changed    (transitions only)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.domain.enums.market_regime import MarketRegime
from core.domain.events.base import DomainEvent


@dataclass(frozen=True)
class MarketRegimeEvaluatedEvent(DomainEvent):
    """Published every time the regime engine evaluates a completed bar.

    Always emitted — consumers that only care about regime changes should
    subscribe to MarketRegimeChangedEvent instead.
    """

    instrument_token: int = 0
    timeframe: str = ""
    primary_regime: MarketRegime = MarketRegime.SIDEWAYS
    secondary_regime: MarketRegime | None = None
    confidence: int = 0
    stability_score: float = 0.0
    regime_duration_bars: int = 0
    transition_signal: bool = False
    direction_layer: str = "NEUTRAL"
    volatility_layer: str = "NORMAL"
    explanation: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MarketRegimeChangedEvent(DomainEvent):
    """Published only when the primary regime transitions to a new value.

    Downstream services (e.g., strategy engine) subscribe here to react
    to regime transitions without processing every evaluated bar.
    """

    instrument_token: int = 0
    timeframe: str = ""
    previous_regime: MarketRegime = MarketRegime.SIDEWAYS
    new_regime: MarketRegime = MarketRegime.SIDEWAYS
    confidence: int = 0
    stability_score: float = 0.0
    regime_duration_bars: int = 0
