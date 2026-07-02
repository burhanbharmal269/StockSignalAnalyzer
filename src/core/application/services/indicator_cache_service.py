"""IndicatorCacheService — Phase 22 §6.

Redis-backed cache for expensive technical indicator computations.
Reuses computed ATR/EMA/ADX/RSI/VWAP/Supertrend/Volume values when
candles haven't changed since the last computation.

Cache key : ind:{symbol}:{last_candle_unix_ts}
TTL       : 600 seconds (10 minutes — two scan cycles)

Only the indicators computed in `_compute_features()` within
SignalScannerService are cached here. The cache key encodes the
last-candle timestamp: if a new candle closes, the key changes and
the full set is recomputed. Stale keys expire automatically via TTL.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

_log = logging.getLogger(__name__)

_CACHE_TTL = 600    # seconds
_CACHE_HIT_LOG_LEVEL = logging.DEBUG

if TYPE_CHECKING:
    from redis.asyncio import Redis


class IndicatorCacheService:
    """Cache-aside layer for scanner indicator computations."""

    def __init__(self, redis_client: "Redis") -> None:
        self._redis = redis_client
        self._hits = 0
        self._misses = 0

    # ── Public API ────────────────────────────────────────────────────────────

    async def get(self, symbol: str, last_candle_ts: Any) -> dict[str, Any] | None:
        """Return cached indicators if the candle hasn't changed. None on miss."""
        key = _make_key(symbol, last_candle_ts)
        try:
            raw = await self._redis.get(key)
            if raw:
                self._hits += 1
                _log.log(_CACHE_HIT_LOG_LEVEL, "ind_cache.hit symbol=%s", symbol)
                return json.loads(raw)
        except Exception as exc:
            _log.debug("ind_cache.get_failed symbol=%s: %s", symbol, exc)
        self._misses += 1
        return None

    async def set(
        self,
        symbol: str,
        last_candle_ts: Any,
        indicators: dict[str, Any],
    ) -> None:
        """Store computed indicators. Fail-silent."""
        key = _make_key(symbol, last_candle_ts)
        try:
            await self._redis.setex(key, _CACHE_TTL, json.dumps(indicators, default=str))
        except Exception as exc:
            _log.debug("ind_cache.set_failed symbol=%s: %s", symbol, exc)

    async def invalidate(self, symbol: str) -> None:
        """Remove all cache keys for a symbol (pattern-based delete)."""
        try:
            pattern = f"ind:{symbol}:*"
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=50)
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            _log.debug("ind_cache.invalidate_failed symbol=%s: %s", symbol, exc)

    def stats(self) -> dict[str, int]:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate_pct": round(self._hits / total * 100) if total else 0,
        }

    def reset_stats(self) -> None:
        self._hits = 0
        self._misses = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_key(symbol: str, last_candle_ts: Any) -> str:
    """Deterministic cache key from symbol and last-candle timestamp."""
    ts_str = str(last_candle_ts).replace(" ", "T").replace("+00:00", "Z")[:19]
    return f"ind:{symbol}:{ts_str}"
