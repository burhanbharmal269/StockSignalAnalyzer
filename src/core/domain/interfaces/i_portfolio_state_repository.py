"""IPortfolioStateRepository — domain port for reading portfolio state from Redis.

Two separate keys with different fail-safe semantics:
  risk:portfolio_state    (Hash, TTL 60s)  → FAIL_CLOSED
  risk:graduated_response (Hash, no TTL)   → FAIL_CLOSED (treat as multiplier=0.0)

Reference: docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 1.2
           docs/PHASE_13_REMEDIATION_PLAN.md Section 1 (C-2 table) and Section 4
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.risk.graduated_response_state import GraduatedResponseState
    from core.domain.risk.portfolio_state import PortfolioState


class IPortfolioStateRepository(ABC):
    """Access to portfolio metrics and graduated-response tier from Redis."""

    @abstractmethod
    async def get_current(self) -> PortfolioState:
        """Read and deserialise the current PortfolioState from risk:portfolio_state.

        Returns:
            A frozen PortfolioState snapshot.

        Raises:
            DataSourceUnavailableError: On ConnectionError, missing key, or parse failure.
                                        source='portfolio_state'
        """

    @abstractmethod
    async def get_graduated_response(self) -> GraduatedResponseState:
        """Read and deserialise the current GraduatedResponseState from risk:graduated_response.

        Returns:
            A frozen GraduatedResponseState.

        Raises:
            DataSourceUnavailableError: On ConnectionError, missing key, or parse failure.
                                        source='graduated_response_state'
        """

    @abstractmethod
    async def set_graduated_response(self, state: GraduatedResponseState) -> None:
        """Persist a new GraduatedResponseState to risk:graduated_response (no TTL).

        Called by PortfolioMonitorService when a drawdown or loss threshold
        causes a tier transition.

        Raises:
            DataSourceUnavailableError: On ConnectionError or write failure.
                                        source='graduated_response_state'
        """
