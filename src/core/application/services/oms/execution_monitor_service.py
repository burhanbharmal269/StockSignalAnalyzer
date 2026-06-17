"""ExecutionMonitorService — monitors broker order status and processes fills.

Responsibilities:
  1. Poll broker for SUBMITTED / OPEN order status
  2. Process full fills → FILLED
  3. Process partial fills → PARTIALLY_FILLED
  4. Persist fill to executions table
  5. Update Order state
  6. Publish fill events

Called by a background task (e.g. WebSocket callback handler or polling loop).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from core.domain.entities.order import Order
from core.domain.enums.order_state import OrderState
from core.domain.events.order_events import OrderExpired, OrderFilled, OrderPartiallyFilled
from core.domain.exceptions.order import OrderPersistenceError
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_execution_repository import IExecutionRepository
from core.domain.interfaces.i_order_repository import IOrderRepository
from core.domain.interfaces.i_order_router import IOrderRouter
from core.domain.value_objects.execution_report import ExecutionReport
from core.domain.value_objects.fill import Fill

_log = logging.getLogger(__name__)

_MONITORABLE_STATES = {OrderState.SUBMITTED, OrderState.OPEN, OrderState.PARTIALLY_FILLED}


class ExecutionMonitorService:
    """Processes broker execution reports and updates Order entities."""

    def __init__(
        self,
        order_repository: IOrderRepository,
        execution_repository: IExecutionRepository,
        order_router: IOrderRouter,
        event_bus: IEventBus,
    ) -> None:
        self._order_repo = order_repository
        self._exec_repo = execution_repository
        self._router = order_router
        self._bus = event_bus

    async def process_execution_report(
        self,
        report: ExecutionReport,
        correlation_id: str = "",
    ) -> Order | None:
        """Apply an ExecutionReport to the matching Order.

        Returns the updated Order, or None if the order was not found.
        """
        order = await self._order_repo.get_by_broker_order_id(report.broker_order_id)
        if order is None:
            _log.warning(
                "Execution report for unknown broker_order_id=%s — ignoring",
                report.broker_order_id,
            )
            return None

        if order.state not in _MONITORABLE_STATES:
            _log.debug(
                "Execution report for order %s in terminal state %s — ignoring",
                order.order_id,
                order.state,
            )
            return order

        if report.is_fully_filled:
            await self._handle_full_fill(order, report, correlation_id)
        elif report.is_partial_fill:
            await self._handle_partial_fill(order, report, correlation_id)
        elif report.is_rejected:
            await self._handle_rejection(order, report, correlation_id)

        return order

    async def process_pending_orders(self) -> int:
        """Poll broker for all SUBMITTED/OPEN/PARTIALLY_FILLED orders.

        Returns the number of orders whose status was updated.
        """
        orders = []
        for state in _MONITORABLE_STATES:
            orders.extend(await self._order_repo.get_by_state(state))

        updated = 0
        for order in orders:
            if not order.broker_order_id:
                continue
            try:
                report = await self._router.get_order_status(order.broker_order_id)
                if report is None:
                    continue
                result = await self.process_execution_report(report)
                if result and result.state != order.state:
                    updated += 1
            except Exception:
                _log.exception(
                    "Error processing status for order %s", order.order_id
                )
        return updated

    async def expire_stale_orders(self) -> int:
        """OPEN orders past market close → EXPIRED."""
        open_orders = await self._order_repo.get_by_state(OrderState.OPEN)
        terminated = 0
        now = datetime.now(UTC)
        for order in open_orders:
            if order.submitted_at and (now - order.submitted_at).total_seconds() > 23400:
                # Market session (6.5 h) has elapsed
                order.expire()
                await self._save(order)
                await self._publish_safe(
                    OrderExpired(
                        order_id=order.order_id,
                        signal_id=order.signal_id,
                    )
                )
                terminated += 1
        return terminated

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _handle_full_fill(
        self,
        order: Order,
        report: ExecutionReport,
        correlation_id: str,
    ) -> None:
        fill_price = report.last_fill_price or report.average_fill_price
        if fill_price is None:
            _log.error(
                "Full fill report missing fill_price for order %s", order.order_id
            )
            return

        if order.state == OrderState.SUBMITTED:
            order.open_at_exchange()

        order.record_fill(report.filled_quantity, fill_price)
        await self._save(order)

        fill = Fill.create(
            order_id=order.order_id,
            broker_order_id=report.broker_order_id,
            filled_quantity=report.filled_quantity,
            fill_price=fill_price,
            fill_time=report.reported_at,
            exchange_trade_id=report.exchange_trade_id,
            trading_mode=order.trading_mode.value,
        )
        await self._save_fill(fill)

        await self._publish_safe(
            OrderFilled(
                order_id=order.order_id,
                signal_id=order.signal_id,
                filled_quantity=report.filled_quantity,
                average_fill_price=fill_price.value,
                filled_at=report.reported_at,
                correlation_id=correlation_id,
            )
        )
        _log.info(
            "Order %s FILLED qty=%d @ %s",
            order.order_id,
            report.filled_quantity,
            fill_price,
        )

    async def _handle_partial_fill(
        self,
        order: Order,
        report: ExecutionReport,
        correlation_id: str,
    ) -> None:
        fill_price = report.average_fill_price or report.last_fill_price
        if fill_price is None:
            return

        if order.state == OrderState.SUBMITTED:
            order.open_at_exchange()

        order.record_partial_fill(report.filled_quantity, fill_price)
        await self._save(order)

        fill = Fill.create(
            order_id=order.order_id,
            broker_order_id=report.broker_order_id,
            filled_quantity=report.last_fill_quantity or report.filled_quantity,
            fill_price=report.last_fill_price or fill_price,
            fill_time=report.reported_at,
            exchange_trade_id=report.exchange_trade_id,
            trading_mode=order.trading_mode.value,
        )
        await self._save_fill(fill)

        await self._publish_safe(
            OrderPartiallyFilled(
                order_id=order.order_id,
                filled_quantity=report.filled_quantity,
                remaining_quantity=report.remaining_quantity,
                average_fill_price=fill_price.value,
                correlation_id=correlation_id,
            )
        )

    async def _handle_rejection(
        self,
        order: Order,
        report: ExecutionReport,
        correlation_id: str,
    ) -> None:
        if order.state in (OrderState.SUBMITTED, OrderState.OPEN):
            if order.state == OrderState.SUBMITTED:
                order.open_at_exchange()
            order.reject(report.rejection_reason or report.status)
        elif order.state == OrderState.PARTIALLY_FILLED:
            order.cancel(report.rejection_reason or report.status)
        else:
            return

        await self._save(order)

        from core.domain.events.order_events import OrderRejected
        await self._publish_safe(
            OrderRejected(
                order_id=order.order_id,
                signal_id=order.signal_id,
                reason=report.rejection_reason,
                rejected_by="exchange",
                correlation_id=correlation_id,
            )
        )

    async def _save(self, order: Order) -> None:
        try:
            await self._order_repo.save(order)
        except Exception as exc:
            raise OrderPersistenceError(
                f"Failed to persist order {order.order_id}: {exc}"
            ) from exc

    async def _save_fill(self, fill: Fill) -> None:
        try:
            await self._exec_repo.save(fill)
        except Exception:
            _log.error("Failed to save fill %s — continuing", fill.fill_id)

    async def _publish_safe(self, event: object) -> None:
        try:
            await self._bus.publish(event)
        except Exception:
            _log.warning("Event publish failed for %s", type(event).__name__)
