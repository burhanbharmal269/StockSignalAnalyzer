"""AccountState — frozen value object for the account snapshot used during risk evaluation.

Captured once per evaluation via asyncio.gather(); frozen for the lifetime of the
RiskRequest flow.  All sizing calculations use session_capital (frozen at 09:15 IST),
not the live account_capital.

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.domain.exceptions.risk import RiskInvariantError

_VALID_MULTIPLIERS: frozenset[float] = frozenset({0.0, 0.5, 1.0})
_VALID_MODES: frozenset[str] = frozenset({"LIVE", "PAPER", "BLOCKED"})


@dataclass(frozen=True, kw_only=True)
class AccountState:
    """Immutable snapshot of the trading account at evaluation time.

    Attributes:
        account_capital:          Total account capital (session-anchored baseline).
        session_capital:          Capital frozen at 09:15 IST; used for all position sizing.
        available_margin:         Margin currently available for new positions.
        used_margin:              Margin already consumed by open positions.
        margin_utilization_pct:   used_margin / account_capital × 100.
        daily_pnl:                Realised + MTM P&L since market open (negative = loss).
        daily_loss_consumed_pct:  abs(daily_pnl) / daily_loss_limit_abs × 100 (0 when positive).
        weekly_pnl:               Rolling 5-trading-day P&L.
        weekly_loss_consumed_pct: abs(weekly_pnl) / weekly_loss_limit_abs × 100 (0 when positive).
        drawdown_from_hwm_pct:    (HWM − current_value) / HWM × 100.
        open_positions_count:     Count of currently open positions.
        position_size_multiplier: Graduated-response multiplier: 1.0 | 0.5 | 0.0.
        trading_mode:             Current trading mode: LIVE | PAPER | BLOCKED.
        captured_at:              UTC timestamp when this snapshot was read from Redis.
    """

    account_capital: Decimal
    session_capital: Decimal
    available_margin: Decimal
    used_margin: Decimal
    margin_utilization_pct: float
    daily_pnl: Decimal
    daily_loss_consumed_pct: float
    weekly_pnl: Decimal
    weekly_loss_consumed_pct: float
    drawdown_from_hwm_pct: float
    open_positions_count: int
    position_size_multiplier: float
    trading_mode: str
    captured_at: datetime

    def __post_init__(self) -> None:
        if self.account_capital < Decimal(0):
            raise RiskInvariantError(
                f"account_capital must be >= 0, got {self.account_capital}"
            )
        if self.session_capital < Decimal(0):
            raise RiskInvariantError(
                f"session_capital must be >= 0, got {self.session_capital}"
            )
        if self.available_margin < Decimal(0):
            raise RiskInvariantError(
                f"available_margin must be >= 0, got {self.available_margin}"
            )
        if self.used_margin < Decimal(0):
            raise RiskInvariantError(
                f"used_margin must be >= 0, got {self.used_margin}"
            )
        if self.margin_utilization_pct < 0.0:
            raise RiskInvariantError(
                f"margin_utilization_pct must be >= 0, got {self.margin_utilization_pct}"
            )
        if self.daily_loss_consumed_pct < 0.0:
            raise RiskInvariantError(
                f"daily_loss_consumed_pct must be >= 0, got {self.daily_loss_consumed_pct}"
            )
        if self.weekly_loss_consumed_pct < 0.0:
            raise RiskInvariantError(
                f"weekly_loss_consumed_pct must be >= 0, got {self.weekly_loss_consumed_pct}"
            )
        if self.drawdown_from_hwm_pct < 0.0:
            raise RiskInvariantError(
                f"drawdown_from_hwm_pct must be >= 0, got {self.drawdown_from_hwm_pct}"
            )
        if self.open_positions_count < 0:
            raise RiskInvariantError(
                f"open_positions_count must be >= 0, got {self.open_positions_count}"
            )
        if self.position_size_multiplier not in _VALID_MULTIPLIERS:
            raise RiskInvariantError(
                f"position_size_multiplier must be one of {sorted(_VALID_MULTIPLIERS)}, "
                f"got {self.position_size_multiplier}"
            )
        if self.trading_mode not in _VALID_MODES:
            raise RiskInvariantError(
                f"trading_mode must be one of {sorted(_VALID_MODES)!r}, "
                f"got {self.trading_mode!r}"
            )
