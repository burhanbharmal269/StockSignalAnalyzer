"""CapitalAllocation entity — the operator-configured capital envelope.

Controls how much capital is reserved for the trading system and which
CapitalSourceMode is used when building EffectiveAccountState.

Mutation history is append-only (allocation_history table).
Only one allocation may be active at a time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.enums.allocation_type import AllocationType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.universe_scope import UniverseScope


@dataclass
class CapitalAllocation:
    """Operator-defined capital envelope.

    allocated_capital: the notional capital budget for position sizing.
    allocated_margin:  the margin budget (used in CONFIGURED mode only).
    capital_source_mode: ACCOUNT | CONFIGURED | HYBRID (default HYBRID).
    """

    allocation_id: uuid.UUID
    name: str
    allocation_type: AllocationType
    universe_scope: UniverseScope
    capital_source_mode: CapitalSourceMode

    # Capital amounts
    allocated_capital: Decimal
    allocated_margin: Decimal | None    # None → fall back to broker margin

    # Optional strategy scoping (used when allocation_type == STRATEGY)
    strategy_type: str | None = field(default=None)

    # State
    is_active: bool = field(default=False)
    description: str = field(default="")

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def activate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.now(UTC)

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.now(UTC)

    def update_capital(
        self,
        allocated_capital: Decimal,
        allocated_margin: Decimal | None = None,
    ) -> None:
        if allocated_capital < Decimal(0):
            msg = f"allocated_capital must be >= 0, got {allocated_capital}"
            raise ValueError(msg)
        self.allocated_capital = allocated_capital
        self.allocated_margin = allocated_margin
        self.updated_at = datetime.now(UTC)

    def update_mode(self, mode: CapitalSourceMode) -> None:
        self.capital_source_mode = mode
        self.updated_at = datetime.now(UTC)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        name: str,
        allocation_type: AllocationType,
        universe_scope: UniverseScope,
        allocated_capital: Decimal,
        *,
        capital_source_mode: CapitalSourceMode = CapitalSourceMode.HYBRID,
        allocated_margin: Decimal | None = None,
        strategy_type: str | None = None,
        description: str = "",
    ) -> CapitalAllocation:
        if allocated_capital < Decimal(0):
            msg = f"allocated_capital must be >= 0, got {allocated_capital}"
            raise ValueError(msg)
        return cls(
            allocation_id=uuid.uuid4(),
            name=name,
            allocation_type=allocation_type,
            universe_scope=universe_scope,
            capital_source_mode=capital_source_mode,
            allocated_capital=allocated_capital,
            allocated_margin=allocated_margin,
            strategy_type=strategy_type,
            description=description,
        )
