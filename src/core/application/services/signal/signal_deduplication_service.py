"""SignalDeduplicationService — Redis-backed fingerprint deduplication.

Prevents duplicate signals for the same instrument/direction/strategy/regime/weights
within the configured dedup TTL window. Wraps ISignalCacheRepository.

Dedup key: signal:dedup:{token}:{direction}:{strategy_type}:{regime}:{weights_sha256}

Including strategy_type and regime means NIFTY LONG Trend Strategy and
NIFTY LONG Mean Reversion Strategy are NOT considered duplicates.
"""

from __future__ import annotations

import logging

from core.domain.interfaces.i_signal_cache_repository import ISignalCacheRepository
from core.infrastructure.config.signal_config import SignalConfig

_log = logging.getLogger(__name__)


class SignalDeduplicationService:
    """Checks and registers signal dedup keys in Redis.

    Redis errors are caught and treated as non-duplicate (fail-open) so that
    a Redis outage does not halt signal generation. This is acceptable because:
    - Dedup is a convenience guard, not a safety-critical invariant.
    - If Redis is down, duplicate signals may be generated; they will be
      caught by the DB unique constraint or treated as independent signals.
    - Persistence (DB) is separately enforced and never fail-open.
    """

    def __init__(
        self,
        cache: ISignalCacheRepository,
        config: SignalConfig,
    ) -> None:
        self._cache = cache
        self._config = config

    async def is_duplicate(
        self,
        instrument_token: int,
        direction: str,
        strategy_type: str,
        regime: str,
        weights_sha256: str,
    ) -> bool:
        """Return True if an identical signal exists within the dedup window."""
        key = self._config.dedup_key(
            instrument_token, direction, strategy_type, regime, weights_sha256
        )
        result = await self._cache.is_duplicate(key)
        if result:
            _log.info(
                "Signal deduplicated: token=%s direction=%s strategy=%s regime=%s",
                instrument_token,
                direction,
                strategy_type,
                regime,
            )
        return result

    async def register(
        self,
        instrument_token: int,
        direction: str,
        strategy_type: str,
        regime: str,
        weights_sha256: str,
        signal_id: str,
    ) -> None:
        """Register a new signal in the dedup window.

        Must be called AFTER the signal has been persisted to the DB.
        """
        key = self._config.dedup_key(
            instrument_token, direction, strategy_type, regime, weights_sha256
        )
        await self._cache.set_dedup(key, signal_id, self._config.dedup_ttl_seconds)
        _log.debug(
            "Dedup key set: %s → %s (ttl=%ds)",
            key, signal_id, self._config.dedup_ttl_seconds,
        )
