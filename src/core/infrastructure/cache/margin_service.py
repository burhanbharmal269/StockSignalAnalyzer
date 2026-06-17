"""Redis-backed margin service implementation.

Reads pre-computed per-lot margin requirements from risk:margin:{instrument_token}.
Margin data is written by MarginCachePoller (Phase 16).

FAIL_CLOSED: cache miss or Redis error → MarginDataUnavailableError.

Key format:
  risk:margin:{instrument_token}  →  Decimal string (margin per lot in INR)

Required margin for the proposed position:
  total_required = margin_per_lot × lots

The Redis client must be configured with decode_responses=True.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.domain.exceptions.risk import MarginDataUnavailableError
from core.domain.interfaces.i_margin_service import IMarginService
from core.infrastructure.config.risk_config import RiskConfig

_KEY_PREFIX = "risk:margin:"


class RedisMarginService(IMarginService):
    """Reads cached per-lot margin from Redis and multiplies by lot count.

    Falls back to MarginDataUnavailableError on cache miss (FAIL_CLOSED policy).
    Timeout is taken from config.margin.timeout_seconds (D-9).
    """

    def __init__(self, redis_client: Redis, config: RiskConfig) -> None:
        self._redis = redis_client
        self._config = config

    async def get_required_margin(
        self,
        instrument_token: int,
        lots: int,
        timeout_seconds: float,
    ) -> Decimal:
        timeout = self._config.margin.timeout_seconds
        key = f"{_KEY_PREFIX}{instrument_token}"
        try:
            raw: str | None = await asyncio.wait_for(
                self._redis.get(key),
                timeout=timeout,
            )
        except TimeoutError as exc:
            raise MarginDataUnavailableError(
                source="margin_cache",
                message=f"Redis timeout reading margin for instrument_token={instrument_token}",
            ) from exc
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise MarginDataUnavailableError(
                source="margin_cache",
                message=(
                    f"Redis unavailable reading margin for "
                    f"instrument_token={instrument_token}: {exc}"
                ),
            ) from exc

        if raw is None:
            raise MarginDataUnavailableError(
                source="margin_cache",
                message=(
                    f"No margin cached for instrument_token={instrument_token} — "
                    "MarginCachePoller has not written this token yet"
                ),
            )

        try:
            margin_per_lot = Decimal(raw)
        except InvalidOperation as exc:
            raise MarginDataUnavailableError(
                source="margin_cache",
                message=f"Invalid margin value for instrument_token={instrument_token}: {raw!r}",
            ) from exc

        return margin_per_lot * lots
