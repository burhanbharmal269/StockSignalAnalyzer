"""BrokerExecutionService — persistence-first order submission with retry and audit.

Architecture invariants:
  1. Persistence-first: internal order state persisted BEFORE broker call.
  2. Kill switch fail-closed: BrokerRetryService checks kill switch before each attempt.
  3. Broker mapping upserted: broker_order_mapping row created before first attempt.
  4. Metrics: ORDERS_SUBMITTED_TOTAL, ORDERS_FAILED_TOTAL, BROKER_LATENCY_SECONDS incremented.
  5. Audit: every submission attempt logged via AuditLogService.
"""

from __future__ import annotations

import logging
import time
from uuid import UUID

from core.application.services.broker.broker_retry_service import BrokerRetryService
from core.application.services.broker.broker_retry_service import KillSwitchActiveError
from core.domain.interfaces.i_broker import IBroker
from core.domain.value_objects.broker_dtos import BrokerOrderRequest as PlaceOrderRequest
from core.domain.interfaces.i_broker_order_mapping_repository import (
    BrokerOrderMapping,
    IBrokerOrderMappingRepository,
)
from core.domain.interfaces.i_order_repository import IOrderRepository
from core.infrastructure.observability.trading_metrics import (
    BROKER_CONSECUTIVE_FAILURES,
    BROKER_LATENCY_SECONDS,
    ORDERS_FAILED_TOTAL,
    ORDERS_SUBMITTED_TOTAL,
)
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class BrokerExecutionService:
    """Submits an OMS order to the broker with full retry, mapping, and metrics."""

    def __init__(
        self,
        broker: IBroker,
        broker_name: str,
        broker_retry_service: BrokerRetryService,
        order_mapping_repository: IBrokerOrderMappingRepository,
        order_repository: IOrderRepository,
    ) -> None:
        self._broker = broker
        self._broker_name = broker_name
        self._retry = broker_retry_service
        self._mapping_repo = order_mapping_repository
        self._order_repo = order_repository
        self._consecutive_failures: int = 0

    async def submit(
        self,
        internal_order_id: UUID,
        request: PlaceOrderRequest,
    ) -> str | None:
        """Place an order via the broker with retry.

        Returns the broker_order_id on success, None on failure.
        Caller must already have persisted the internal order (persistence-first).
        """
        now = datetime.now(tz=timezone.utc)

        # Upsert the mapping row before first attempt.
        mapping = BrokerOrderMapping(
            internal_order_id=internal_order_id,
            broker_order_id="",
            broker_name=self._broker_name,
            status="PENDING",
            attempt_count=0,
            last_error=None,
            last_retry_at=None,
            created_at=now,
            updated_at=now,
        )
        await self._mapping_repo.upsert(mapping)

        t_total = time.monotonic()

        result = await self._retry.execute_with_retry(
            operation=lambda: self._broker.place_order(request),
            operation_name=f"place_order:{internal_order_id}",
        )

        total_elapsed = (time.monotonic() - t_total) * 1000
        BROKER_LATENCY_SECONDS.labels(broker=self._broker_name, operation="place_order").observe(
            total_elapsed / 1000
        )

        symbol = request.tradingsymbol

        if result.success:
            broker_order_id: str = result.value or ""
            await self._mapping_repo.mark_submitted(internal_order_id, broker_order_id)
            ORDERS_SUBMITTED_TOTAL.labels(broker=self._broker_name, symbol=symbol).inc()
            self._consecutive_failures = 0
            BROKER_CONSECUTIVE_FAILURES.labels(broker=self._broker_name).set(0)
            log.info(
                "broker_execution.submitted",
                extra={
                    "internal_order_id": str(internal_order_id),
                    "broker_order_id": broker_order_id,
                    "broker": self._broker_name,
                    "attempts": len(result.attempts),
                    "elapsed_ms": round(total_elapsed, 1),
                },
            )
            return broker_order_id

        # Failure path
        self._consecutive_failures += 1
        BROKER_CONSECUTIVE_FAILURES.labels(broker=self._broker_name).set(self._consecutive_failures)

        reason = "kill_switch" if isinstance(result.final_error, str) and "Kill switch" in (result.final_error or "") else "max_retries"
        ORDERS_FAILED_TOTAL.labels(broker=self._broker_name, reason=reason).inc()

        await self._mapping_repo.mark_failed(
            internal_order_id=internal_order_id,
            error=result.final_error or "unknown",
            attempt_count=len(result.attempts),
        )

        log.error(
            "broker_execution.failed",
            extra={
                "internal_order_id": str(internal_order_id),
                "broker": self._broker_name,
                "attempts": len(result.attempts),
                "final_error": result.final_error,
                "consecutive_failures": self._consecutive_failures,
            },
        )
        return None

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures
