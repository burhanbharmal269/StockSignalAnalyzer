"""Portfolio entity — named container that groups positions and orders.

Each live trading session is associated with exactly one active Portfolio.
Paper portfolios route to PaperBrokerAdapter; live portfolios route to
the configured live broker.

Only one portfolio of each PortfolioType may be active at a time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.domain.enums.portfolio_type import PortfolioType


@dataclass
class Portfolio:
    """Named grouping for positions and orders."""

    portfolio_id: uuid.UUID
    name: str
    portfolio_type: PortfolioType

    # Links to capital framework
    risk_profile_id: uuid.UUID | None = field(default=None)
    allocation_id: uuid.UUID | None = field(default=None)

    # Optional owner (future multi-user)
    owner_user_id: int | None = field(default=None)

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

    def assign_risk_profile(self, risk_profile_id: uuid.UUID) -> None:
        self.risk_profile_id = risk_profile_id
        self.updated_at = datetime.now(UTC)

    def assign_allocation(self, allocation_id: uuid.UUID) -> None:
        self.allocation_id = allocation_id
        self.updated_at = datetime.now(UTC)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        name: str,
        portfolio_type: PortfolioType,
        *,
        risk_profile_id: uuid.UUID | None = None,
        allocation_id: uuid.UUID | None = None,
        owner_user_id: int | None = None,
        description: str = "",
    ) -> Portfolio:
        return cls(
            portfolio_id=uuid.uuid4(),
            name=name,
            portfolio_type=portfolio_type,
            risk_profile_id=risk_profile_id,
            allocation_id=allocation_id,
            owner_user_id=owner_user_id,
            description=description,
        )
