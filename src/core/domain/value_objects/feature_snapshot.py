"""FeatureSnapshot — immutable bag of pre-computed indicator values.

All fields are Optional so the domain can handle partial data gracefully.
Callers (Feature Engineering pipeline) push a fully-populated snapshot;
the regime engine evaluates only the fields that are present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.mtf_snapshot import MtfSnapshot


@dataclass(frozen=True)
class FeatureSnapshot:
    """All indicator inputs required by the Market Regime Engine.

    Fields are None when the upstream pipeline could not compute a value
    (e.g., insufficient history, missing market data).
    """

    instrument_token: int
    timeframe: str

    # ADX / DI+ / DI-
    adx: float | None = None
    di_plus: float | None = None
    di_minus: float | None = None

    # EMAs
    ema_20: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None

    # Price
    close_price: float | None = None

    # Supertrend
    supertrend_direction: int | None = None  # +1 = bullish, -1 = bearish

    # Momentum confirmation
    adx_rising: bool | None = None           # True when ADX is increasing (trend accelerating)
    macd_hist_expanding: bool | None = None  # True when MACD histogram magnitude is growing

    # Volatility
    atr: float | None = None
    atr_ratio: float | None = None          # current ATR / SMA-20 of ATR
    bb_width_percentile: float | None = None

    # Options market data
    india_vix: float | None = None
    iv_percentile: float | None = None
    pcr: float | None = None                 # Put-Call Ratio

    # Breadth
    advance_decline_ratio: float | None = None
    fii_net_buying_days: int | None = None   # consecutive +/- days; sign = direction
    nifty_above_200dma_pct: float | None = None  # % of Nifty 50 stocks above 200 DMA

    # VWAP
    vwap: float | None = None

    # Historical vs Implied Volatility
    hv_iv_ratio: float | None = None

    # Phase 14 — 5-minute MTF snapshot for TrendComponent overlay.
    # None when 5m candle data is unavailable or insufficient (< 55 bars).
    # TrendComponent reads this to apply the ±4 pt alignment bonus/penalty.
    mtf_5m: MtfSnapshot | None = None

    snapshot_time: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
