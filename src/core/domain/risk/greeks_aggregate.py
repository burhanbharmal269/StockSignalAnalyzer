"""GreeksAggregate — frozen domain value object for portfolio-level option Greeks.

Produced by GreeksCalculator.aggregate() from a collection of GreeksSnapshot values.
Represents the net (summed) Greeks across all positions at evaluation time.

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.domain.exceptions.risk import RiskInvariantError


@dataclass(frozen=True, kw_only=True)
class GreeksAggregate:
    """Summed portfolio-level Greeks across all positions.

    All float fields are signed sums:
      - net_delta is positive for a net-long portfolio, negative for net-short.
      - net_theta is negative for a portfolio that is net-long options (daily decay cost).
      - net_vega is positive when the portfolio benefits from rising implied volatility.
      - net_gamma is always positive for a net-long options portfolio.

    Unit dependency: All values are sums of pre-scaled INR-unit inputs.
        Correctness depends on GreeksSnapshot.delta (and gamma/theta/vega) being
        pre-scaled by GreeksComputeService before storage. See GreeksSnapshot for
        the authoritative unit contract.

    Attributes:
        net_delta:        Sum of per-position delta values (INR/point of underlying).
        net_gamma:        Sum of per-position gamma values (INR per 1-point² move).
        net_theta:        Sum of per-position theta values (INR daily time decay).
        net_vega:         Sum of per-position vega values (INR per 1% IV move).
        any_from_fallback: True when at least one snapshot was sourced from the Tier-2
                           fallback cache (risk:greeks:fallback:{position_id}).
        snapshot_count:   Number of GreeksSnapshot objects that were aggregated.
    """

    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    any_from_fallback: bool
    snapshot_count: int

    def __post_init__(self) -> None:
        if self.snapshot_count < 0:
            raise RiskInvariantError(
                f"snapshot_count must be >= 0, got {self.snapshot_count}"
            )
