"""CapitalSourceMode — controls which capital figures feed the Risk Engine."""

from __future__ import annotations

from enum import Enum


class CapitalSourceMode(str, Enum):
    """How effective capital and margin are derived for position sizing.

    ACCOUNT  : use live broker account_capital / available_margin only.
    CONFIGURED: use allocation's allocated_capital / allocated_margin only.
    HYBRID   : use allocation's allocated_capital for sizing; broker's
               available_margin for exposure limits.  Default for all new systems.
    """

    ACCOUNT = "ACCOUNT"
    CONFIGURED = "CONFIGURED"
    HYBRID = "HYBRID"
