"""IAccountStateRepository — domain port for reading risk:account_state from Redis.

FAIL_CLOSED policy (C-2 resolution): if the Redis read fails for any reason,
implementations must raise DataSourceUnavailableError.  The caller returns
RiskDecision(rejection_code=DATA_SOURCE_UNAVAILABLE) without proceeding to checks.

Reference: docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 1.2
           docs/PHASE_13_REMEDIATION_PLAN.md Section 1 (C-2 table)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.risk.account_state import AccountState


class IAccountStateRepository(ABC):
    """Read-only access to the risk:account_state Redis Hash (TTL 30s).

    Written by the AccountStatePoller (Phase 16); read by RiskEngineService
    and PortfolioMonitor in Phase 13.
    """

    @abstractmethod
    async def get_current(self) -> AccountState:
        """Read and deserialise the current AccountState from Redis.

        Returns:
            A frozen AccountState snapshot.

        Raises:
            DataSourceUnavailableError: On Redis ConnectionError, missing key,
                                        or any parse failure.
                                        source='account_state'
        """
