"""LiveTradingSafetyService — capital ramp-up and safety gate for live trading.

Implements a 4-stage capital ramp-up:
  Stage 1: ₹5,000
  Stage 2: ₹10,000
  Stage 3: ₹25,000
  Stage 4: ₹50,000

Promotion between stages requires passing configurable performance thresholds:
  - min_win_rate (default: 55%)
  - max_drawdown_pct (default: 5%)
  - min_trades (default: 20)
  - min_consecutive_profitable_days (default: 3)

Safety rules lock trading when:
  - Win rate drops below threshold
  - Drawdown exceeds threshold
  - Consecutive losses exceed threshold
  - Broker instability detected

Architecture:
  - State persisted in live_trading_ramp_up table
  - Stage transitions are atomic DB writes
  - Lock/unlock via explicit admin API
  - Kill switch activated on safety breach
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)

# Stage configuration: (capital_inr, label)
_STAGES: dict[int, Decimal] = {
    1: Decimal("5000"),
    2: Decimal("10000"),
    3: Decimal("25000"),
    4: Decimal("50000"),
}

_MAX_STAGE = max(_STAGES)


@dataclass
class RampUpState:
    ramp_id: int
    current_stage: int
    stage_capital: Decimal
    stage_entered_at: datetime
    promoted_at: datetime | None
    locked: bool
    lock_reason: str | None
    performance_snapshot: dict | None
    created_at: datetime
    updated_at: datetime

    @property
    def effective_capital(self) -> Decimal:
        return _STAGES.get(self.current_stage, self.stage_capital)

    @property
    def at_max_stage(self) -> bool:
        return self.current_stage >= _MAX_STAGE


@dataclass
class PromotionEligibility:
    eligible: bool
    current_stage: int
    next_stage: int | None
    next_capital: Decimal | None
    reason: str
    win_rate: float
    drawdown_pct: float
    trades_completed: int
    consecutive_profitable_days: int


@dataclass
class SafetyCheck:
    passed: bool
    reason: str
    locked: bool


class LiveTradingSafetyService:
    """Capital ramp-up state machine and safety gate."""

    # Promotion thresholds (configurable per stage)
    _MIN_WIN_RATE = 0.55
    _MAX_DRAWDOWN_PCT = 5.0
    _MIN_TRADES = 20
    _MIN_PROFITABLE_DAYS = 3
    _MAX_CONSECUTIVE_LOSSES = 5

    def __init__(self, ramp_up_repository) -> None:
        self._repo = ramp_up_repository

    # ------------------------------------------------------------------
    # Read current state
    # ------------------------------------------------------------------

    async def get_state(self) -> RampUpState | None:
        """Return the current ramp-up state (None if not initialised)."""
        return await self._repo.get_current()

    async def initialize(self) -> RampUpState:
        """Create a new Stage 1 ramp-up state (idempotent — returns existing if present)."""
        existing = await self._repo.get_current()
        if existing is not None:
            return existing
        return await self._repo.create_initial()

    # ------------------------------------------------------------------
    # Promotion evaluation
    # ------------------------------------------------------------------

    async def check_promotion_eligibility(
        self,
        win_rate: float,
        drawdown_pct: float,
        trades_completed: int,
        consecutive_profitable_days: int,
    ) -> PromotionEligibility:
        """Evaluate whether current stage qualifies for promotion."""
        state = await self._repo.get_current()
        if state is None:
            return PromotionEligibility(
                eligible=False,
                current_stage=0,
                next_stage=None,
                next_capital=None,
                reason="Ramp-up not initialized",
                win_rate=win_rate,
                drawdown_pct=drawdown_pct,
                trades_completed=trades_completed,
                consecutive_profitable_days=consecutive_profitable_days,
            )

        if state.at_max_stage:
            return PromotionEligibility(
                eligible=False,
                current_stage=state.current_stage,
                next_stage=None,
                next_capital=None,
                reason="Already at maximum stage",
                win_rate=win_rate,
                drawdown_pct=drawdown_pct,
                trades_completed=trades_completed,
                consecutive_profitable_days=consecutive_profitable_days,
            )

        if state.locked:
            return PromotionEligibility(
                eligible=False,
                current_stage=state.current_stage,
                next_stage=state.current_stage + 1,
                next_capital=_STAGES.get(state.current_stage + 1),
                reason=f"Trading locked: {state.lock_reason}",
                win_rate=win_rate,
                drawdown_pct=drawdown_pct,
                trades_completed=trades_completed,
                consecutive_profitable_days=consecutive_profitable_days,
            )

        # Check all thresholds
        failures = []
        if win_rate < self._MIN_WIN_RATE:
            failures.append(f"win_rate {win_rate:.1%} < {self._MIN_WIN_RATE:.1%}")
        if drawdown_pct > self._MAX_DRAWDOWN_PCT:
            failures.append(f"drawdown {drawdown_pct:.2f}% > {self._MAX_DRAWDOWN_PCT:.2f}%")
        if trades_completed < self._MIN_TRADES:
            failures.append(f"trades {trades_completed} < {self._MIN_TRADES}")
        if consecutive_profitable_days < self._MIN_PROFITABLE_DAYS:
            failures.append(
                f"profitable_days {consecutive_profitable_days} < {self._MIN_PROFITABLE_DAYS}"
            )

        next_stage = state.current_stage + 1
        next_capital = _STAGES.get(next_stage)

        if failures:
            return PromotionEligibility(
                eligible=False,
                current_stage=state.current_stage,
                next_stage=next_stage,
                next_capital=next_capital,
                reason="; ".join(failures),
                win_rate=win_rate,
                drawdown_pct=drawdown_pct,
                trades_completed=trades_completed,
                consecutive_profitable_days=consecutive_profitable_days,
            )

        return PromotionEligibility(
            eligible=True,
            current_stage=state.current_stage,
            next_stage=next_stage,
            next_capital=next_capital,
            reason="All promotion thresholds met",
            win_rate=win_rate,
            drawdown_pct=drawdown_pct,
            trades_completed=trades_completed,
            consecutive_profitable_days=consecutive_profitable_days,
        )

    async def promote(
        self,
        win_rate: float,
        drawdown_pct: float,
        trades_completed: int,
        consecutive_profitable_days: int,
    ) -> RampUpState:
        """Promote to next stage if eligible. Raises ValueError if not eligible."""
        eligibility = await self.check_promotion_eligibility(
            win_rate, drawdown_pct, trades_completed, consecutive_profitable_days
        )
        if not eligibility.eligible:
            raise ValueError(f"Not eligible for promotion: {eligibility.reason}")

        state = await self._repo.promote_stage(
            performance_snapshot={
                "win_rate": win_rate,
                "drawdown_pct": drawdown_pct,
                "trades_completed": trades_completed,
                "consecutive_profitable_days": consecutive_profitable_days,
                "promoted_at": datetime.now(UTC).isoformat(),
            }
        )
        _log.info(
            "live_trading.promoted stage=%d capital=%s",
            state.current_stage, state.stage_capital
        )
        return state

    # ------------------------------------------------------------------
    # Safety checks (lock trading on breach)
    # ------------------------------------------------------------------

    async def evaluate_safety(
        self,
        *,
        win_rate: float,
        drawdown_pct: float,
        consecutive_losses: int,
        broker_consecutive_failures: int,
    ) -> SafetyCheck:
        """Check all safety rules; lock if any is breached."""
        state = await self._repo.get_current()
        if state is None:
            return SafetyCheck(passed=True, reason="Not initialized", locked=False)

        if state.locked:
            return SafetyCheck(
                passed=False,
                reason=f"Already locked: {state.lock_reason}",
                locked=True,
            )

        breaches = []
        if win_rate < 0.40:
            breaches.append(f"win_rate critically low: {win_rate:.1%}")
        if drawdown_pct > 10.0:
            breaches.append(f"drawdown excessive: {drawdown_pct:.2f}%")
        if consecutive_losses > self._MAX_CONSECUTIVE_LOSSES:
            breaches.append(f"consecutive_losses={consecutive_losses} > {self._MAX_CONSECUTIVE_LOSSES}")
        if broker_consecutive_failures >= 5:
            breaches.append(f"broker_consecutive_failures={broker_consecutive_failures}")

        if breaches:
            reason = "; ".join(breaches)
            await self._repo.lock(reason)
            _log.critical("live_trading.safety_locked reason=%s", reason)
            return SafetyCheck(passed=False, reason=reason, locked=True)

        return SafetyCheck(passed=True, reason="All safety checks passed", locked=False)

    async def lock(self, reason: str) -> None:
        """Manually lock trading (admin action)."""
        await self._repo.lock(reason)
        _log.warning("live_trading.manually_locked reason=%s", reason)

    async def unlock(self, reason: str = "admin_unlock") -> None:
        """Unlock trading (admin action)."""
        await self._repo.unlock()
        _log.info("live_trading.unlocked reason=%s", reason)
