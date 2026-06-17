"""OrderType — how the order is to be executed at the exchange."""

from __future__ import annotations

from enum import StrEnum


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_MARKET = "SL_MARKET"
