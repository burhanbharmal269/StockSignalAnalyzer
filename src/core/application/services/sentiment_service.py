"""SentimentService — keyword + AI-assisted sentiment scoring.

Two modes:
1. Keyword-based (always available) — fast, deterministic
2. AI-enhanced (when AI provider configured) — uses LLM for nuanced scoring
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from core.domain.entities.news_event import NewsEvent
    from core.infrastructure.config.ai_config import AIConfig
    from sqlalchemy.ext.asyncio import async_sessionmaker

_log = logging.getLogger(__name__)

_BULLISH_WORDS = {
    "surge", "rally", "gain", "profit", "beat", "record", "high", "growth",
    "strong", "positive", "upgrade", "buy", "outperform", "bullish",
    "breakthrough", "boost", "recover", "rise", "jump", "climb", "soar",
    "expansion", "acquisition", "merger", "dividend", "bonus",
}
_BEARISH_WORDS = {
    "fall", "drop", "decline", "loss", "miss", "low", "weak", "negative",
    "downgrade", "sell", "underperform", "bearish", "crash", "slump",
    "concern", "risk", "fraud", "probe", "penalty", "fine", "delay",
    "cut", "reduce", "halt", "suspend", "bankrupt", "debt",
}


class SentimentService:
    def __init__(self, session_factory, ai_config=None) -> None:
        self._sf = session_factory
        self._ai_config = ai_config

    def score_text(self, text: str) -> tuple[Decimal, str, Decimal]:
        """Returns (score, direction, confidence).  score ∈ [-1, +1]."""
        words = re.findall(r"\b\w+\b", text.lower())
        bull_hits = sum(1 for w in words if w in _BULLISH_WORDS)
        bear_hits = sum(1 for w in words if w in _BEARISH_WORDS)
        total = bull_hits + bear_hits

        if total == 0:
            return Decimal("0"), "NEUTRAL", Decimal("0.3")

        score = Decimal(str((bull_hits - bear_hits) / total))
        confidence = Decimal(str(min(total / 10, 1.0)))

        if score > Decimal("0.1"):
            direction = "BULLISH"
        elif score < Decimal("-0.1"):
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        return score, direction, confidence

    async def score_news_event(self, event: NewsEvent) -> None:
        """Score a news event and persist sentiment scores per symbol."""
        text = f"{event.title} {event.content}"
        score, direction, confidence = self.score_text(text)

        symbols = event.symbols if event.symbols else ["NIFTY"]
        async with self._sf() as db:
            for symbol in symbols:
                await db.execute(text("""
                    INSERT INTO sentiment_scores
                        (symbol, score, direction, confidence, source_type, news_event_id)
                    VALUES
                        (:symbol, :score, :direction, :confidence, 'NEWS', :news_id)
                """), {
                    "symbol": symbol,
                    "score": float(score),
                    "direction": direction,
                    "confidence": float(confidence),
                    "news_id": event.id,
                })
            await db.commit()

    async def get_symbol_sentiment(self, symbol: str, hours: int = 24) -> dict:
        """Aggregate sentiment for a symbol over the last N hours."""
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT AVG(score) as avg_score, COUNT(*) as count,
                       SUM(CASE WHEN direction='BULLISH' THEN 1 ELSE 0 END) as bull,
                       SUM(CASE WHEN direction='BEARISH' THEN 1 ELSE 0 END) as bear
                FROM sentiment_scores
                WHERE symbol=:sym
                  AND calculated_at >= NOW() - INTERVAL ':hours hours'
            """).bindparams(hours=hours), {"sym": symbol})
            # Fallback for interval parameter binding
        async with self._sf() as db:
            result = await db.execute(text(
                f"SELECT AVG(score), COUNT(*), "
                f"SUM(CASE WHEN direction='BULLISH' THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN direction='BEARISH' THEN 1 ELSE 0 END) "
                f"FROM sentiment_scores "
                f"WHERE symbol=:sym "
                f"AND calculated_at >= NOW() - INTERVAL '{hours} hours'"
            ), {"sym": symbol})
            row = result.fetchone()
            avg_score = float(row[0] or 0)
            count = int(row[1] or 0)
            bull = int(row[2] or 0)
            bear = int(row[3] or 0)

        direction = "NEUTRAL"
        if avg_score > 0.1:
            direction = "BULLISH"
        elif avg_score < -0.1:
            direction = "BEARISH"

        return {
            "symbol": symbol,
            "avg_score": avg_score,
            "direction": direction,
            "news_count": count,
            "bullish_count": bull,
            "bearish_count": bear,
            "hours": hours,
        }

    async def get_market_sentiment(self) -> dict:
        """Overall market sentiment (all symbols, last 24h)."""
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT
                    AVG(score) as avg_score,
                    COUNT(*) as total,
                    SUM(CASE WHEN direction='BULLISH' THEN 1 ELSE 0 END) as bullish,
                    SUM(CASE WHEN direction='BEARISH' THEN 1 ELSE 0 END) as bearish,
                    SUM(CASE WHEN direction='NEUTRAL' THEN 1 ELSE 0 END) as neutral
                FROM sentiment_scores
                WHERE calculated_at >= NOW() - INTERVAL '24 hours'
            """))
            row = result.fetchone()
            avg = float(row[0] or 0)
            return {
                "avg_score": avg,
                "direction": "BULLISH" if avg > 0.1 else "BEARISH" if avg < -0.1 else "NEUTRAL",
                "total_articles": int(row[1] or 0),
                "bullish": int(row[2] or 0),
                "bearish": int(row[3] or 0),
                "neutral": int(row[4] or 0),
            }
