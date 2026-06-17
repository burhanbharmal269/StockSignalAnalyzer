"""InstrumentData — raw market data input to the Universe Selection Engine.

This is the caller-prepared structure passed to UniverseFilterService.select().
The USE does not perform any I/O; all market data is injected by the caller.

All fields that may be unavailable from Phase 16+ data sources are typed as
`float | None`. Filters skip or exclude gracefully when data is None.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class InstrumentData:
    """Market data snapshot for a single NSE FnO instrument.

    Attributes:
        instrument_token:       Unique numeric token (Kite API).
        underlying:             Underlying symbol (e.g. "NIFTY", "RELIANCE").
        instrument_class:       "OPTION" | "FUTURE".
        expiry_date:            Expiry date of this contract.
        sector:                 NSE sector name (for diversification filter).
        spot_price:             Current underlying spot price.
        is_banned:              True if instrument is on SEBI F&O ban list.
        dte:                    Calendar days to expiry from today.
        avg_traded_value_5d:    5-day rolling average traded value (INR crore).
        active_strikes_count:   Strikes with non-zero OI within 10% of spot.
        today_volume:           Intraday volume so far (units: lots).
        avg_volume_20d:         20-day rolling average volume (lots). 0 = no history.
        atm_oi:                 Near-ATM open interest (lots, within atm_oi_band_pct).
        bid:                    Best bid for ATM strike (INR).
        ask:                    Best ask for ATM strike (INR). 0 = no live quote.
        iv_pct:                 Implied volatility % (annualised). None = unavailable.
        iv_rank:                IV rank (0–100). None = unavailable.
        atr_14_pct:             ATR-14 as % of spot. None = unavailable.
    """

    instrument_token: int
    underlying: str
    instrument_class: str
    expiry_date: date
    sector: str
    spot_price: float
    is_banned: bool
    dte: int
    avg_traded_value_5d: float
    active_strikes_count: int
    today_volume: float
    avg_volume_20d: float
    atm_oi: float
    bid: float
    ask: float
    iv_pct: float | None
    iv_rank: float | None
    atr_14_pct: float | None

    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2.0 if (self.bid + self.ask) > 0 else 0.0

    @property
    def spread_pct(self) -> float | None:
        """Bid-ask spread as % of mid. None if no live quote."""
        mid = self.mid_price
        if mid <= 0:
            return None
        return (self.ask - self.bid) / mid * 100.0

    @property
    def volume_ratio(self) -> float:
        """Today's volume relative to 20-day average. 0 if no history."""
        if self.avg_volume_20d <= 0:
            return 0.0
        return self.today_volume / self.avg_volume_20d
