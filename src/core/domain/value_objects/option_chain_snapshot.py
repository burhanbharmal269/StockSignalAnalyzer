"""OptionChainSnapshot — immutable bag of option chain market data.

Refreshed every ~60 seconds from NSE REST feed. All fields Optional
so the domain handles partial data gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class OptionChainSnapshot:
    """Live option chain data used by the scoring components.

    Separate from FeatureSnapshot because it refreshes on a different cadence
    (~60 s REST) than candle-derived indicators (15-min candle close).
    """

    # IV surface
    iv_percentile: float | None = None    # rolling 252-day percentile (0-100)
    iv_skew: float | None = None          # put_iv - call_iv (OTM 5-10%)

    # Gamma Exposure
    gex_positive: bool | None = None      # True = market makers net long gamma
    gex_strike: float | None = None       # Strike with highest GEX concentration

    # OI walls
    nearest_call_wall_distance_pct: float | None = None  # % distance above price
    nearest_put_wall_distance_pct: float | None = None   # % distance below price

    # PCR trend
    pcr_trend: str | None = None          # "RISING" | "FALLING" | "STABLE"

    # Reference
    atm_strike: float | None = None

    snapshot_timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
