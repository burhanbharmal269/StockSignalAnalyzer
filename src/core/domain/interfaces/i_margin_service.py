"""IMarginService — domain port for broker margin queries.

FAIL_CLOSED policy (C-2 resolution / A-10): the broker margin API call is on the
critical evaluation path.  Implementations must apply a 150ms timeout internally
to protect the 200ms P99 evaluation SLO (Decision A-10).

On timeout or broker error raise MarginDataUnavailableError so the caller can
apply FAIL_CLOSED and return RiskDecision(MARGIN_DATA_UNAVAILABLE).

Reference: docs/PHASE_13_FINAL_READINESS_REVIEW.md Special Review 2 (broker outage)
           docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 1.2
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal


class IMarginService(ABC):
    """Async broker margin query port.

    Current implementation: KiteMarginService (wraps Kite Connect span margin API).
    Future: pluggable per IBroker abstraction.
    """

    @abstractmethod
    async def get_required_margin(
        self,
        instrument_token: int,
        lots: int,
        timeout_seconds: float,
    ) -> Decimal:
        """Query the broker for the margin required to open a position.

        Args:
            instrument_token: Broker instrument token.
            lots:             Number of lots in the proposed trade.
            timeout_seconds:  Maximum seconds to wait for the broker API.
                              Implementations should enforce this internally
                              in addition to any outer asyncio.wait_for wrapper.

        Returns:
            Required margin in INR as a Decimal.

        Raises:
            MarginDataUnavailableError: On broker API timeout, HTTP error, or
                                        any failure that prevents returning a
                                        reliable margin figure.
                                        source='margin_api'
        """
