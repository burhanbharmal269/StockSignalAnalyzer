"""BrokerRetryService — exponential back-off retry for broker order submission.

Retry schedule (5 max attempts):
  Attempt 1 — immediate
  Attempt 2 — 2 s
  Attempt 3 — 5 s
  Attempt 4 — 15 s
  Attempt 5 — 30 s

Error classification:
  RETRYABLE    — BrokerConnectionError, BrokerSessionExpiredError, timeout, rate-limit
  NON_RETRYABLE — BrokerOrderError with codes: MARGIN_INSUFFICIENT, INVALID_INSTRUMENT,
                  INVALID_QUANTITY, ORDER_REJECTED, DUPLICATE_ORDER

Architecture:
  - Kill switch checked before EVERY attempt; fail-closed.
  - BrokerRetryService is stateless — callers decide what to retry.
  - Returns BrokerRetryResult with final outcome and attempt log.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

from core.domain.exceptions.broker import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerOrderError,
    BrokerSessionExpiredError,
)
from core.domain.interfaces.i_kill_switch_repository import IKillSwitchRepository

log = logging.getLogger(__name__)

_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.0, 2.0, 5.0, 15.0, 30.0)
_MAX_ATTEMPTS = len(_RETRY_DELAYS_SECONDS)

# BrokerOrderError rejection codes that must NEVER be retried.
_NON_RETRYABLE_CODES: frozenset[str] = frozenset(
    {
        "MARGIN_INSUFFICIENT",
        "INSUFFICIENT_FUNDS",
        "INVALID_INSTRUMENT",
        "INVALID_QUANTITY",
        "INVALID_PRICE",
        "ORDER_REJECTED",
        "DUPLICATE_ORDER",
        "MARKET_CLOSED",
        "SYMBOL_NOT_FOUND",
    }
)

T = TypeVar("T")


@dataclass
class AttemptRecord:
    attempt: int
    elapsed_ms: float
    error: str | None


@dataclass
class BrokerRetryResult:
    success: bool
    value: Any | None
    attempts: list[AttemptRecord] = field(default_factory=list)
    final_error: str | None = None


class KillSwitchActiveError(Exception):
    """Raised when the kill switch is active before or between retry attempts."""


class BrokerRetryService:
    def __init__(self, kill_switch_repository: IKillSwitchRepository) -> None:
        self._ks_repo = kill_switch_repository

    def _is_retryable(self, exc: Exception) -> bool:
        if isinstance(exc, (BrokerConnectionError, BrokerSessionExpiredError)):
            return True
        if isinstance(exc, BrokerAuthenticationError):
            return True
        if isinstance(exc, BrokerOrderError):
            code = (getattr(exc, "code", "") or "").upper()
            return code not in _NON_RETRYABLE_CODES
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return True
        # Unknown errors are treated as retryable (safer for connectivity issues).
        return True

    async def _check_kill_switch(self) -> None:
        ks_state = await self._ks_repo.get_state()
        if ks_state.is_active:
            raise KillSwitchActiveError("Kill switch is active — aborting broker retry loop.")

    async def execute_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        operation_name: str = "broker_call",
    ) -> BrokerRetryResult:
        """Execute *operation* with exponential back-off retry.

        Fail-closed: kill switch checked before attempt 1 and between attempts.
        Non-retryable errors return immediately without further attempts.
        """
        attempts: list[AttemptRecord] = []

        for attempt_num in range(1, _MAX_ATTEMPTS + 1):
            delay = _RETRY_DELAYS_SECONDS[attempt_num - 1]
            if delay > 0:
                log.info(
                    "broker_retry.waiting",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt_num,
                        "delay_seconds": delay,
                    },
                )
                await asyncio.sleep(delay)

            try:
                await self._check_kill_switch()
            except KillSwitchActiveError as ks_exc:
                record = AttemptRecord(attempt=attempt_num, elapsed_ms=0.0, error=str(ks_exc))
                attempts.append(record)
                return BrokerRetryResult(
                    success=False,
                    value=None,
                    attempts=attempts,
                    final_error=str(ks_exc),
                )

            t0 = time.monotonic()
            error_str: str | None = None
            try:
                result = await operation()
                elapsed_ms = (time.monotonic() - t0) * 1000
                attempts.append(AttemptRecord(attempt=attempt_num, elapsed_ms=elapsed_ms, error=None))
                log.info(
                    "broker_retry.success",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt_num,
                        "elapsed_ms": round(elapsed_ms, 1),
                    },
                )
                return BrokerRetryResult(success=True, value=result, attempts=attempts)

            except Exception as exc:  # noqa: BLE001
                elapsed_ms = (time.monotonic() - t0) * 1000
                error_str = f"{type(exc).__name__}: {exc}"
                attempts.append(
                    AttemptRecord(attempt=attempt_num, elapsed_ms=elapsed_ms, error=error_str)
                )

                if not self._is_retryable(exc):
                    log.warning(
                        "broker_retry.non_retryable",
                        extra={
                            "operation": operation_name,
                            "attempt": attempt_num,
                            "error": error_str,
                        },
                    )
                    return BrokerRetryResult(
                        success=False,
                        value=None,
                        attempts=attempts,
                        final_error=error_str,
                    )

                if attempt_num == _MAX_ATTEMPTS:
                    log.error(
                        "broker_retry.exhausted",
                        extra={
                            "operation": operation_name,
                            "total_attempts": attempt_num,
                            "final_error": error_str,
                        },
                    )
                else:
                    log.warning(
                        "broker_retry.attempt_failed",
                        extra={
                            "operation": operation_name,
                            "attempt": attempt_num,
                            "error": error_str,
                            "next_delay_seconds": _RETRY_DELAYS_SECONDS[attempt_num]
                            if attempt_num < _MAX_ATTEMPTS
                            else None,
                        },
                    )

        return BrokerRetryResult(
            success=False,
            value=None,
            attempts=attempts,
            final_error=attempts[-1].error if attempts else "unknown",
        )
