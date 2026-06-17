"""ICorrelationRepository — domain port for reading the correlation matrix from Redis.

CONSERVATIVE_DEFAULT policy (C-2 resolution): on a cache miss or connection error
return an empty dict.  The caller applies ρ=1.0 for any unknown pair (most
conservative assumption — maximum effective concentration).

Reference: docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 1.2
           docs/PHASE_13_REMEDIATION_PLAN.md Section 1 (C-2 table)
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ICorrelationRepository(ABC):
    """Read-only access to the risk:correlation_matrix Redis key (JSON String, TTL 24h).

    Written by CorrelationService (Phase 16); read by RiskEngineService in Phase 13.
    """

    @abstractmethod
    async def get_matrix(self) -> dict[str, dict[str, float]]:
        """Return the current inter-underlying correlation matrix.

        Returns:
            Nested dict: {underlying_a: {underlying_b: correlation_coefficient}}.
            Returns an empty dict on cache miss or Redis unavailability.
            Callers must treat missing pairs as ρ=1.0 (CONSERVATIVE_DEFAULT).
        """
