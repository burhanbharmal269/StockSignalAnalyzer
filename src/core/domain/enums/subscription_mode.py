"""SubscriptionMode — controls the data density of each tick stream.

Reference: docs/12_WEBSOCKET_MANAGER.md §Interface Definition
"""

from __future__ import annotations

from enum import StrEnum


class SubscriptionMode(StrEnum):
    """Broker-agnostic subscription modes.

    Each broker adapter maps these to its own internal mode strings.
    The application layer never references broker-specific mode names.
    """

    LTP = "LTP"      # last traded price only (minimal bandwidth)
    QUOTE = "QUOTE"  # LTP + OHLC + volume + best bid/ask
    FULL = "FULL"    # QUOTE + market depth (5 levels) + OI (FnO)
