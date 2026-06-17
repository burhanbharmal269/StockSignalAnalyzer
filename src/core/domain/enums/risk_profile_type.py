"""RiskProfileType — preset risk-parameter bundles."""

from __future__ import annotations

from enum import Enum


class RiskProfileType(str, Enum):
    """Built-in risk-parameter presets.

    CONSERVATIVE : tight limits, small size — 1% risk/trade, 2% daily loss cap.
    MODERATE     : balanced defaults — 2% risk/trade, 3% daily loss cap (system default).
    AGGRESSIVE   : wider limits, larger size — 3% risk/trade, 5% daily loss cap.
    CUSTOM       : all parameters set explicitly by the operator.
    """

    CONSERVATIVE = "CONSERVATIVE"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"
    CUSTOM = "CUSTOM"
