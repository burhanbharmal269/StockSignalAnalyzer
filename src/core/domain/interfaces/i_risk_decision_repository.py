"""IRiskDecisionRepository — domain port for risk_decisions persistence.

risk_decisions is append-only.  Implementations must NEVER provide update()
or delete() methods.  The application DB user must not have UPDATE or DELETE
permissions on this table (enforced in migration 004_phase13).

Reference: docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 1.2
           docs/17_PORTFOLIO_RISK_ENGINE.md §risk_decisions schema
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.risk.risk_decision import RiskDecision


class IRiskDecisionRepository(ABC):
    """Append-only repository for the risk_decisions TimescaleDB hypertable.

    The caller wraps insert() with asyncio.wait_for(timeout=...) to enforce the
    100ms persistence-first deadline (Constraint 4 / H-7 resolution).
    """

    @abstractmethod
    async def insert(self, decision: RiskDecision, timeout_seconds: float) -> int:
        """Persist a RiskDecision and return its assigned primary key.

        Args:
            decision:        The completed RiskDecision to persist.
            timeout_seconds: Maximum seconds before raising asyncio.TimeoutError.

        Returns:
            The auto-assigned BIGSERIAL primary key (risk_decision_id >= 1).

        Raises:
            RiskDecisionPersistenceError: On OperationalError or IntegrityError.
            asyncio.TimeoutError:         If the INSERT exceeds timeout_seconds.
        """
