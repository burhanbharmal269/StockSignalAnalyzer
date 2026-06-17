"""Sentiment Analysis Component — Component 6 (base weight: 5).

The ONLY component that uses an AI provider. In Phase 10, NeutralSentimentProvider
is always used, which returns score=50 (NEUTRAL) and is_fallback=True.

Scoring:
  STRONGLY_BULLISH (≥80): long=5, short=0
  BULLISH (60-79):        long=4, short=1
  NEUTRAL (40-59):        long=2.5, short=2.5
  BEARISH (20-39):        long=1, short=4
  STRONGLY_BEARISH (<20): long=0, short=5

If sentiment_result is None or age > 60 minutes: treat as NEUTRAL (2.5/2.5).
The ConfidenceEngine (Phase 12) separately applies -5 when is_fallback=True.

Source: docs/21_SIGNAL_ENGINE.md Component 6
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.domain.interfaces.i_score_component import IScoreComponent
from core.domain.value_objects.component_output import ComponentOutput

if TYPE_CHECKING:
    from core.domain.value_objects.score_context import ScoreContext
    from core.infrastructure.config.strategy_config import StrategyConfig

_NAME = "SENTIMENT"
_MAX_WEIGHT = 5


class SentimentComponent(IScoreComponent):
    """Sentiment score mapper. Pure, stateless."""

    def __init__(self, config: StrategyConfig) -> None:
        self._cfg = config.sentiment

    @property
    def component_name(self) -> str:
        return _NAME

    @property
    def max_weight(self) -> int:
        return _MAX_WEIGHT

    def evaluate(self, context: ScoreContext) -> ComponentOutput:
        cfg = self._cfg
        sr = context.sentiment_result

        # Treat missing or stale sentiment as NEUTRAL
        if sr is None or _is_stale(sr, cfg.max_age_minutes):
            long_score = cfg.neutral_long_score
            short_score = cfg.neutral_short_score
            bucket = "NEUTRAL"
            provider = "NONE"
            is_fallback = True
        else:
            long_score, short_score = self._map_score(sr.score, cfg)
            bucket = _bucket_name(sr.score, cfg)
            provider = sr.provider_name
            is_fallback = sr.is_fallback

        direction, conviction = _direction_and_conviction(long_score, short_score, _MAX_WEIGHT)

        key_finding = (
            f"Sentiment: {bucket} via {provider}. "
            f"{'[FALLBACK — confidence -5]' if is_fallback else '[real AI]'}"
        )

        return ComponentOutput(
            component_name=_NAME,
            max_weight=_MAX_WEIGHT,
            long_score=long_score,
            short_score=short_score,
            direction=direction,
            conviction=conviction,
            is_available=True,
            data_freshness_seconds=0,
            key_finding=key_finding,
            metadata={
                "raw_score": sr.score if sr is not None else None,
                "bucket": bucket,
                "provider": provider,
                "is_fallback": is_fallback,
            },
        )

    @staticmethod
    def _map_score(raw: int, cfg: object) -> tuple[float, float]:
        """Map 0-100 sentiment score to (long_score, short_score)."""
        if raw >= cfg.strongly_bullish_min:
            return cfg.strongly_bullish_long_score, cfg.strongly_bullish_short_score
        if raw >= cfg.bullish_min:
            return cfg.bullish_long_score, cfg.bullish_short_score
        if raw >= cfg.neutral_min:
            return cfg.neutral_long_score, cfg.neutral_short_score
        if raw >= cfg.bearish_min:
            return cfg.bearish_long_score, cfg.bearish_short_score
        return cfg.strongly_bearish_long_score, cfg.strongly_bearish_short_score


def _is_stale(sr: object, max_age_minutes: int) -> bool:
    age_seconds = (datetime.now(UTC) - sr.generated_at).total_seconds()
    return age_seconds > max_age_minutes * 60


def _bucket_name(raw: int, cfg: object) -> str:
    if raw >= cfg.strongly_bullish_min:
        return "STRONGLY_BULLISH"
    if raw >= cfg.bullish_min:
        return "BULLISH"
    if raw >= cfg.neutral_min:
        return "NEUTRAL"
    if raw >= cfg.bearish_min:
        return "BEARISH"
    return "STRONGLY_BEARISH"


def _direction_and_conviction(
    long_score: float, short_score: float, max_weight: int
) -> tuple[str, float]:
    if long_score > short_score:
        return "LONG", long_score / max_weight
    if short_score > long_score:
        return "SHORT", short_score / max_weight
    return "NEUTRAL", 0.0
