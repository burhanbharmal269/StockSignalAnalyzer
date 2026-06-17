"""SignalRequest — input bundle to SignalEngineService.process().

One SignalRequest is created per universe candidate per evaluation cycle.
The caller pre-builds ScoreContext and price levels; the Signal Engine
is pure orchestration and does NOT compute prices or fetch market data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.domain.enums.asset_type import AssetType
from core.domain.enums.market_regime import MarketRegime
from core.domain.enums.strategy_type import StrategyType
from core.domain.value_objects.score_context import ScoreContext


@dataclass(frozen=True)
class SignalRequest:
    """All data required for Signal Engine to process one universe candidate.

    Price fields (entry_price, stop_loss_price, target_price) are computed
    by the caller's price-level service and passed in here. The Signal Engine
    does NOT compute entry, stop, or target prices.
    """

    instrument_token: int
    underlying: str
    instrument_class: str          # "OPTION" | "FUTURE"
    expiry_date: date
    strategy_type: StrategyType
    asset_type: AssetType
    regime: MarketRegime
    score_context: ScoreContext    # Pre-built by caller; passed to scoring engine

    # Price levels for Risk Engine — computed by caller before this request
    entry_price: Decimal
    stop_loss_price: Decimal
    target_price: Decimal
    option_premium: Decimal | None # Required for OPTION; None for FUTURE
    lot_size: int
    dte: int
    atr_14: float                  # 14-period ATR for risk sizing

    # Optional Greeks for option risk checks
    option_delta: float | None = None
    option_vega: float | None = None

    correlation_id: str = ""
