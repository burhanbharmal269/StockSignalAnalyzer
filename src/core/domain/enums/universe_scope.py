"""UniverseScope — which instruments a strategy universe may trade."""

from __future__ import annotations

from enum import Enum


class UniverseScope(str, Enum):
    """Instrument universe scope for strategies and allocations.

    NIFTY_ONLY  : only Nifty 50 index derivatives.
    TOP_50_FNO  : top 50 most-liquid F&O stocks.
    ALL_FNO     : all NSE F&O eligible instruments (system default).
    CUSTOM      : operator-defined instrument list.
    """

    NIFTY_ONLY = "NIFTY_ONLY"
    TOP_50_FNO = "TOP_50_FNO"
    ALL_FNO = "ALL_FNO"
    CUSTOM = "CUSTOM"
