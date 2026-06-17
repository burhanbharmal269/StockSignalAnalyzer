"""IMarketRegimeEngine — extension point for multiple regime implementations.

Future strategies consume this interface, not the concrete service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.feature_snapshot import FeatureSnapshot
    from core.domain.value_objects.regime_snapshot import RegimeSnapshot


class IMarketRegimeEngine(ABC):
    """Contract that any regime classification engine must satisfy."""

    @abstractmethod
    async def evaluate(self, snapshot: FeatureSnapshot) -> RegimeSnapshot:
        """Evaluate market regime from pre-computed feature snapshot.

        Args:
            snapshot: Indicator values for one (instrument, timeframe) bar.

        Returns:
            RegimeSnapshot with primary regime, confidence, and metadata.
        """

    @abstractmethod
    async def update_features(self, snapshot: FeatureSnapshot) -> None:
        """Push a fresh FeatureSnapshot into the engine cache.

        Called by the Feature Engineering pipeline before each candle close.
        The engine caches the snapshot keyed by (instrument_token, timeframe).
        """
