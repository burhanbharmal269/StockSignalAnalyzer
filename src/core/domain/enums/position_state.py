"""PositionState — open/closed lifecycle for a position."""

from __future__ import annotations

from enum import StrEnum


class PositionState(StrEnum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"

    @property
    def is_terminal(self) -> bool:
        return self == PositionState.CLOSED
