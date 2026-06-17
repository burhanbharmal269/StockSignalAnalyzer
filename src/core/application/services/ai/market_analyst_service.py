"""MarketAnalystService — AI-generated market regime analysis and daily insights.

Consumes pre-computed market intelligence (breadth, sentiment, option chain)
and generates human-readable narrative insights. Never accesses raw prices directly.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from core.application.services.market_breadth_service import MarketBreadthService
    from core.application.services.option_chain_service import OptionChainService
    from core.application.services.sentiment_service import SentimentService
    from core.infrastructure.ai.ai_client import AIClient

_log = logging.getLogger(__name__)

_SYSTEM = """You are a senior NSE/BSE equity and derivatives market analyst.
You receive aggregated market intelligence (NOT individual prices) and produce
a concise market briefing. Be specific, actionable, and data-driven.
Respond in this exact JSON format:
{
  "regime": "BULLISH" | "BEARISH" | "NEUTRAL" | "VOLATILE",
  "regime_confidence": <float 0-1>,
  "summary": "<2-3 sentence market overview>",
  "key_themes": ["theme1", "theme2", "theme3"],
  "sector_outlook": {"sector": "bullish/bearish/neutral", ...},
  "risks": ["risk1", "risk2"],
  "opportunities": ["opp1", "opp2"],
  "recommendation": "<1 sentence actionable advice>"
}"""


class MarketAnalystService:
    def __init__(
        self,
        ai_client: AIClient,
        breadth_service: MarketBreadthService,
        sentiment_service: SentimentService,
        option_chain_service: OptionChainService,
        session_factory,
    ) -> None:
        self._ai = ai_client
        self._breadth = breadth_service
        self._sentiment = sentiment_service
        self._option_chain = option_chain_service
        self._sf = session_factory

    async def generate_daily_insight(self) -> dict:
        """Compile market intelligence and generate AI insight. Persist to DB."""
        context = await self._build_context()
        insight = await self._call_ai(context)
        insight["context"] = context
        insight["generated_at"] = datetime.now(UTC).isoformat()
        await self._persist(insight)
        return insight

    async def get_latest(self) -> dict | None:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT content, generated_at, model_used
                FROM ai_insights
                WHERE insight_type = 'MARKET_DAILY'
                ORDER BY generated_at DESC
                LIMIT 1
            """))
            row = result.mappings().fetchone()
            if not row:
                return None
            return {
                "content": row["content"],
                "generated_at": row["generated_at"],
                "model": row["model_used"],
            }

    async def get_history(self, limit: int = 7) -> list[dict]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT content, generated_at FROM ai_insights
                WHERE insight_type = 'MARKET_DAILY'
                ORDER BY generated_at DESC LIMIT :lim
            """), {"lim": limit})
            return [dict(r) for r in result.mappings().fetchall()]

    async def _build_context(self) -> dict:
        context: dict = {}

        try:
            breadth = await self._breadth.get_latest()
            if breadth:
                context["breadth"] = {
                    "advances": breadth.get("advances"),
                    "declines": breadth.get("declines"),
                    "ad_ratio": breadth.get("advance_decline_ratio"),
                    "breadth_score": breadth.get("breadth_score"),
                    "above_200dma_pct": breadth.get("above_200dma_pct"),
                    "new_highs_52w": breadth.get("new_highs_52w"),
                    "new_lows_52w": breadth.get("new_lows_52w"),
                }
        except Exception as exc:
            _log.debug("market_analyst.breadth_error err=%s", exc)

        try:
            mkt_sent = await self._sentiment.get_market_sentiment()
            context["sentiment"] = mkt_sent
        except Exception as exc:
            _log.debug("market_analyst.sentiment_error err=%s", exc)

        try:
            nifty_oc = await self._option_chain.get_latest("NIFTY")
            if nifty_oc:
                context["nifty_options"] = nifty_oc
        except Exception as exc:
            _log.debug("market_analyst.oc_error err=%s", exc)

        return context

    async def _call_ai(self, context: dict) -> dict:
        user_prompt = f"Market Intelligence Data:\n{json.dumps(context, default=str, indent=2)}"
        raw = await self._ai.complete(_SYSTEM, user_prompt)

        if not raw:
            return self._fallback_insight(context)

        try:
            text_clean = raw.strip()
            if text_clean.startswith("```"):
                text_clean = text_clean.split("```")[1]
                if text_clean.startswith("json"):
                    text_clean = text_clean[4:]
            return json.loads(text_clean.strip())
        except Exception as exc:
            _log.debug("market_analyst.parse_error err=%s", exc)
            return self._fallback_insight(context)

    def _fallback_insight(self, context: dict) -> dict:
        """Rule-based fallback when AI is unavailable."""
        breadth = context.get("breadth", {})
        sentiment = context.get("sentiment", {})

        ad_ratio = float(breadth.get("ad_ratio", 1.0) or 1.0)
        sent_score = float(sentiment.get("avg_score", 0.0) or 0.0)
        above_200 = float(breadth.get("above_200dma_pct", 50.0) or 50.0)

        if ad_ratio > 1.5 and sent_score > 0.1 and above_200 > 60:
            regime = "BULLISH"
        elif ad_ratio < 0.7 and sent_score < -0.1 and above_200 < 40:
            regime = "BEARISH"
        elif above_200 < 30:
            regime = "VOLATILE"
        else:
            regime = "NEUTRAL"

        return {
            "regime": regime,
            "regime_confidence": 0.5,
            "summary": f"Market breadth A/D ratio {ad_ratio:.2f}. {above_200:.0f}% stocks above 200DMA.",
            "key_themes": ["breadth-driven analysis", "no AI available"],
            "sector_outlook": {},
            "risks": [],
            "opportunities": [],
            "recommendation": "Monitor A/D ratio and breadth for direction.",
        }

    async def _persist(self, insight: dict) -> None:
        async with self._sf() as db:
            try:
                await db.execute(text("""
                    INSERT INTO ai_insights
                        (insight_type, symbol, content, model_used, token_count)
                    VALUES
                        ('MARKET_DAILY', 'MARKET', :content::jsonb, :model, 0)
                """), {
                    "content": json.dumps(insight, default=str),
                    "model": self._ai._config.ai_model if self._ai._config.is_enabled else "rule_based",
                })
                await db.commit()
            except Exception as exc:
                _log.debug("market_analyst.persist_error err=%s", exc)
