"""ISentimentProvider — contract for news/market sentiment providers.

Implemented by:
  - NeutralSentimentProvider (Phase 10, always available, is_fallback=True)
  - OpenAIProvider / AnthropicProvider / GeminiProvider (Phase 17, AI-powered)

AI providers are FORBIDDEN from being injected into:
  OMS, RiskEngine, PositionSizer, KillSwitchService.

This interface is injected only into SentimentScoreComponent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.sentiment_result import SentimentResult


class ISentimentProvider(ABC):
    """Sentiment signal source — AI-backed or deterministic fallback."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifier stored in SentimentResult.provider_name."""

    @property
    @abstractmethod
    def is_fallback(self) -> bool:
        """True for NeutralSentimentProvider; False for real AI providers."""

    @abstractmethod
    async def get_sentiment(self, symbol: str) -> SentimentResult:
        """Return the current sentiment for the given symbol.

        Never raises — catches provider errors and returns a neutral result
        with is_fallback=True so the scoring pipeline is never blocked.
        """
