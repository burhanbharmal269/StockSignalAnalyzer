"""PortfolioState — frozen value object for portfolio-level risk metrics.

Captured once per evaluation via asyncio.gather().  Dict fields are JSON-decoded
from Redis Hash values.  The dataclass is frozen but dicts are not hashable — do
not use PortfolioState as a dict key or event field.

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.domain.exceptions.risk import RiskInvariantError


@dataclass(frozen=True, kw_only=True)
class PortfolioState:
    """Immutable snapshot of the live portfolio at evaluation time.

    Attributes:
        open_positions_count:        Total open positions across all underlyings.
        positions_per_underlying:    {underlying: position_count} mapping.
        capital_per_underlying_pct:  {underlying: pct_of_total_capital} mapping.
        net_delta:                   Portfolio net delta in INR per 1-point underlying move.
        net_vega:                    Portfolio net vega in INR per 1% IV change.
        net_theta_daily:             Portfolio daily theta in INR per calendar day.
        orders_last_minute:          Count of orders placed in the last 60 seconds.
        orders_today:                Count of orders placed since midnight IST for the current day.
        captured_at:                 UTC timestamp when this snapshot was read.
    """

    open_positions_count: int
    positions_per_underlying: dict[str, int]
    capital_per_underlying_pct: dict[str, float]
    net_delta: float
    net_vega: float
    net_theta_daily: float
    orders_last_minute: int
    orders_today: int
    captured_at: datetime

    def __post_init__(self) -> None:
        if self.open_positions_count < 0:
            raise RiskInvariantError(
                f"open_positions_count must be >= 0, got {self.open_positions_count}"
            )
        if self.orders_last_minute < 0:
            raise RiskInvariantError(
                f"orders_last_minute must be >= 0, got {self.orders_last_minute}"
            )
        if self.orders_today < 0:
            raise RiskInvariantError(
                f"orders_today must be >= 0, got {self.orders_today}"
            )
        for underlying, count in self.positions_per_underlying.items():
            if count < 0:
                raise RiskInvariantError(
                    f"positions_per_underlying[{underlying!r}] must be >= 0, got {count}"
                )
        for underlying, pct in self.capital_per_underlying_pct.items():
            if pct < 0.0:
                raise RiskInvariantError(
                    f"capital_per_underlying_pct[{underlying!r}] must be >= 0, got {pct}"
                )
