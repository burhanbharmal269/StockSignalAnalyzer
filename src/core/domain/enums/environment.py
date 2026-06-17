"""Trading environment enumeration used by the domain layer.

Kept separate from infrastructure config so domain entities can express
which environment they were created in without importing infrastructure.
"""

from enum import StrEnum


class TradingMode(StrEnum):
    """Whether the platform is executing real or simulated orders."""

    LIVE = "LIVE"
    PAPER = "PAPER"
