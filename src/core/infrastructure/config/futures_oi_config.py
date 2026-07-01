"""Configuration for Phase 21 — Futures OI integration.

All parameters are configurable; nothing is hardcoded in the service layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FuturesOIConfig:
    """Configurable parameters for Futures OI polling and intelligence."""

    # Master switch — set False to disable FUT inclusion and OI cache updates.
    oi_poll_enabled: bool = True

    # Sequential OI direction thresholds (percent change between consecutive polls).
    # Values outside [-threshold, +threshold] are classified as Increasing or Falling.
    oi_direction_threshold: float = 0.5

    # Cache TTL in seconds: OI snapshot older than this is treated as stale.
    # Slightly above the 5-minute poll interval to tolerate a missed poll.
    oi_cache_ttl: int = 600

    # Contract preference strategy (currently only "nearest_monthly" is supported).
    future_contract_preference: str = "nearest_monthly"

    # Rolling observation window sizes (number of poll intervals).
    rolling_window_sizes: list[int] = field(default_factory=lambda: [5, 15, 60])
