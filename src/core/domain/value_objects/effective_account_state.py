"""EffectiveAccountState — resolved capital / risk limits for a single evaluation.

Replaces direct AccountState usage in the Risk Engine when the Capital
Allocation Framework is active.  The EffectiveAccountStateService produces
one of these per risk evaluation by blending broker account data with the
operator-configured allocation and risk profile.

This is a frozen VO — no mutation after creation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.domain.enums.capital_source_mode import CapitalSourceMode


@dataclass(frozen=True, kw_only=True)
class EffectiveAccountState:
    """Blended account snapshot for the Risk Engine.

    Attributes:
        capital_source_mode:    How broker and configured values were combined.
        broker_capital:         Live broker account_capital at evaluation time.
        broker_margin:          Live broker available_margin at evaluation time.
        configured_capital:     Operator-configured allocated_capital (from CapitalAllocation).
        configured_margin:      Operator-configured allocated_margin (None → use broker margin).
        effective_capital:      The value fed to PositionSizer as session_capital.
        effective_margin:       The value used for margin exposure limits.
        effective_daily_loss_limit:   Absolute INR cap derived from risk profile.
        effective_weekly_loss_limit:  Absolute INR cap derived from risk profile.
        effective_drawdown_limit:     Absolute INR cap derived from risk profile.
        effective_risk_per_trade:     Absolute INR risk allowed per trade.
        effective_max_open_positions: Integer cap from risk profile.
        risk_profile_id:        Source risk profile (None if no profile active).
        allocation_id:          Source capital allocation (None if no allocation active).
        portfolio_id:           Active portfolio (None if no portfolio active).
        captured_at:            When the broker snapshot was read.
    """

    capital_source_mode: CapitalSourceMode
    broker_capital: Decimal
    broker_margin: Decimal
    configured_capital: Decimal
    configured_margin: Decimal | None
    effective_capital: Decimal
    effective_margin: Decimal
    effective_daily_loss_limit: Decimal
    effective_weekly_loss_limit: Decimal
    effective_drawdown_limit: Decimal
    effective_risk_per_trade: Decimal
    effective_max_open_positions: int
    risk_profile_id: uuid.UUID | None
    allocation_id: uuid.UUID | None
    portfolio_id: uuid.UUID | None
    captured_at: datetime
