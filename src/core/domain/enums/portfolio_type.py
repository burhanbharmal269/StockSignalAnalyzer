"""PortfolioType — classifies a Portfolio instance."""

from __future__ import annotations

from enum import Enum


class PortfolioType(str, Enum):
    """Portfolio classification.

    DEFAULT : the system-default portfolio automatically created for new users.
    PAPER   : paper-trading portfolio; positions never route to live broker.
    LIVE    : live-trading portfolio; positions route through the live broker.
    """

    DEFAULT = "DEFAULT"
    PAPER = "PAPER"
    LIVE = "LIVE"
