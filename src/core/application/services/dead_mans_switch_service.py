"""DeadMansSwitchService — connectivity watchdog that activates the kill switch
on sustained infrastructure failures.

Monitors:
  - Redis connectivity (PING with timeout)
  - Database connectivity (single lightweight query)

When consecutive failure count reaches the configured threshold for either
source, the kill switch is activated via KillSwitchService.

Configuration is loaded from dead_mans_switch section of risk.yaml:
  redis_check_interval_seconds
  redis_failure_threshold
  db_check_interval_seconds
  db_failure_threshold

Runs as a supervised background task via BackgroundTaskRegistry (D-12).
"""

from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.kill_switch_service import KillSwitchService
from core.infrastructure.config.risk_config import RiskConfig

_log = logging.getLogger(__name__)

_PING_TIMEOUT_SECONDS: float = 2.0
_DB_QUERY_TIMEOUT_SECONDS: float = 2.0


class DeadMansSwitchService:

    def __init__(
        self,
        kill_switch_service: KillSwitchService,
        redis_client: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        config: RiskConfig,
    ) -> None:
        self._ks_service = kill_switch_service
        self._redis = redis_client
        self._session_factory = session_factory
        self._config = config

        self._redis_failures: int = 0
        self._db_failures: int = 0

    async def run(self) -> None:
        """Continuous monitoring loop.  Runs until cancelled."""
        _log.info("dead_mans_switch_service started")
        cfg = self._config.dead_mans_switch
        while True:
            try:
                redis_ok = await self._check_redis()
                db_ok = await self._check_db()

                if redis_ok:
                    self._redis_failures = 0
                else:
                    self._redis_failures += 1
                    _log.warning(
                        "dead_mans_switch redis failure count=%d threshold=%d",
                        self._redis_failures,
                        cfg.redis_failure_threshold,
                    )
                    if self._redis_failures >= cfg.redis_failure_threshold:
                        reason = f"Redis unavailable for {self._redis_failures} consecutive checks"
                        _log.critical("dead_mans_switch.redis_threshold_exceeded reason=%s (auto-activation disabled)", reason)

                if db_ok:
                    self._db_failures = 0
                else:
                    self._db_failures += 1
                    _log.warning(
                        "dead_mans_switch db failure count=%d threshold=%d",
                        self._db_failures,
                        cfg.db_failure_threshold,
                    )
                    if self._db_failures >= cfg.db_failure_threshold:
                        reason = f"Database unavailable for {self._db_failures} consecutive checks"
                        _log.critical("dead_mans_switch.db_threshold_exceeded reason=%s (auto-activation disabled)", reason)

            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("dead_mans_switch_cycle_error")

            await asyncio.sleep(cfg.redis_check_interval_seconds)

    async def _check_redis(self) -> bool:
        try:
            await asyncio.wait_for(self._redis.ping(), timeout=_PING_TIMEOUT_SECONDS)
            return True
        except (TimeoutError, RedisConnectionError, RedisTimeoutError):
            return False
        except Exception:
            return False

    async def _check_db(self) -> bool:
        try:
            async with self._session_factory() as session:
                await asyncio.wait_for(
                    session.execute(
                        __import__("sqlalchemy").text("SELECT 1")
                    ),
                    timeout=_DB_QUERY_TIMEOUT_SECONDS,
                )
            return True
        except TimeoutError:
            return False
        except Exception:
            return False
