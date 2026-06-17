"""NeutralSentimentProvider — deterministic fallback for ISentimentProvider.

Always returns score=50 (NEUTRAL), is_fallback=True.
Used during Phases 10-16 (before the AI Layer in Phase 17).

The ConfidenceEngine applies -5 to confidence when is_fallback=True,
signalling that no real sentiment analysis was available.

This provider is NEVER injected into: OMS, RiskEngine, PositionSizer,
KillSwitchService. It is injected only into SentimentScoreComponent.
"""

from __future__ import annotations

from core.domain.interfaces.i_sentiment_provider import ISentimentProvider
from core.domain.value_objects.sentiment_result import SentimentResult

_NEUTRAL_SCORE = 50
_PROVIDER_NAME = "NeutralSentimentProvider"


class NeutralSentimentProvider(ISentimentProvider):
    """Returns fixed neutral sentiment. No I/O, no external calls."""

    @property
    def provider_name(self) -> str:
        return _PROVIDER_NAME

    @property
    def is_fallback(self) -> bool:
        return True

    async def get_sentiment(self, symbol: str) -> SentimentResult:  # noqa: ARG002
        return SentimentResult(
            score=_NEUTRAL_SCORE,
            provider_name=_PROVIDER_NAME,
            is_fallback=True,
        )
