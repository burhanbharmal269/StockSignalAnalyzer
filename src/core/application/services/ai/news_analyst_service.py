"""NewsAnalystService — AI-enhanced news analysis.

Keyword scoring is always available (fast, free).
When AI is enabled, upgrades sentiment with LLM-based classification
and extracts market impact assessment.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.entities.news_event import NewsEvent
    from core.infrastructure.ai.ai_client import AIClient

_log = logging.getLogger(__name__)

_SYSTEM = """You are a senior Indian equity market analyst.
Analyze the news headline and summary below.
Respond with EXACTLY this JSON (no extra text):
{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "score": <float -1.0 to 1.0>,
  "impact": "HIGH" | "MEDIUM" | "LOW",
  "affected_sectors": ["sector1", ...],
  "key_points": ["point1", "point2"],
  "confidence": <float 0.0 to 1.0>
}"""


class NewsAnalystService:
    def __init__(self, ai_client: AIClient) -> None:
        self._ai = ai_client

    async def analyze(self, event: NewsEvent) -> dict:
        """Return AI analysis dict. Falls back to empty dict if AI unavailable."""
        user_prompt = f"Headline: {event.title}\n\nSummary: {event.content[:500]}"

        raw = await self._ai.complete(_SYSTEM, user_prompt)
        if not raw:
            return {}

        try:
            import json
            # Strip markdown fences if present
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except Exception as exc:
            _log.debug("news_analyst.parse_error err=%s raw=%s", exc, raw[:100])
            return {}

    async def analyze_batch(self, events: list[NewsEvent]) -> list[dict]:
        results = []
        for event in events:
            try:
                result = await self.analyze(event)
                results.append({"event_id": event.id, "analysis": result})
            except Exception as exc:
                _log.debug("news_analyst.batch_error id=%s err=%s", event.id, exc)
                results.append({"event_id": event.id, "analysis": {}})
        return results
