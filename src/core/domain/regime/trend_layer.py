"""TrendLayer — ADX + DI directional classification.

Stateless. Called once per bar. Returns a DirectionSignal dataclass.

Hard gate: ADX must be >= cfg.adx.trend_strong AND DI spread >= cfg.di_spread.hard_gate_min
for the gate to be considered "open" (i.e., a trending move is confirmed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.feature_snapshot import FeatureSnapshot
    from core.infrastructure.config.regime_config import RegimeConfig


@dataclass(frozen=True)
class DirectionSignal:
    """Output of TrendLayer evaluation."""

    direction: str          # BULLISH | BEARISH | NEUTRAL
    adx_strength: float     # raw ADX value (0.0 when not available)
    di_spread: float        # |DI+ - DI-| (0.0 when not available)
    is_gate_open: bool      # True when ADX >= trend_strong AND di_spread >= hard_gate_min


class TrendLayer:
    """Pure stateless ADX/DI trend classifier."""

    def __init__(self, config: RegimeConfig) -> None:
        self._cfg = config

    def evaluate(self, snapshot: FeatureSnapshot) -> DirectionSignal:
        """Classify direction from ADX, DI+, DI- fields in snapshot.

        Returns NEUTRAL when mandatory fields are missing.
        """
        adx = snapshot.adx
        di_plus = snapshot.di_plus
        di_minus = snapshot.di_minus

        if adx is None or di_plus is None or di_minus is None:
            return DirectionSignal(
                direction="NEUTRAL",
                adx_strength=0.0,
                di_spread=0.0,
                is_gate_open=False,
            )

        spread = abs(di_plus - di_minus)
        is_gate_open = (
            adx >= self._cfg.adx.trend_strong
            and spread >= self._cfg.di_spread.hard_gate_min
        )

        if not is_gate_open:
            return DirectionSignal(
                direction="NEUTRAL",
                adx_strength=adx,
                di_spread=spread,
                is_gate_open=False,
            )

        direction = "BULLISH" if di_plus > di_minus else "BEARISH"
        return DirectionSignal(
            direction=direction,
            adx_strength=adx,
            di_spread=spread,
            is_gate_open=True,
        )
