"""VolatilityLayer — India VIX + ATR ratio volatility classification.

Stateless. Called once per bar. Returns a VolatilitySignal dataclass.

VIX is the primary signal. ATR ratio acts as a confirming / secondary signal.
Panic is flagged when VIX > cfg.vix.panic (Rule 1 override).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.feature_snapshot import FeatureSnapshot
    from core.infrastructure.config.regime_config import RegimeConfig


@dataclass(frozen=True)
class VolatilitySignal:
    """Output of VolatilityLayer evaluation."""

    level: str              # HIGH | NORMAL | LOW
    vix_value: float        # raw India VIX (0.0 when not available)
    atr_ratio_value: float  # raw ATR ratio (0.0 when not available)
    is_panic: bool          # True when VIX > cfg.vix.panic (Rule 1 override)


class VolatilityLayer:
    """Pure stateless VIX/ATR volatility classifier."""

    def __init__(self, config: RegimeConfig) -> None:
        self._cfg = config

    def evaluate(self, snapshot: FeatureSnapshot) -> VolatilitySignal:
        """Classify volatility level from VIX and ATR ratio.

        Returns NORMAL when mandatory fields are missing.
        """
        vix = snapshot.india_vix
        atr_ratio = snapshot.atr_ratio

        vix_val = vix if vix is not None else 0.0
        atr_val = atr_ratio if atr_ratio is not None else 0.0

        if vix is None:
            return VolatilitySignal(
                level="NORMAL",
                vix_value=0.0,
                atr_ratio_value=atr_val,
                is_panic=False,
            )

        cfg = self._cfg

        # Panic override — VIX above panic threshold
        if vix > cfg.vix.panic:
            return VolatilitySignal(
                level="HIGH",
                vix_value=vix_val,
                atr_ratio_value=atr_val,
                is_panic=True,
            )

        # High volatility — VIX above high threshold
        if vix > cfg.vix.high:
            return VolatilitySignal(
                level="HIGH",
                vix_value=vix_val,
                atr_ratio_value=atr_val,
                is_panic=False,
            )

        # Also HIGH if ATR ratio is very elevated even when VIX is moderate
        if atr_ratio is not None and atr_ratio > cfg.atr_ratio.very_high:
            return VolatilitySignal(
                level="HIGH",
                vix_value=vix_val,
                atr_ratio_value=atr_val,
                is_panic=False,
            )

        # Low volatility — VIX very low (Rule 5)
        if vix < cfg.vix.very_low:
            return VolatilitySignal(
                level="LOW",
                vix_value=vix_val,
                atr_ratio_value=atr_val,
                is_panic=False,
            )

        # Low volatility — VIX below low AND ATR ratio compressed (Rule 5b)
        if (
            vix < cfg.vix.low
            and atr_ratio is not None
            and atr_ratio < cfg.atr_ratio.low
        ):
            return VolatilitySignal(
                level="LOW",
                vix_value=vix_val,
                atr_ratio_value=atr_val,
                is_panic=False,
            )

        return VolatilitySignal(
            level="NORMAL",
            vix_value=vix_val,
            atr_ratio_value=atr_val,
            is_panic=False,
        )
