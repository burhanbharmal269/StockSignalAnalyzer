"""PositionOutcome — final result of a closed position."""

from __future__ import annotations

from enum import StrEnum


class PositionOutcome(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    TIME_EXIT = "TIME_EXIT"  # Closed at market close without hitting SL or target
    BREAKEVEN = "BREAKEVEN"  # Closed at entry price (stop moved to breakeven)
