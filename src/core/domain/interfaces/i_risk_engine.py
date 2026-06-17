"""IRiskEngine — domain port for the risk evaluation service.

The application layer implements this; consumers depend only on the interface.

Reference: docs/17_PORTFOLIO_RISK_ENGINE.md
           docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 6
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.risk.risk_decision import RiskDecision
    from core.domain.risk.risk_request import RiskRequest


class IRiskEngine(ABC):
    """Async pre-trade risk evaluation engine.

    Exactly one evaluation runs at a time (sequential model, Constraint 1 and 2).
    """

    @abstractmethod
    async def evaluate(self, request: RiskRequest) -> RiskDecision:
        """Run all 15 pre-trade checks and return an immutable RiskDecision.

        The returned RiskDecision is always persisted to risk_decisions before
        this coroutine completes (persistence-first invariant, Constraint 4).

        Args:
            request: Fully populated RiskRequest carrying all data needed for
                     the 15 checks without additional I/O inside check logic.

        Returns:
            RiskDecision with approved=True and risk_decision_id set if all checks
            pass and final_lots >= 1; otherwise approved=False with a rejection_code.

        Raises:
            ConcurrentEvaluationError: If called while another evaluation is active
                                       via a direct (non-consumer-group) call path.
        """
