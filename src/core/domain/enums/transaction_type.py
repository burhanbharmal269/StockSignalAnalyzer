"""TransactionType — BUY or SELL direction for an order."""

from __future__ import annotations

from enum import StrEnum


class TransactionType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
