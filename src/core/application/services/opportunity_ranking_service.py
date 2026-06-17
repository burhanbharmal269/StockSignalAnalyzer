"""OpportunityRankingService — scores and persists scanner results.

Combines technical, volume, sentiment, OI, and regime scores
into a final ranked opportunity list.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.market_scanner_service import MarketScannerService
    from core.application.services.sentiment_service import SentimentService
    from core.infrastructure.database.repositories.opportunity_repository import (
        SqlAlchemyOpportunityRepository,
    )
    from core.domain.entities.market_opportunity import MarketOpportunity

_log = logging.getLogger(__name__)

# Score weights
_W_TECHNICAL = Decimal("0.35")
_W_VOLUME = Decimal("0.20")
_W_SENTIMENT = Decimal("0.15")
_W_OI = Decimal("0.15")
_W_REGIME = Decimal("0.15")


class OpportunityRankingService:
    def __init__(
        self,
        scanner: MarketScannerService,
        sentiment_service: SentimentService,
        repository: SqlAlchemyOpportunityRepository,
    ) -> None:
        self._scanner = scanner
        self._sentiment = sentiment_service
        self._repo = repository

    async def run_full_scan(self, timeframe: str = "15m") -> list[dict]:
        """Run scanner, enrich with sentiment, rank, persist, return top N."""
        raw = await self._scanner.scan_all(timeframe)
        enriched = await self._enrich_with_sentiment(raw)
        ranked = self._rank(enriched)

        # Persist top 50
        for opp in ranked[:50]:
            try:
                await self._repo.save(opp)
            except Exception as exc:
                _log.debug("opportunity.save failed: %s", exc)

        return [self._to_dict(o) for o in ranked[:30]]

    async def get_top(self, limit: int = 20) -> list[dict]:
        return [self._to_dict(o) for o in await self._repo.get_top(limit)]

    async def _enrich_with_sentiment(
        self, opportunities: list[MarketOpportunity]
    ) -> list[MarketOpportunity]:
        for opp in opportunities:
            try:
                sentiment = await self._sentiment.get_symbol_sentiment(opp.symbol, hours=24)
                opp.sentiment_score = Decimal(str(abs(sentiment["avg_score"]) * 100))
            except Exception:
                opp.sentiment_score = Decimal("0")
        return opportunities

    def _rank(self, opportunities: list[MarketOpportunity]) -> list[MarketOpportunity]:
        for opp in opportunities:
            tech = opp.technical_score or Decimal("0")
            vol = opp.volume_score or Decimal("0")
            sent = opp.sentiment_score or Decimal("0")
            oi = opp.oi_score or Decimal("0")
            reg = opp.regime_score or Decimal("0")

            composite = (
                tech * _W_TECHNICAL
                + vol * _W_VOLUME
                + sent * _W_SENTIMENT
                + oi * _W_OI
                + reg * _W_REGIME
            )
            opp.total_score = composite

        return sorted(opportunities, key=lambda o: o.total_score, reverse=True)

    def _to_dict(self, opp: MarketOpportunity) -> dict:
        return {
            "id": opp.id,
            "symbol": opp.symbol,
            "type": opp.opportunity_type,
            "direction": opp.direction,
            "total_score": float(opp.total_score),
            "confidence": float(opp.confidence),
            "technical_score": float(opp.technical_score or 0),
            "volume_score": float(opp.volume_score or 0),
            "sentiment_score": float(opp.sentiment_score or 0),
            "regime": opp.regime,
            "meta": opp.meta,
            "created_at": opp.created_at.isoformat() if opp.created_at else None,
        }
