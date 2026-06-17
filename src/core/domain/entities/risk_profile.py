"""RiskProfile entity — named set of risk parameters.

Each RiskProfile maps to a RiskProfileType preset or CUSTOM values.
Only one profile may be active at a time (enforced by the service layer).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.enums.risk_profile_type import RiskProfileType
from core.domain.enums.universe_scope import UniverseScope


@dataclass
class RiskProfile:
    """A named bundle of risk parameters applied system-wide.

    All percentage fields are stored as percentages (e.g. 2.0 means 2%).
    """

    profile_id: uuid.UUID
    name: str
    profile_type: RiskProfileType
    universe_scope: UniverseScope

    # Per-trade risk
    risk_per_trade_pct: Decimal        # % of effective_capital risked per trade
    max_open_positions: int

    # Loss limits (% of effective_capital)
    daily_loss_pct: Decimal
    weekly_loss_pct: Decimal
    drawdown_pct: Decimal              # max drawdown from HWM

    # Position sizing
    max_position_size_pct: Decimal     # max single-position % of capital
    min_position_size_lots: int

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

    def update(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            if not hasattr(self, k):
                msg = f"RiskProfile has no field {k!r}"
                raise ValueError(msg)
            setattr(self, k, v)
        self.updated_at = datetime.now(UTC)

    # ------------------------------------------------------------------
    # Preset factories
    # ------------------------------------------------------------------

    @classmethod
    def conservative(cls) -> RiskProfile:
        return cls(
            profile_id=uuid.uuid4(),
            name="Conservative",
            profile_type=RiskProfileType.CONSERVATIVE,
            universe_scope=UniverseScope.ALL_FNO,
            risk_per_trade_pct=Decimal("1.0"),
            max_open_positions=3,
            daily_loss_pct=Decimal("2.0"),
            weekly_loss_pct=Decimal("5.0"),
            drawdown_pct=Decimal("8.0"),
            max_position_size_pct=Decimal("10.0"),
            min_position_size_lots=1,
            description="Conservative: tight limits, small size.",
        )

    @classmethod
    def moderate(cls) -> RiskProfile:
        return cls(
            profile_id=uuid.uuid4(),
            name="Moderate",
            profile_type=RiskProfileType.MODERATE,
            universe_scope=UniverseScope.ALL_FNO,
            risk_per_trade_pct=Decimal("2.0"),
            max_open_positions=5,
            daily_loss_pct=Decimal("3.0"),
            weekly_loss_pct=Decimal("8.0"),
            drawdown_pct=Decimal("12.0"),
            max_position_size_pct=Decimal("20.0"),
            min_position_size_lots=1,
            description="Moderate: balanced defaults (system default).",
        )

    @classmethod
    def aggressive(cls) -> RiskProfile:
        return cls(
            profile_id=uuid.uuid4(),
            name="Aggressive",
            profile_type=RiskProfileType.AGGRESSIVE,
            universe_scope=UniverseScope.ALL_FNO,
            risk_per_trade_pct=Decimal("3.0"),
            max_open_positions=10,
            daily_loss_pct=Decimal("5.0"),
            weekly_loss_pct=Decimal("12.0"),
            drawdown_pct=Decimal("18.0"),
            max_position_size_pct=Decimal("30.0"),
            min_position_size_lots=1,
            description="Aggressive: wider limits, larger size.",
        )

    @classmethod
    def create(
        cls,
        name: str,
        profile_type: RiskProfileType,
        universe_scope: UniverseScope,
        risk_per_trade_pct: Decimal,
        max_open_positions: int,
        daily_loss_pct: Decimal,
        weekly_loss_pct: Decimal,
        drawdown_pct: Decimal,
        max_position_size_pct: Decimal,
        min_position_size_lots: int = 1,
        description: str = "",
    ) -> RiskProfile:
        return cls(
            profile_id=uuid.uuid4(),
            name=name,
            profile_type=profile_type,
            universe_scope=universe_scope,
            risk_per_trade_pct=risk_per_trade_pct,
            max_open_positions=max_open_positions,
            daily_loss_pct=daily_loss_pct,
            weekly_loss_pct=weekly_loss_pct,
            drawdown_pct=drawdown_pct,
            max_position_size_pct=max_position_size_pct,
            min_position_size_lots=min_position_size_lots,
            description=description,
        )
