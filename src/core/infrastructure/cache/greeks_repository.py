"""Redis implementation of IGreeksRepository.

Two-tier cache with atomic pipeline writes:
  Tier 1: risk:greeks:{position_id}          TTL = config.greeks.max_age_seconds   (primary)
  Tier 2: risk:greeks:fallback:{position_id} TTL = config.greeks.fallback_ttl_seconds (fallback)

Read priority:
  1. Tier 1 — use if computed_at age <= max_age_seconds
  2. Tier 2 — use with from_fallback=True
  3. Both miss → return None for this position_id

The Redis client must be configured with decode_responses=True.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.domain.exceptions.risk import DataSourceUnavailableError
from core.domain.interfaces.i_greeks_repository import IGreeksRepository
from core.domain.risk.greeks_snapshot import GreeksSnapshot

_T1_PREFIX = "risk:greeks:"
_T2_PREFIX = "risk:greeks:fallback:"
_SOURCE = "greeks_cache"

_log = logging.getLogger(__name__)


def _t1_key(position_id: str) -> str:
    return f"{_T1_PREFIX}{position_id}"


def _t2_key(position_id: str) -> str:
    return f"{_T2_PREFIX}{position_id}"


def _decode_snapshot(raw: str, position_id: str, from_fallback: bool) -> GreeksSnapshot | None:
    try:
        data: dict[str, object] = json.loads(raw)
        return GreeksSnapshot(
            position_id=position_id,
            delta=float(data["delta"]),  # type: ignore[arg-type]
            gamma=float(data["gamma"]),  # type: ignore[arg-type]
            theta=float(data["theta"]),  # type: ignore[arg-type]
            vega=float(data["vega"]),  # type: ignore[arg-type]
            computed_at=datetime.fromisoformat(str(data["computed_at"])),
            from_fallback=from_fallback,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        _log.warning(
            "greeks_cache decode failure position_id=%s from_fallback=%s",
            position_id,
            from_fallback,
        )
        return None


class RedisGreeksRepository(IGreeksRepository):

    def __init__(self, redis_client: Redis, tier1_ttl_seconds: int, tier2_ttl_seconds: int) -> None:
        self._redis = redis_client
        self._tier1_ttl = tier1_ttl_seconds
        self._tier2_ttl = tier2_ttl_seconds

    async def get_portfolio_greeks(
        self,
        position_ids: list[str],
        max_age_seconds: int,
        new_position_grace_seconds: int,
    ) -> dict[str, GreeksSnapshot | None]:
        if not position_ids:
            return {}

        t1_keys = [_t1_key(pid) for pid in position_ids]
        t2_keys = [_t2_key(pid) for pid in position_ids]
        all_keys = t1_keys + t2_keys

        try:
            values: list[str | None] = await self._redis.mget(all_keys)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis unavailable reading Greeks: {exc}",
            ) from exc

        n = len(position_ids)
        t1_values = values[:n]
        t2_values = values[n:]

        now = datetime.now(UTC)
        result: dict[str, GreeksSnapshot | None] = {}

        for pid, t1_raw, t2_raw in zip(position_ids, t1_values, t2_values, strict=True):
            snap: GreeksSnapshot | None = None

            if t1_raw is not None:
                t1_snap = _decode_snapshot(t1_raw, pid, from_fallback=False)
                if t1_snap is not None:
                    computed = t1_snap.computed_at
                    if computed.tzinfo is None:
                        computed = computed.replace(tzinfo=UTC)
                    age = (now - computed).total_seconds()
                    if age <= max_age_seconds:
                        snap = t1_snap

            if snap is None and t2_raw is not None:
                snap = _decode_snapshot(t2_raw, pid, from_fallback=True)

            result[pid] = snap

        return result

    async def write_greeks(self, position_id: str, snapshot: GreeksSnapshot) -> None:
        payload = json.dumps(
            {
                "delta": snapshot.delta,
                "gamma": snapshot.gamma,
                "theta": snapshot.theta,
                "vega": snapshot.vega,
                "computed_at": snapshot.computed_at.isoformat(),
            }
        )
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.set(_t1_key(position_id), payload, ex=self._tier1_ttl)
            pipe.set(_t2_key(position_id), payload, ex=self._tier2_ttl)
            await pipe.execute()
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis write failure for position_id={position_id}: {exc}",
            ) from exc
