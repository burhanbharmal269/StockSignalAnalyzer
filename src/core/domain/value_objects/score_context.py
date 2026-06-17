"""ScoreContext — all inputs required by the scoring components.

Bundles FeatureSnapshot (candle-derived indicators) with market-context
data that arrives from different sources and on different cadences.
Created by the Phase 14 Signal Engine and passed to every IScoreComponent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.domain.enums.instrument_class import InstrumentClass
from core.domain.enums.market_regime import MarketRegime

if TYPE_CHECKING:
    from core.domain.value_objects.feature_snapshot import FeatureSnapshot
    from core.domain.value_objects.option_chain_snapshot import OptionChainSnapshot
    from core.domain.value_objects.sentiment_result import SentimentResult


@dataclass(frozen=True)
class ScoreContext:
    """All data a scoring component may need to evaluate a signal.

    Fields are Optional where data may be unavailable; components declare
    is_available=False in their output when their required fields are None.
    """

    instrument_token: int
    timeframe: str
    regime: MarketRegime
    features: FeatureSnapshot       # candle-derived: ADX, EMA, ATR, VIX, VWAP …

    # OI market data (from NSE FO feed, 3-5 min delay expected)
    oi_change_pct: float | None = None      # (current_OI - prev_OI) / prev_OI × 100
    price_change_pct: float | None = None   # (close - prev_close) / prev_close × 100
    fii_net_contracts: int | None = None    # FII net futures position (EOD, prior day)
    max_pain_price: float | None = None     # Theoretical max pain for nearest expiry
    dte: int | None = None                  # Days to expiry for nearest contract

    # Volume and order-flow data
    volume_ratio: float | None = None       # current_bar_volume / 20-bar average
    obv_trend: str | None = None            # "UP" | "DOWN" | "FLAT"
    cumulative_delta: float | None = None   # buy_volume - sell_volume (30 min)
    vpoc_distance_pct: float | None = None  # % distance from VPOC (session)

    # VWAP data
    vwap_deviation_sigma: float | None = None  # (price - VWAP) / VWAP_std_dev
    vwap_touch_count: int = 0               # Times price has tested VWAP today

    # Instrument classification — required by Confidence Engine for win-rate lookup
    instrument_class: InstrumentClass | None = None

    # Intraday RSI (computed by feature pipeline, separate from regime features)
    rsi_14: float | None = None

    # Option chain (refreshed every ~60 s)
    option_chain: OptionChainSnapshot | None = None

    # Sentiment (AI or fallback, asynchronous)
    sentiment_result: SentimentResult | None = None

    evaluation_timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
