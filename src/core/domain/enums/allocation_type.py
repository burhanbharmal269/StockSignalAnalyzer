"""AllocationType — scope of a CapitalAllocation."""

from __future__ import annotations

from enum import Enum


class AllocationType(str, Enum):
    """Scope for a capital allocation record.

    GLOBAL   : applied to the whole system / all strategies.
    STRATEGY : scoped to a specific StrategyType.
    PAPER    : paper-trading simulation allocation — never touches live capital.
    """

    GLOBAL = "GLOBAL"
    STRATEGY = "STRATEGY"
    PAPER = "PAPER"
