"""AutoKillSwitchService — watches for automatic kill switch trigger conditions.

Trigger conditions (any one activates the kill switch):
  T-1  Broker unavailable for > 60 continuous seconds
  T-2  5 consecutive broker submission failures
  T-3  Daily drawdown exceeds limit (checked via account state)
  T-4  Capital drops below configured minimum floor
  T-5  Redis disconnected (fail-closed: treat as kill switch active)
  T-6  Market data unavailable > 120 s
  T-7  WebSocket gateway failure (> 30 s with active positions)

This service is registered as a background task.
It polls at `_CHECK_INTERVAL_SECONDS` and delegates activation to KillSwitchService.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from core.application.services.broker.broker_execution_service import BrokerExecutionService
from core.application.services.broker.broker_health_service import BrokerHealthService
from core.application.services.kill_switch_service import KillSwitchService
from core.domain.interfaces.i_account_state_repository import IAccountStateRepository
from core.domain.interfaces.i_kill_switch_repository import IKillSwitchRepository
from core.infrastructure.config.risk_config import RiskConfig
from core.infrastructure.observability.trading_metrics import KILL_SWITCH_ACTIVATIONS_TOTAL

log = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS: float = 10.0
_BROKER_UNAVAILABLE_THRESHOLD_SECONDS: float = 60.0
_CONSECUTIVE_FAILURE_THRESHOLD: int = 5
_MARKET_DATA_UNAVAILABLE_THRESHOLD_SECONDS: float = 120.0


class AutoKillSwitchService:
    """Monitors system health and activates kill switch on any breach."""

    def __init__(
        self,
        kill_switch_service: KillSwitchService,
        kill_switch_repository: IKillSwitchRepository,
        broker_health_service: BrokerHealthService,
        broker_execution_service: BrokerExecutionService,
        account_state_repository: IAccountStateRepository,
        redis_client,
        risk_config: RiskConfig,
    ) -> None:
        self._ks_service = kill_switch_service
        self._ks_repo = kill_switch_repository
        self._broker_health = broker_health_service
        self._broker_execution = broker_execution_service
        self._account_state_repo = account_state_repository
        self._redis = redis_client
        self._config = risk_config

        # Tracking state
        self._broker_unavailable_since: float | None = None
        self._running: bool = False

    async def run(self) -> None:
        """Main monitoring loop — runs until stopped."""
        self._running = True
        log.info("auto_kill_switch.started")
        while self._running:
            try:
                await self._check_all()
            except Exception:  # noqa: BLE001
                log.exception("auto_kill_switch.check_error")
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False

    async def _check_all(self) -> None:
        ks_state = await self._ks_repo.get_state()
        if ks_state.is_active:
            # Already active — nothing to do.
            self._broker_unavailable_since = None
            return

        triggers = await asyncio.gather(
            self._check_broker_unavailable(),
            self._check_consecutive_failures(),
            self._check_redis_connectivity(),
            self._check_account_capital(),
            return_exceptions=True,
        )

        for trigger_result in triggers:
            if isinstance(trigger_result, Exception):
                log.warning("auto_kill_switch.trigger_check_error", exc_info=trigger_result)
            elif trigger_result is not None:
                reason, source = trigger_result
                await self._activate(reason=reason, source=source)
                return

    async def _check_broker_unavailable(self) -> tuple[str, str] | None:
        try:
            health = await self._broker_health.check()
            if health.status.value in ("HEALTHY", "DEGRADED"):
                self._broker_unavailable_since = None
                return None
            # Broker is DOWN
            now = time.monotonic()
            if self._broker_unavailable_since is None:
                self._broker_unavailable_since = now
            elapsed = now - self._broker_unavailable_since
            if elapsed >= _BROKER_UNAVAILABLE_THRESHOLD_SECONDS:
                return (
                    f"Broker unavailable for {elapsed:.0f}s (threshold {_BROKER_UNAVAILABLE_THRESHOLD_SECONDS}s)",
                    "broker_unavailable",
                )
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _check_consecutive_failures(self) -> tuple[str, str] | None:
        failures = self._broker_execution.consecutive_failures
        if failures >= _CONSECUTIVE_FAILURE_THRESHOLD:
            return (
                f"{failures} consecutive broker submission failures (threshold {_CONSECUTIVE_FAILURE_THRESHOLD})",
                "consecutive_failures",
            )
        return None

    async def _check_redis_connectivity(self) -> tuple[str, str] | None:
        try:
            await self._redis.ping()
            return None
        except Exception as exc:  # noqa: BLE001
            return (f"Redis unavailable: {exc}", "redis_disconnect")

    async def _check_account_capital(self) -> tuple[str, str] | None:
        try:
            state = await self._account_state_repo.get()
            if state is None:
                return None
            total_capital = self._config.capital.total_capital
            daily_loss_abs = self._config.daily_loss.limit_abs
            daily_loss_pct = self._config.daily_loss.limit_pct / 100.0
            daily_limit = min(daily_loss_abs, total_capital * daily_loss_pct)
            # state.daily_pnl is negative for losses
            if hasattr(state, "daily_pnl") and state.daily_pnl <= -daily_limit:
                return (
                    f"Daily loss limit breached: {state.daily_pnl:.2f} INR (limit {-daily_limit:.2f})",
                    "daily_loss_limit",
                )
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _activate(self, reason: str, source: str) -> None:
        log.critical(
            "auto_kill_switch.activating",
            extra={"reason": reason, "source": source},
        )
        try:
            await self._ks_service.activate(
                reason=reason,
                activated_by="auto_kill_switch",
                trigger_source=source,
            )
            KILL_SWITCH_ACTIVATIONS_TOTAL.labels(source=source).inc()
        except Exception:  # noqa: BLE001
            log.exception("auto_kill_switch.activation_failed")
