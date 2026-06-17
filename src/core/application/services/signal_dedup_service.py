"""SignalDedupService — Redis-based signal deduplication.

Prevents signal flooding when repeated identical signal patterns are
generated within the dedup TTL window. A second identical signal is
suppressed only when its adjusted_score delta <= score_delta_threshold.

Reference: docs/21_SIGNAL_ENGINE.md §Signal Deduplication
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from core.infrastructure.config.confidence_config import ConfidenceConfig

_log = logging.getLogger(__name__)


class SignalDedupService:
    """Stateless Redis wrapper for signal deduplication checks."""

    def __init__(self, redis_client: Redis, config: ConfidenceConfig) -> None:
        self._redis = redis_client
        self._cfg = config.dedup

    def _key(self, instrument_token: int, direction: str, score_bucket: str) -> str:
        return f"{self._cfg.key_prefix}:{instrument_token}:{direction}:{score_bucket}"

    async def is_duplicate(
        self,
        instrument_token: int,
        direction: str,
        score_bucket: str,
        adjusted_score: float,
    ) -> bool:
        """Return True if this signal pattern was seen within the TTL window
        and the score delta does not exceed the threshold."""
        key = self._key(instrument_token, direction, score_bucket)
        existing = await self._redis.get(key)
        if existing is None:
            return False
        try:
            prev_score = float(existing)
        except (TypeError, ValueError):
            return False
        delta = abs(adjusted_score - prev_score)
        if delta <= self._cfg.score_delta_threshold:
            _log.debug(
                "dedup hit instrument=%d direction=%s bucket=%s delta=%.2f",
                instrument_token,
                direction,
                score_bucket,
                delta,
            )
            return True
        return False

    async def register(
        self,
        instrument_token: int,
        direction: str,
        score_bucket: str,
        adjusted_score: float,
    ) -> None:
        """Register this signal pattern in Redis with the configured TTL."""
        key = self._key(instrument_token, direction, score_bucket)
        await self._redis.setex(key, self._cfg.ttl_seconds, str(adjusted_score))
        _log.debug(
            "dedup registered instrument=%d direction=%s bucket=%s score=%.2f ttl=%ds",
            instrument_token,
            direction,
            score_bucket,
            adjusted_score,
            self._cfg.ttl_seconds,
        )
