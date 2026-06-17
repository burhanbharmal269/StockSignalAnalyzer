"""OrderRouterService — routes a validated order to the broker.

Responsibilities:
  1. Transition order PENDING → SUBMITTING
  2. Call broker via IOrderRouter
  3. On success: SUBMITTING → SUBMITTED (broker_order_id set)
  4. On broker failure: SUBMITTING → REJECTED_PRE_SUBMIT (fail closed)
  5. Persist updated order (persistence-first after each transition)
  6. Publish OrderRouted or OrderRejected

Fail-closed: if the broker is unavailable, no order exists at the exchange.
The Order entity is transitioned to REJECTED_PRE_SUBMIT and persisted.
"""

from __future__ import annotations

import logging

from core.domain.entities.order import Order
from core.domain.events.order_events import OrderRejected, OrderRouted, OrderValidated
from core.domain.exceptions.order import BrokerUnavailableError, OrderPersistenceError
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_order_repository import IOrderRepository
from core.domain.interfaces.i_order_router import IOrderRouter

_log = logging.getLogger(__name__)


class OrderRouterService:
    """Routes a validated PENDING order to the broker.

    Called by OrderManagementService after persistence-first saves the order.
    """

    def __init__(
        self,
        order_router: IOrderRouter,
        order_repository: IOrderRepository,
        event_bus: IEventBus,
    ) -> None:
        self._router = order_router
        self._repo = order_repository
        self._bus = event_bus

    async def route(self, order: Order, correlation_id: str = "") -> Order:
        """Route order to broker. Returns updated Order.

        Raises OrderPersistenceError if DB fails after state transition.
        Fail-closed: broker failure → REJECTED_PRE_SUBMIT.
        """
        # Publish validation success
        await self._publish_safe(
            OrderValidated(
                order_id=order.order_id,
                signal_id=order.signal_id,
                correlation_id=correlation_id,
            )
        )

        # PENDING → SUBMITTING
        order.start_submission()
        await self._save(order)

        try:
            broker_order_id = await self._router.route(order)
        except BrokerUnavailableError as exc:
            _log.error(
                "Broker unavailable for order %s — failing closed: %s",
                order.order_id,
                exc,
            )
            order.reject_pre_submit(f"broker_unavailable: {exc}")
            await self._save(order)
            await self._publish_safe(
                OrderRejected(
                    order_id=order.order_id,
                    signal_id=order.signal_id,
                    reason=str(exc),
                    rejected_by="broker",
                    correlation_id=correlation_id,
                )
            )
            raise  # Re-raise: fail-closed means caller knows about the failure
        except Exception as exc:
            _log.exception("Unexpected error routing order %s", order.order_id)
            order.reject_pre_submit(f"routing_error: {exc}")
            await self._save(order)
            await self._publish_safe(
                OrderRejected(
                    order_id=order.order_id,
                    signal_id=order.signal_id,
                    reason=str(exc),
                    rejected_by="oms",
                    correlation_id=correlation_id,
                )
            )
            raise BrokerUnavailableError(str(exc)) from exc

        # SUBMITTING → SUBMITTED
        order.confirm_submitted(broker_order_id)
        await self._save(order)

        await self._publish_safe(
            OrderRouted(
                order_id=order.order_id,
                signal_id=order.signal_id,
                broker_order_id=broker_order_id,
                broker_name=self._router.__class__.__name__,
                correlation_id=correlation_id,
            )
        )

        _log.info(
            "Order %s routed → broker_order_id=%s",
            order.order_id,
            broker_order_id,
        )
        return order

    async def cancel(self, order: Order, reason: str = "", correlation_id: str = "") -> Order:
        """Cancel an open order at the broker (bypass kill switch per Doc 14/22)."""
        try:
            await self._router.cancel(order)
        except Exception as exc:
            _log.error("Cancel failed for order %s: %s", order.order_id, exc)
            # Still mark as cancelled in OMS (broker cancel may have succeeded)

        order.cancel(reason)
        await self._save(order)

        from core.domain.events.order_events import OrderCancelled
        await self._publish_safe(
            OrderCancelled(
                order_id=order.order_id,
                signal_id=order.signal_id,
                reason=reason,
                correlation_id=correlation_id,
            )
        )
        return order

    async def _save(self, order: Order) -> None:
        try:
            await self._repo.save(order)
        except Exception as exc:
            raise OrderPersistenceError(
                f"Failed to persist order {order.order_id} state {order.state}: {exc}"
            ) from exc

    async def _publish_safe(self, event: object) -> None:
        try:
            await self._bus.publish(event)
        except Exception:
            _log.warning("Event publish failed for %s", type(event).__name__)
