"""OI Regime domain value objects — Phase 21.1 Part 1.

Classifies each FuturesOI observation into one of 6 directional regimes
using price change and OI change as inputs.  This module is pure domain
logic — no I/O, no async, no side effects.

Definitions (standard market interpretation):
  Price↑ + OI↑  → Long Build-up     (new longs accumulating)
  Price↓ + OI↑  → Short Build-up    (new shorts accumulating)
  Price↓ + OI↓  → Long Unwinding    (longs exiting)
  Price↑ + OI↓  → Short Covering    (shorts exiting)
  Within thresholds → Neutral
  Insufficient data → Unknown
"""
from __future__ import annotations

from enum import Enum


class OIRegime(str, Enum):
    LONG_BUILDUP   = "Long Build-up"
    SHORT_BUILDUP  = "Short Build-up"
    LONG_UNWINDING = "Long Unwinding"
    SHORT_COVERING = "Short Covering"
    NEUTRAL        = "Neutral"
    UNKNOWN        = "Unknown"


class OIQualityTier(str, Enum):
    EXCELLENT   = "Excellent"
    GOOD        = "Good"
    FAIR        = "Fair"
    POOR        = "Poor"
    UNAVAILABLE = "Unavailable"


def classify_oi_regime(
    price_change_pct: float | None,
    oi_change_pct: float | None,
    price_threshold: float = 0.1,
    oi_threshold: float = 0.5,
) -> OIRegime:
    """Classify price+OI combination into a directional regime.

    Args:
        price_change_pct:  % change in underlying/futures price since last poll.
        oi_change_pct:     % change in futures OI since last poll (from FuturesOIService).
        price_threshold:   Minimum absolute % price move to leave Neutral.
        oi_threshold:      Minimum absolute % OI move to leave Neutral.

    Returns:
        OIRegime enum value — never raises.
    """
    if price_change_pct is None or oi_change_pct is None:
        return OIRegime.UNKNOWN

    price_up = price_change_pct >  price_threshold
    price_dn = price_change_pct < -price_threshold
    oi_up    = oi_change_pct    >  oi_threshold
    oi_dn    = oi_change_pct    < -oi_threshold

    if price_up and oi_up:
        return OIRegime.LONG_BUILDUP
    if price_dn and oi_up:
        return OIRegime.SHORT_BUILDUP
    if price_dn and oi_dn:
        return OIRegime.LONG_UNWINDING
    if price_up and oi_dn:
        return OIRegime.SHORT_COVERING
    return OIRegime.NEUTRAL
