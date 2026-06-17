"""DailyUniverseBuilderService — builds a prioritised trading universe before market open.

Inputs:
  - All active F&O symbols + index futures from MarketUniverseService
  - Historical candle data for volume/momentum pre-screening
  - (Optional) news/earnings events when available

Output:
  - DailyTradingUniverse: ranked list of symbols with priority scores
  - Logged as daily_universe.selected for dashboard display

Called once at market-open startup (or via POST /api/v1/universe/build).
The signal scanner always uses the full universe — this service prioritises it
so high-conviction candidates get processed first in each scan cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.market_universe_service import MarketUniverseService
    from core.domain.entities.market_symbol import MarketSymbol

_log = logging.getLogger(__name__)


@dataclass
class DailyCandidate:
    symbol: str
    is_index: bool
    sector: str | None
    priority_score: float          # 0–100 composite
    volume_score: float            # relative volume vs 20-day avg
    momentum_score: float          # price change % last session
    regime_compatible: bool        # passes basic regime pre-filter
    reason: str                    # human-readable why it was selected


@dataclass
class DailyTradingUniverse:
    built_at: datetime
    total_candidates: int
    index_futures: list[DailyCandidate]
    fo_stocks: list[DailyCandidate]
    sector_breakdown: dict[str, int] = field(default_factory=dict)

    @property
    def all_candidates(self) -> list[DailyCandidate]:
        """Index futures first (always evaluated), then stocks by priority score."""
        return self.index_futures + sorted(
            self.fo_stocks, key=lambda c: c.priority_score, reverse=True
        )

    @property
    def top_symbols(self) -> list[str]:
        return [c.symbol for c in self.all_candidates]


class DailyUniverseBuilderService:
    """Builds the daily trading universe with priority ranking.

    Does NOT replace the full-universe scanner — it provides priority ordering
    so the most promising symbols are processed first in each scan cycle.
    """

    def __init__(
        self,
        universe_svc: "MarketUniverseService",
        historical_svc,  # HistoricalDataService — optional; skipped if unavailable
    ) -> None:
        self._universe = universe_svc
        self._history  = historical_svc

    async def build(self) -> DailyTradingUniverse:
        """Build today's ranked trading universe."""
        all_symbols = await self._universe.get_active_symbols(fo_only=True)
        index_futures = [s for s in all_symbols if s.is_index]
        fo_stocks     = [s for s in all_symbols if not s.is_index]

        _log.info(
            "daily_universe.building index_futures=%d fo_stocks=%d total=%d",
            len(index_futures), len(fo_stocks), len(all_symbols),
        )

        # Score each category
        scored_indices = [self._score_symbol(s) for s in index_futures]
        scored_stocks  = await self._score_stocks(fo_stocks)

        # Sector breakdown
        sector_counts: dict[str, int] = {}
        for c in scored_stocks:
            if c.sector:
                sector_counts[c.sector] = sector_counts.get(c.sector, 0) + 1

        universe = DailyTradingUniverse(
            built_at=datetime.now(UTC),
            total_candidates=len(all_symbols),
            index_futures=scored_indices,
            fo_stocks=scored_stocks,
            sector_breakdown=sector_counts,
        )

        top10 = universe.top_symbols[:10]
        _log.info(
            "daily_universe.built total=%d indices=%d stocks=%d "
            "top10=%s sectors=%d",
            universe.total_candidates,
            len(scored_indices),
            len(scored_stocks),
            top10,
            len(sector_counts),
        )
        return universe

    def _score_symbol(self, sym: "MarketSymbol") -> DailyCandidate:
        """Default scoring when no historical data — index futures always high priority."""
        return DailyCandidate(
            symbol=sym.symbol,
            is_index=sym.is_index,
            sector=sym.sector,
            priority_score=90.0 if sym.is_index else 50.0,
            volume_score=1.0,
            momentum_score=0.0,
            regime_compatible=True,
            reason="index_future_always_active" if sym.is_index else "default_fo_stock",
        )

    async def _score_stocks(self, stocks: list["MarketSymbol"]) -> list[DailyCandidate]:
        """Score F&O stocks using recent candle data. Falls back to default on error."""
        candidates: list[DailyCandidate] = []
        for sym in stocks:
            try:
                candidate = await self._score_stock_with_history(sym)
            except Exception as exc:
                _log.debug("daily_universe.score_error symbol=%s: %s", sym.symbol, exc)
                candidate = self._score_symbol(sym)
            candidates.append(candidate)
        return candidates

    async def _score_stock_with_history(self, sym: "MarketSymbol") -> DailyCandidate:
        """Compute priority score from last 20 candles."""
        candles = await self._history.get_latest(sym.symbol, "15m", 25)
        if len(candles) < 10:
            return self._score_symbol(sym)

        closes = [float(c.close) for c in candles]
        vols   = [float(c.volume) for c in candles]

        # Volume ratio: latest vs 20-bar average
        avg_vol   = sum(vols[:-1]) / max(len(vols) - 1, 1)
        vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 1.0

        # Momentum: price change over last 5 bars
        price_change_pct = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0.0

        # Priority: volume spike + momentum + base
        priority = (
            min(vol_ratio * 20, 40)            # volume contribution: 0–40
            + min(abs(price_change_pct) * 5, 40)  # momentum: 0–40
            + 20                                  # base score
        )
        priority = min(priority, 100.0)

        reason_parts = []
        if vol_ratio > 1.5:
            reason_parts.append(f"vol_spike={vol_ratio:.1f}x")
        if abs(price_change_pct) > 1.0:
            reason_parts.append(f"momentum={price_change_pct:+.1f}%")
        reason = ",".join(reason_parts) or "standard_fo"

        return DailyCandidate(
            symbol=sym.symbol,
            is_index=False,
            sector=sym.sector,
            priority_score=priority,
            volume_score=vol_ratio,
            momentum_score=price_change_pct,
            regime_compatible=True,
            reason=reason,
        )
