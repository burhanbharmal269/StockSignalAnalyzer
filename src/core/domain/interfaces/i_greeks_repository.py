"""IGreeksRepository — domain port for the two-tier Greeks cache.

Tier 1:  risk:greeks:{position_id}          TTL 60s   (primary)
Tier 2:  risk:greeks:fallback:{position_id} TTL 300s  (fallback)

Both tiers are written atomically in a single pipeline.  A Tier 1 write without
a corresponding Tier 2 write is a contract violation (Constraint 11).

Read priority: Tier 1 (age check) → Tier 2 → None (FAIL_CLOSED / grace period).

Reference: docs/PHASE_13_FINAL_READINESS_REVIEW.md H-4 resolution
           docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 1.2
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.risk.greeks_snapshot import GreeksSnapshot


class IGreeksRepository(ABC):
    """Read/write access to the two-tier Greeks cache in Redis."""

    @abstractmethod
    async def get_portfolio_greeks(
        self,
        position_ids: list[str],
        max_age_seconds: int,
        new_position_grace_seconds: int,
    ) -> dict[str, GreeksSnapshot | None]:
        """Fetch Greeks for a list of positions using the two-tier fallback strategy.

        For each position_id:
          1. Try risk:greeks:{id} (Tier 1).  Use if age <= max_age_seconds.
          2. Try risk:greeks:fallback:{id} (Tier 2).  Use with from_fallback=True.
          3. Both miss → return None for this id (caller applies FAIL_CLOSED).

        The new_position_grace_seconds parameter is exposed so the caller can
        determine whether a None result should be FAIL_CLOSED or skipped
        (grace period applies when the position is < grace_seconds old).

        Args:
            position_ids:              List of position IDs to look up.
            max_age_seconds:           Reject Tier 1 entries older than this.
            new_position_grace_seconds: Unused inside this method; documented for
                                        callers that apply the grace-period logic.

        Returns:
            Dict mapping position_id → GreeksSnapshot (or None on full miss).
        """

    @abstractmethod
    async def write_greeks(self, position_id: str, snapshot: GreeksSnapshot) -> None:
        """Write Greeks to both cache tiers atomically (single Redis pipeline).

        Tier 1: risk:greeks:{position_id}          with TTL = config.greeks.max_age_seconds
        Tier 2: risk:greeks:fallback:{position_id} with TTL = config.greeks.fallback_ttl_seconds

        Args:
            position_id: Position identifier.
            snapshot:    Computed GreeksSnapshot (from_fallback must be False on write).

        Raises:
            DataSourceUnavailableError: On Redis ConnectionError.
                                        source='greeks_cache'
        """
