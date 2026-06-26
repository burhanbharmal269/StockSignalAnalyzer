"""PipelineEventHandler — domain event → service dispatch.

Bridges Redis Stream events to downstream application services:

  SignalRiskApproved  → OrderManagementService → OrderRouterService
  OrderFilled         → PositionManagerService → ExitManagerService (SL)
  OrderPartiallyFilled → PositionManagerService MTM update (logged only)

This class holds no state. It is constructed once at startup and its
handle_* methods are registered as Redis Stream consumer callbacks.

Invariants:
  - Persistence-first: OMS saves Order before route() is called.
  - Fail-closed: handler exceptions are caught and logged — never propagate
    out to the Redis consumer loop (which would stall the consumer group).
  - Cancellations bypass kill switch (IOrderRouter contract).
  - Parent-order fills (SL/target) are identified by order.parent_position_id
    and routed to ExitManagerService, not PositionManagerService.
"""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.events.base import DomainEvent
from core.domain.events.order_events import OrderFilled, OrderPartiallyFilled
from core.domain.events.signal_events import SignalRiskApproved
from core.domain.exceptions.order import (
    KillSwitchActiveError,
    OrderPersistenceError,
    OrderRateLimitError,
    SignalExpiredError,
)
from core.domain.value_objects.price import Price

if TYPE_CHECKING:
    from core.application.services.execution_lock_service import ExecutionLockService
    from core.application.services.oms.exit_manager_service import ExitManagerService
    from core.application.services.oms.order_management_service import OrderManagementService
    from core.application.services.oms.order_router_service import OrderRouterService
    from core.application.services.oms.position_manager_service import PositionManagerService
    from core.application.services.portfolio_intelligence_service import PortfolioIntelligenceService
    from core.domain.interfaces.i_order_repository import IOrderRepository
    from core.domain.interfaces.i_position_repository import IPositionRepository

_log = logging.getLogger(__name__)


class PipelineEventHandler:
    """Dispatches domain events to the appropriate application services.

    Methods are registered as async callbacks on the event bus and must not
    raise — all exceptions are caught, logged, and swallowed so the Redis
    consumer group continues processing.
    """

    def __init__(
        self,
        order_management_service: "OrderManagementService",
        order_router_service: "OrderRouterService",
        order_repository: "IOrderRepository",
        position_manager_service: "PositionManagerService",
        exit_manager_service: "ExitManagerService",
        position_repository: "IPositionRepository",
        execution_lock_service: "ExecutionLockService | None" = None,
        portfolio_intelligence_svc: "PortfolioIntelligenceService | None" = None,
    ) -> None:
        self._oms = order_management_service
        self._router = order_router_service
        self._order_repo = order_repository
        self._position_mgr = position_manager_service
        self._exit_mgr = exit_manager_service
        self._position_repo = position_repository
        self._execution_lock = execution_lock_service
        self._portfolio_svc  = portfolio_intelligence_svc

    # ------------------------------------------------------------------
    # Signal → OMS
    # ------------------------------------------------------------------

    async def handle_signal_risk_approved(self, event: DomainEvent) -> None:
        """SignalRiskApproved → create + route order.

        1. OMS creates Order (PENDING) and persists it (persistence-first).
        2. OrderRouterService routes PENDING → SUBMITTED.
        """
        if not isinstance(event, SignalRiskApproved):
            _log.warning(
                "handle_signal_risk_approved: unexpected event type %s",
                type(event).__name__,
            )
            return

        _log.info(
            "PipelineEventHandler: SignalRiskApproved signal_id=%s instrument=%s",
            event.signal_id,
            event.instrument_token,
        )

        # Execution lock gate — signals ALWAYS flow; orders only placed when UNLOCKED + AUTOMATIC
        if self._execution_lock and await self._execution_lock.is_order_execution_blocked():
            _log.info(
                "execution_lock.orders_blocked signal_id=%s — signal stored, no order placed",
                event.signal_id,
            )
            return

        # Portfolio heat hard gate (Phase 21.1 §7) — blocks order when heat >= 100%.
        # Signal remains stored in the DB for operator review; only execution is gated.
        # Fail-open: if the check itself errors, we proceed rather than block valid signals.
        if self._portfolio_svc:
            try:
                heat_blocked, heat_pct = await self._portfolio_svc.check_heat_hard_gate()
                if heat_blocked:
                    _log.warning(
                        "PipelineEventHandler: portfolio_heat_gate signal_id=%s heat=%.1f%% "
                        "— order blocked; signal stored for operator review",
                        event.signal_id, heat_pct,
                    )
                    return
            except Exception as _heat_exc:
                _log.warning(
                    "portfolio_heat_gate_exception signal_id=%s — proceeding without heat check: %s",
                    event.signal_id, _heat_exc,
                )

        # Market context size multiplier (Phase 21.1 §1) — scale lots before OMS.
        # NORMAL=1.0 (no change), CAUTION=0.75, HIGH_RISK=0.50, PANIC=0.0.
        # PANIC is already handled by execution_lock above; this covers CAUTION/HIGH_RISK
        # where orders are permitted but must be sized down proportionally.
        # If adjusted_lots rounds to 0, block — equivalent to PANIC signal with tiny base size.
        # Fail-open: on any error, proceed with the engine's original lot count.
        if self._portfolio_svc and event.position_size_lots > 0:
            try:
                size_mult = await self._portfolio_svc.get_current_size_multiplier()
                if size_mult < 1.0:
                    adjusted_lots = math.floor(event.position_size_lots * size_mult)
                    if adjusted_lots <= 0:
                        _log.warning(
                            "PipelineEventHandler: context_size_gate signal_id=%s "
                            "lots=%d mult=%.2f adjusted=0 — order blocked",
                            event.signal_id, event.position_size_lots, size_mult,
                        )
                        return
                    if adjusted_lots != event.position_size_lots:
                        _log.info(
                            "PipelineEventHandler: context_size_adjusted signal_id=%s "
                            "lots=%d→%d mult=%.2f",
                            event.signal_id, event.position_size_lots, adjusted_lots, size_mult,
                        )
                        event = replace(event, position_size_lots=adjusted_lots)
            except Exception as _size_exc:
                _log.warning(
                    "context_size_gate_exception signal_id=%s — proceeding with original lots: %s",
                    event.signal_id, _size_exc,
                )

        # Step 1 — OMS creates the order
        try:
            result = await self._oms.process_signal_risk_approved(event)
        except OrderPersistenceError:
            _log.critical(
                "OMS persistence failed for signal_id=%s — order not created",
                event.signal_id,
            )
            return
        except (KillSwitchActiveError, SignalExpiredError, OrderRateLimitError) as exc:
            _log.warning(
                "OMS rejected signal_id=%s: %s", event.signal_id, exc
            )
            return
        except Exception:
            _log.exception(
                "Unexpected OMS error for signal_id=%s", event.signal_id
            )
            return

        if not result.accepted or result.order_id is None:
            _log.info(
                "OMS did not accept signal_id=%s (duplicate=%s reason=%s)",
                event.signal_id,
                result.is_duplicate,
                result.rejection_reason,
            )
            return

        # Step 2 — Route to broker
        order = await self._order_repo.get_by_id(result.order_id)
        if order is None:
            _log.error(
                "Order %s not found after OMS create — cannot route",
                result.order_id,
            )
            return

        try:
            await self._router.route(order, correlation_id=str(event.correlation_id))
            _log.info(
                "Order %s routed for signal_id=%s broker_order_id=%s",
                order.order_id,
                event.signal_id,
                order.broker_order_id,
            )
        except Exception:
            _log.exception("Order routing failed for order_id=%s", result.order_id)

    # ------------------------------------------------------------------
    # Order filled → Position
    # ------------------------------------------------------------------

    async def handle_order_filled(self, event: DomainEvent) -> None:
        """OrderFilled → open position (entry) or close position (SL/target).

        Entry fill:  order.parent_position_id is None → open new position.
        Exit fill:   order.parent_position_id is set  → route to ExitManager.
        """
        if not isinstance(event, OrderFilled):
            _log.warning(
                "handle_order_filled: unexpected event type %s",
                type(event).__name__,
            )
            return

        _log.info(
            "PipelineEventHandler: OrderFilled order_id=%s qty=%d @ %s",
            event.order_id,
            event.filled_quantity,
            event.average_fill_price,
        )

        order = await self._order_repo.get_by_id(event.order_id)
        if order is None:
            _log.warning(
                "OrderFilled: order %s not found in repository", event.order_id
            )
            return

        # Determine if this is an entry fill or an exit fill
        if order.parent_position_id is not None:
            await self._handle_exit_fill(order, event)
        else:
            await self._handle_entry_fill(order, event)

    async def _handle_entry_fill(
        self, order: object, event: OrderFilled
    ) -> None:
        """Primary order filled → open position and place SL."""
        try:
            position = await self._position_mgr.open_position(order)
            _log.info(
                "Position opened: %s for order %s",
                position.position_id,
                event.order_id,
            )
        except Exception:
            _log.exception(
                "Failed to open position for order_id=%s", event.order_id
            )
            return

        # Place stop-loss order immediately after position opens
        try:
            sl_order = await self._exit_mgr.place_stop_loss_order(position)
            if sl_order:
                _log.info(
                    "SL order %s placed for position %s",
                    sl_order.order_id,
                    position.position_id,
                )
        except Exception:
            _log.exception(
                "SL placement failed for position %s — position is OPEN without SL",
                position.position_id,
            )

    async def _handle_exit_fill(
        self, order: object, event: OrderFilled
    ) -> None:
        """SL or target order filled → close position via ExitManagerService."""
        parent_position_id = order.parent_position_id
        position = await self._position_repo.get_by_id(parent_position_id)
        if position is None:
            _log.warning(
                "ExitFill: parent position %s not found for order %s",
                parent_position_id,
                event.order_id,
            )
            return

        fill_price = Price(event.average_fill_price)

        # Determine if this is SL or target by comparing with position's stop
        is_sl_fill = (
            position.stop_order_id is not None
            and str(order.order_id) == str(position.stop_order_id)
        )

        try:
            if is_sl_fill:
                await self._exit_mgr.handle_stop_loss_fill(
                    position, fill_price, order.order_id
                )
                _log.info(
                    "SL triggered: position %s closed at %s",
                    position.position_id,
                    fill_price,
                )
            else:
                await self._exit_mgr.handle_target_fill(
                    position, fill_price, order.order_id
                )
                _log.info(
                    "Target triggered: position %s closed at %s",
                    position.position_id,
                    fill_price,
                )
        except Exception:
            _log.exception(
                "Exit handler failed for position %s order %s",
                parent_position_id,
                event.order_id,
            )

    # ------------------------------------------------------------------
    # Partial fill — logging only
    # ------------------------------------------------------------------

    async def handle_order_partially_filled(self, event: DomainEvent) -> None:
        """OrderPartiallyFilled — logged; position update deferred to full fill."""
        if not isinstance(event, OrderPartiallyFilled):
            return
        _log.info(
            "OrderPartiallyFilled order_id=%s filled=%d remaining=%d avg=%s",
            event.order_id,
            event.filled_quantity,
            event.remaining_quantity,
            event.average_fill_price,
        )
