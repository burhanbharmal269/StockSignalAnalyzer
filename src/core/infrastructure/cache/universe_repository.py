"""Redis implementation of IUniverseRepository.

Keys:
  universe:selected                    String (JSON), TTL = cache_ttl_seconds
  universe:metadata:{instrument_token} Hash,          TTL = cache_ttl_seconds

Read: get_selected() deserialises universe:selected back into a UniverseSelected event.
Write: save_selected() atomically sets both key families via pipeline.

The Redis client must be configured with decode_responses=True.

Reference: docs/architecture_decisions/AD-USE-01.md (Redis Key Usage)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, date

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.domain.events.universe_events import UniverseSelected
from core.domain.interfaces.i_universe_repository import IUniverseRepository
from core.domain.universe.selected_instrument import SelectedInstrument

_SELECTED_KEY = "universe:selected"
_METADATA_PREFIX = "universe:metadata:"

_log = logging.getLogger(__name__)


class RedisUniverseRepository(IUniverseRepository):
    """Persists and retrieves the Universe Selection Engine output via Redis."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def save_selected(self, event: UniverseSelected, ttl_seconds: int) -> None:
        """Write universe:selected and per-instrument metadata hashes atomically."""
        payload = _serialise_event(event)
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.set(_SELECTED_KEY, json.dumps(payload), ex=ttl_seconds)
            for inst in event.instruments:
                meta_key = f"{_METADATA_PREFIX}{inst.instrument_token}"
                flat: dict[str, str] = {
                    k: str(v) for k, v in inst.filter_metadata.items()
                }
                flat["rank"] = str(inst.rank)
                flat["composite_score"] = str(inst.composite_score)
                flat["protected"] = str(inst.protected)
                pipe.hset(meta_key, mapping=flat)
                pipe.expire(meta_key, ttl_seconds)
            await pipe.execute()
        except (RedisConnectionError, RedisTimeoutError) as exc:
            _log.warning(
                "universe_repository_write_failed ttl=%d instruments=%d: %s",
                ttl_seconds,
                len(event.instruments),
                exc,
            )
            raise

    async def get_selected(self) -> UniverseSelected | None:
        """Return the cached UniverseSelected event, or None when absent/expired."""
        try:
            raw: str | None = await self._redis.get(_SELECTED_KEY)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            _log.warning("universe_repository_read_failed: %s", exc)
            return None

        if raw is None:
            return None

        try:
            data = json.loads(raw)
            return _deserialise_event(data)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            _log.warning("universe_repository_decode_failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _serialise_event(event: UniverseSelected) -> dict:  # type: ignore[type-arg]
    return {
        "event_id": str(event.event_id),
        "occurred_at": event.occurred_at.isoformat(),
        "total_eligible": event.total_eligible,
        "total_filtered_out": event.total_filtered_out,
        "evaluation_cycle_ms": event.evaluation_cycle_ms,
        "protected_count": event.protected_count,
        "universe_enabled": event.universe_enabled,
        "instruments": [_serialise_instrument(i) for i in event.instruments],
    }


def _serialise_instrument(inst: SelectedInstrument) -> dict:  # type: ignore[type-arg]
    return {
        "instrument_token": inst.instrument_token,
        "underlying": inst.underlying,
        "instrument_class": inst.instrument_class,
        "expiry_date": inst.expiry_date.isoformat(),
        "sector": inst.sector,
        "composite_score": inst.composite_score,
        "rank": inst.rank,
        "protected": inst.protected,
        "filter_metadata": inst.filter_metadata,
    }


def _deserialise_event(data: dict) -> UniverseSelected:  # type: ignore[type-arg]
    instruments = tuple(
        _deserialise_instrument(i) for i in data.get("instruments", [])
    )
    return UniverseSelected(
        total_eligible=int(data["total_eligible"]),
        total_filtered_out=int(data["total_filtered_out"]),
        evaluation_cycle_ms=int(data["evaluation_cycle_ms"]),
        protected_count=int(data["protected_count"]),
        universe_enabled=bool(data["universe_enabled"]),
        instruments=instruments,
        occurred_at=datetime.fromisoformat(data["occurred_at"]),
    )


def _deserialise_instrument(data: dict) -> SelectedInstrument:  # type: ignore[type-arg]
    return SelectedInstrument(
        instrument_token=int(data["instrument_token"]),
        underlying=str(data["underlying"]),
        instrument_class=str(data["instrument_class"]),
        expiry_date=date.fromisoformat(data["expiry_date"]),
        sector=str(data["sector"]),
        composite_score=float(data["composite_score"]),
        rank=int(data["rank"]),
        protected=bool(data["protected"]),
        filter_metadata=dict(data.get("filter_metadata", {})),
    )
