"""SentimentResult — output from ISentimentProvider.

Carries the sentiment score, the provider that produced it, and a flag
indicating whether this is a fallback (NeutralSentimentProvider) result.
The ConfidenceEngine applies a -5 adjustment when is_fallback is True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class SentimentResult:
    """Immutable sentiment assessment from an AI or fallback provider.

    score: 0-100 integer where:
        0-19   = STRONGLY_BEARISH
        20-39  = BEARISH
        40-59  = NEUTRAL
        60-79  = BULLISH
        80-100 = STRONGLY_BULLISH

    is_fallback: True when NeutralSentimentProvider was used.
        The SentimentScoreComponent still contributes 2.5 pts (NEUTRAL).
        The ConfidenceEngine separately applies -5 to confidence.
    """

    score: int                       # 0-100 sentiment strength
    provider_name: str               # e.g. "NeutralSentimentProvider"
    is_fallback: bool                # True = no real AI available
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            msg = f"SentimentResult.score must be 0-100, got {self.score}"
            raise ValueError(msg)
