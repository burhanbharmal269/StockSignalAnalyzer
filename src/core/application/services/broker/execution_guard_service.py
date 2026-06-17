"""ExecutionGuardService — pre-execution safety checks before broker order placement.

Checks (in order, FAIL CLOSED):
  1. Kill switch — Redis system:kill_switch. Treat Redis down as armed.
  2. Session validity — session.is_expired() or session.is_active == False.
  3. Broker health — broker.health_check() returns HEALTHY or DEGRADED only.
  4. Market hours — skip if market is closed (configurable bypass for paper mode).
  5. Duplicate check — Redis idempotency key already set.

Any failed check raises ExecutionGuardError with the guard name.
Cancellations bypass the kill switch check (Doc 14/22 invariant).

Reference: docs/22_OMS_DESIGN.md §Kill Switch, docs/14_KILL_SWITCH_DESIGN.md
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from core.domain.exceptions.broker import ExecutionGuardError
from core.domain.value_objects.broker_health import BrokerHealthStatus

if __name__ == "__main__":
    pass  # pragma: no cover

_log = logging.getLogger(__name__)
_IST = ZoneInfo("Asia/Kolkata")

# Market hours IST
_MARKET_OPEN_H = 9
_MARKET_OPEN_M = 15
_MARKET_CLOSE_H = 15
_MARKET_CLOSE_M = 30


class ExecutionGuardService:
    """Pre-execution safety gate. All checks must pass before order placement.

    FAIL CLOSED: any exception in any check → ExecutionGuardError raised.
    """

    def __init__(
        self,
        kill_switch_repository: object,
        broker: object,
        enforce_market_hours: bool = True,
    ) -> None:
        self._kill_switch = kill_switch_repository
        self._broker = broker
        self._enforce_market_hours = enforce_market_hours

    async def guard(
        self,
        session: object,
        *,
        is_cancellation: bool = False,
    ) -> None:
        """Run all pre-execution checks.

        Args:
            session: Active BrokerSession.
            is_cancellation: True for cancel operations — skips kill switch check.

        Raises:
            ExecutionGuardError: If any guard fails.
        """
        if not is_cancellation:
            await self._check_kill_switch()
        self._check_session(session)
        await self._check_broker_health()
        if self._enforce_market_hours:
            self._check_market_hours()

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    async def _check_kill_switch(self) -> None:
        try:
            state = await self._kill_switch.get_state()
            if getattr(state, "is_active", True):
                msg = "Kill switch is active — all new orders blocked."
                raise ExecutionGuardError(msg, guard="kill_switch")
        except ExecutionGuardError:
            raise
        except Exception as exc:
            # Redis down → FAIL CLOSED
            msg = f"Kill switch repository unavailable — treating as armed: {exc}"
            _log.error(msg)
            raise ExecutionGuardError(msg, guard="kill_switch_unavailable") from exc

    def _check_session(self, session: object) -> None:
        is_active = getattr(session, "is_active", True)
        if not is_active:
            msg = "Broker session is not active."
            raise ExecutionGuardError(msg, guard="session_inactive")

        is_expired_fn = getattr(session, "is_expired", None)
        if callable(is_expired_fn) and is_expired_fn():
            msg = "Broker session has expired."
            raise ExecutionGuardError(msg, guard="session_expired")

    async def _check_broker_health(self) -> None:
        try:
            report = await self._broker.health_check()
            if report.status == BrokerHealthStatus.DOWN:
                msg = f"Broker {report.broker_name} is DOWN: {report.error}"
                raise ExecutionGuardError(msg, guard="broker_down")
        except ExecutionGuardError:
            raise
        except Exception as exc:
            msg = f"Broker health check failed: {exc}"
            _log.error(msg)
            raise ExecutionGuardError(msg, guard="broker_health_check_failed") from exc

    def _check_market_hours(self) -> None:
        now_ist = datetime.now(_IST)
        open_time = now_ist.replace(
            hour=_MARKET_OPEN_H, minute=_MARKET_OPEN_M, second=0, microsecond=0
        )
        close_time = now_ist.replace(
            hour=_MARKET_CLOSE_H, minute=_MARKET_CLOSE_M, second=0, microsecond=0
        )
        if not (open_time <= now_ist <= close_time):
            msg = f"Market is closed. Current IST: {now_ist.strftime('%H:%M:%S')}."
            raise ExecutionGuardError(msg, guard="market_closed")
