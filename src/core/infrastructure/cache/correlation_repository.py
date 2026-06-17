"""Redis implementation of ICorrelationRepository.

Reads risk:correlation_matrix (JSON String, TTL 24h).
CONSERVATIVE_DEFAULT policy: returns empty dict on cache miss or Redis error.
Callers treat missing pairs as ρ=1.0.

The Redis client must be configured with decode_responses=True.
"""

from __future__ import annotations

import json
import logging

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.domain.interfaces.i_correlation_repository import ICorrelationRepository

_KEY = "risk:correlation_matrix"
_log = logging.getLogger(__name__)


class RedisCorrelationRepository(ICorrelationRepository):

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def get_matrix(self) -> dict[str, dict[str, float]]:
        try:
            raw: str | None = await self._redis.get(_KEY)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            _log.warning("correlation_matrix Redis error — applying CONSERVATIVE_DEFAULT: %s", exc)
            return {}

        if raw is None:
            return {}

        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise TypeError(f"expected dict, got {type(data).__name__}")
            return data
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            _log.warning(
                "correlation_matrix JSON parse failure — applying CONSERVATIVE_DEFAULT: %s", exc
            )
            return {}
