"""GreeksCalculator — pure domain service for portfolio-level Greeks aggregation.

Consumes a collection of GreeksSnapshot objects and produces a GreeksAggregate
representing the net (signed sum) Greeks across the full portfolio.

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.domain.risk.greeks_aggregate import GreeksAggregate
from core.domain.risk.greeks_snapshot import GreeksSnapshot


class GreeksCalculator:
    """Stateless portfolio Greeks aggregation service."""

    @staticmethod
    def aggregate(snapshots: Sequence[GreeksSnapshot]) -> GreeksAggregate:
        """Sum per-position Greeks into a portfolio-level GreeksAggregate.

        Precondition: All GreeksSnapshot values must be pre-scaled to INR-unit
        values by GreeksComputeService (Phase D). This method sums as-is without
        unit conversion. See GreeksSnapshot for the authoritative unit contract.

        Args:
            snapshots: Collection of GreeksSnapshot values, one per open position.
                       An empty sequence returns a zero-valued GreeksAggregate.

        Returns:
            GreeksAggregate with signed sums across all snapshots.
            any_from_fallback is True when at least one snapshot was read from
            the Tier-2 fallback cache (risk:greeks:fallback:{position_id}).
        """
        if not snapshots:
            return GreeksAggregate(
                net_delta=0.0,
                net_gamma=0.0,
                net_theta=0.0,
                net_vega=0.0,
                any_from_fallback=False,
                snapshot_count=0,
            )
        return GreeksAggregate(
            net_delta=sum((s.delta for s in snapshots), 0.0),
            net_gamma=sum((s.gamma for s in snapshots), 0.0),
            net_theta=sum((s.theta for s in snapshots), 0.0),
            net_vega=sum((s.vega for s in snapshots), 0.0),
            any_from_fallback=any(s.from_fallback for s in snapshots),
            snapshot_count=len(snapshots),
        )
