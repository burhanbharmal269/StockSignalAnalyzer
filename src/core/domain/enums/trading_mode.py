"""TradingMode — live vs paper (simulation) mode."""

from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    LIVE = "LIVE"
    PAPER = "PAPER"
