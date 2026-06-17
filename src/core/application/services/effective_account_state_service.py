"""EffectiveAccountStateService — blends broker account data with the capital framework.

Produces an EffectiveAccountState used by the Risk Engine and for auditability.
Also exposes to_account_state() which converts the effective values back into an
AccountState with effective_capital substituted for session_capital, allowing the
rest of the Risk Engine to operate without any changes.

Resolution rules per CapitalSourceMode:
  ACCOUNT    : effective_capital = broker_capital, effective_margin = broker_margin
  CONFIGURED : effective_capital = configured_capital, effective_margin = configured_margin
               (falls back to broker_margin when configured_margin is None)
  HYBRID     : effective_capital = configured_capital (if set and > 0) else broker_capital
               effective_margin = broker_margin  (always from broker)
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.interfaces.i_account_state_repository import IAccountStateRepository
from core.domain.interfaces.i_capital_allocation_repository import ICapitalAllocationRepository
from core.domain.interfaces.i_portfolio_repository import IPortfolioRepository
from core.domain.interfaces.i_risk_profile_repository import IRiskProfileRepository
from core.domain.risk.account_state import AccountState
from core.domain.value_objects.effective_account_state import EffectiveAccountState
from core.infrastructure.logging.setup import get_logger

_log = get_logger(__name__)

_ZERO = Decimal(0)


class EffectiveAccountStateService:
    def __init__(
        self,
        account_state_repo: IAccountStateRepository,
        risk_profile_repo: IRiskProfileRepository,
        capital_allocation_repo: ICapitalAllocationRepository,
        portfolio_repo: IPortfolioRepository,
    ) -> None:
        self._account_repo = account_state_repo
        self._profile_repo = risk_profile_repo
        self._allocation_repo = capital_allocation_repo
        self._portfolio_repo = portfolio_repo

    async def resolve(self) -> EffectiveAccountState:
        """Build the EffectiveAccountState from all active framework components.

        Falls back gracefully: if no allocation or profile is active, broker
        values and safe defaults are used.  The system never blocks on missing
        configuration.
        """
        broker_state = await self._account_repo.get_current()
        risk_profile = await self._profile_repo.get_active()
        allocation = await self._allocation_repo.get_active()
        portfolio = await self._portfolio_repo.get_active()

        broker_capital = broker_state.account_capital
        broker_margin = broker_state.available_margin

        if allocation is not None:
            configured_capital = allocation.allocated_capital
            configured_margin = allocation.allocated_margin
            mode = allocation.capital_source_mode
        else:
            configured_capital = _ZERO
            configured_margin = None
            mode = CapitalSourceMode.HYBRID

        effective_capital, effective_margin = self._resolve_capital(
            mode=mode,
            broker_capital=broker_capital,
            broker_margin=broker_margin,
            configured_capital=configured_capital,
            configured_margin=configured_margin,
        )

        if risk_profile is not None:
            effective_daily = effective_capital * (risk_profile.daily_loss_pct / Decimal(100))
            effective_weekly = effective_capital * (risk_profile.weekly_loss_pct / Decimal(100))
            effective_drawdown = effective_capital * (risk_profile.drawdown_pct / Decimal(100))
            effective_risk_per_trade = effective_capital * (risk_profile.risk_per_trade_pct / Decimal(100))
            effective_max_open = risk_profile.max_open_positions
        else:
            # No active profile — use conservative safe defaults
            effective_daily = effective_capital * Decimal("0.02")
            effective_weekly = effective_capital * Decimal("0.05")
            effective_drawdown = effective_capital * Decimal("0.10")
            effective_risk_per_trade = effective_capital * Decimal("0.01")
            effective_max_open = 5

        return EffectiveAccountState(
            capital_source_mode=mode,
            broker_capital=broker_capital,
            broker_margin=broker_margin,
            configured_capital=configured_capital,
            configured_margin=configured_margin,
            effective_capital=effective_capital,
            effective_margin=effective_margin,
            effective_daily_loss_limit=effective_daily,
            effective_weekly_loss_limit=effective_weekly,
            effective_drawdown_limit=effective_drawdown,
            effective_risk_per_trade=effective_risk_per_trade,
            effective_max_open_positions=effective_max_open,
            risk_profile_id=risk_profile.profile_id if risk_profile else None,
            allocation_id=allocation.allocation_id if allocation else None,
            portfolio_id=portfolio.portfolio_id if portfolio else None,
            captured_at=broker_state.captured_at,
        )

    async def to_account_state(self, eas: EffectiveAccountState) -> AccountState:
        """Return an AccountState with session_capital replaced by effective_capital.

        The Risk Engine (PositionSizer, risk limit checks) consumes an AccountState.
        This adapter bridges the gap without modifying any Risk Engine internals.
        """
        broker_state = await self._account_repo.get_current()
        return dataclasses.replace(
            broker_state,
            session_capital=eas.effective_capital,
            available_margin=eas.effective_margin,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_capital(
        mode: CapitalSourceMode,
        broker_capital: Decimal,
        broker_margin: Decimal,
        configured_capital: Decimal,
        configured_margin: Decimal | None,
    ) -> tuple[Decimal, Decimal]:
        if mode == CapitalSourceMode.ACCOUNT:
            return broker_capital, broker_margin

        if mode == CapitalSourceMode.CONFIGURED:
            margin = configured_margin if configured_margin is not None else broker_margin
            return configured_capital, margin

        # HYBRID (default)
        effective_capital = configured_capital if configured_capital > _ZERO else broker_capital
        return effective_capital, broker_margin
