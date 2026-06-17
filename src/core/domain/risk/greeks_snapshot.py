"""GreeksSnapshot — frozen value object for a single position's option Greeks.

Read from the two-tier Greeks cache:
  Tier 1: risk:greeks:{position_id} (TTL 60s)
  Tier 2: risk:greeks:fallback:{position_id} (TTL 300s)
The from_fallback flag signals to callers that Tier 2 was used and a WARNING should be emitted.

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.domain.exceptions.risk import RiskInvariantError


@dataclass(frozen=True, kw_only=True)
class GreeksSnapshot:
    """Greeks for a single position, frozen at cache-read time.

    Unit contract (enforced by GreeksComputeService, Phase D):
        All numeric fields are pre-scaled to INR-unit values before being stored.
        This class sums them as-is — no unit conversion is performed here.
        The phase that writes this snapshot is responsible for applying the scaling:
            value = raw_bs_value × lot_size × lots

    Attributes:
        position_id:   Broker or internal position identifier (non-empty string).
        delta:         Position delta contribution in INR per 1-point underlying move.
                       Computed as: raw_bs_delta × lot_size × lots.
                       Example: NIFTY ATM call (raw delta=0.5, lot_size=50, 1 lot) → 25.0.
                       NOT the raw Black-Scholes delta (0–1 range).
        gamma:         Position gamma contribution (INR per 1-point² move in underlying).
                       Computed as: raw_gamma × lot_size × lots.
        theta:         Position daily time decay in INR (negative for long options).
                       Computed as: raw_theta × lot_size × lots.
        vega:          Position sensitivity to 1% IV change in INR.
                       Computed as: raw_vega × lot_size × lots.
        computed_at:   UTC timestamp when the Greeks were computed by the poller.
        from_fallback: True when Tier 2 (risk:greeks:fallback:{id}) was used.
    """

    position_id: str
    delta: float
    gamma: float
    theta: float
    vega: float
    computed_at: datetime
    from_fallback: bool

    def __post_init__(self) -> None:
        if not self.position_id:
            raise RiskInvariantError("position_id must be a non-empty string")
