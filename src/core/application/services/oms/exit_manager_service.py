"""ExitManagerService — places and manages exit orders.

Responsibilities:
  1. Place stop-loss order immediately after position opens (SL-Market)
  2. Place target order (LIMIT) for T1 or T2
  3. Handle stop-loss fill → close position (LOSS or BREAKEVEN)
  4. Handle target fill → close position (WIN) + move stop to breakeven
  5. Trailing stop update on price ticks
  6. Time exit: close position if market close approaching

Called by:
  - PositionManagerService (after position open)
  - ExecutionMonitorService (on SL/target fill)
  - Background task (time exit, trailing stop tick)
"""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.entities.order import Order
from core.domain.entities.position import Position
from core.domain.enums.order_type import OrderType
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.product_type import ProductType
from core.domain.enums.signal_type import SignalType
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.events.order_events import (
    StopLossPlaced,
    StopLossTriggered,
    TargetPlaced,
    TargetTriggered,
)
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_order_repository import IOrderRepository
from core.domain.interfaces.i_position_repository import IPositionRepository
from core.domain.value_objects.price import Price

_log = logging.getLogger(__name__)

_MARKET_CLOSE_BUFFER_SECONDS = 900  # 15 min before close → time exit
_MARKET_SESSION_SECONDS = 23400     # 6.5 hours


class ExitManagerService:
    """Orchestrates stop-loss, target, trailing-stop, and time exits."""

    def __init__(
        self,
        order_repository: IOrderRepository,
        position_repository: IPositionRepository,
        order_router_service: object,   # OrderRouterService (duck-typed to break circular imports)
        position_manager_service: object,  # PositionManagerService (duck-typed)
        event_bus: IEventBus,
    ) -> None:
        self._order_repo = order_repository
        self._position_repo = position_repository
        self._router = order_router_service
        self._position_mgr = position_manager_service
        self._bus = event_bus

    async def place_stop_loss_order(
        self,
        position: Position,
        correlation_id: str = "",
    ) -> Order | None:
        """Place a SL-Market stop-loss order for the position.

        Returns the stop-loss Order on success, None if position has no SL price.
        """
        if position.stop_loss_price is None:
            _log.warning(
                "Position %s has no stop_loss_price — skip SL placement",
                position.position_id,
            )
            return None

        sl_transaction = (
            TransactionType.SELL
            if position.direction == SignalType.LONG
            else TransactionType.BUY
        )

        sl_order = Order.create(
            signal_id=position.signal_id or _NULL_UUID,
            symbol=position.symbol,
            quantity=position.quantity,
            limit_price=None,
            instrument_token=position.instrument_token,
            order_type=OrderType.SL_MARKET,
            transaction_type=sl_transaction,
            product=ProductType.MIS,
            lots=position.lots,
            trigger_price=position.stop_loss_price,
            validity=Validity.DAY,
            trading_mode=position.trading_mode,
            parent_position_id=position.position_id,
        )

        try:
            routed_order = await self._router.route(sl_order, correlation_id)
        except Exception:
            _log.exception(
                "Failed to place SL order for position %s", position.position_id
            )
            return None

        await self._position_mgr.assign_stop_order(position, routed_order.order_id)

        await self._publish_safe(
            StopLossPlaced(
                position_id=position.position_id,
                stop_order_id=routed_order.order_id,
                signal_id=position.signal_id or _NULL_UUID,
                trigger_price=position.stop_loss_price.value,
            )
        )

        _log.info(
            "SL order %s placed for position %s @ trigger=%s",
            routed_order.order_id,
            position.position_id,
            position.stop_loss_price,
        )
        return routed_order

    async def place_target_order(
        self,
        position: Position,
        target_level: int = 1,
        correlation_id: str = "",
    ) -> Order | None:
        """Place a LIMIT target order for the position.

        Returns the target Order on success, None if no target price.
        """
        target_price = (
            position.target_1_price
            if target_level == 1
            else position.target_2_price
        )
        if target_price is None:
            _log.warning(
                "Position %s has no target_%d_price — skip target placement",
                position.position_id,
                target_level,
            )
            return None

        t_transaction = (
            TransactionType.SELL
            if position.direction == SignalType.LONG
            else TransactionType.BUY
        )

        target_order = Order.create(
            signal_id=position.signal_id or _NULL_UUID,
            symbol=position.symbol,
            quantity=position.quantity,
            limit_price=target_price,
            instrument_token=position.instrument_token,
            order_type=OrderType.LIMIT,
            transaction_type=t_transaction,
            product=ProductType.MIS,
            lots=position.lots,
            validity=Validity.DAY,
            trading_mode=position.trading_mode,
            parent_position_id=position.position_id,
        )

        try:
            routed_order = await self._router.route(target_order, correlation_id)
        except Exception:
            _log.exception(
                "Failed to place target order for position %s", position.position_id
            )
            return None

        await self._position_mgr.assign_target_order(position, routed_order.order_id)

        await self._publish_safe(
            TargetPlaced(
                position_id=position.position_id,
                target_order_id=routed_order.order_id,
                signal_id=position.signal_id or _NULL_UUID,
                limit_price=target_price.value,
                target_level=target_level,
            )
        )

        _log.info(
            "Target order %s placed for position %s @ limit=%s (T%d)",
            routed_order.order_id,
            position.position_id,
            target_price,
            target_level,
        )
        return routed_order

    async def handle_stop_loss_fill(
        self,
        position: Position,
        fill_price: Price,
        stop_order_id: object,
    ) -> Position:
        """Stop-loss order filled → close position as LOSS (or BREAKEVEN)."""
        if position.stop_loss_price is not None and fill_price == position.entry_price:
            outcome = PositionOutcome.BREAKEVEN
        else:
            outcome = PositionOutcome.LOSS

        await self._publish_safe(
            StopLossTriggered(
                position_id=position.position_id,
                stop_order_id=stop_order_id,
                signal_id=position.signal_id or _NULL_UUID,
                stop_price=(
                    position.stop_loss_price.value if position.stop_loss_price else Decimal("0")
                ),
                fill_price=fill_price.value,
            )
        )

        updated = await self._position_mgr.close_position(position, fill_price, outcome)

        # Cancel pending target order — exactly one of {SL, target} must be active
        if updated.target_order_id:
            await self._cancel_sibling_order(
                updated.target_order_id, "sl_triggered_cancel_target"
            )

        _log.info(
            "SL triggered for position %s: fill=%s outcome=%s",
            position.position_id,
            fill_price,
            outcome.value,
        )
        return updated

    async def handle_target_fill(
        self,
        position: Position,
        fill_price: Price,
        target_order_id: object,
        target_level: int = 1,
    ) -> Position:
        """Target order filled → close position as WIN + move stop to breakeven."""
        await self._publish_safe(
            TargetTriggered(
                position_id=position.position_id,
                target_order_id=target_order_id,
                signal_id=position.signal_id or _NULL_UUID,
                target_price=position.target_1_price.value
                if position.target_1_price
                else Decimal("0"),
                fill_price=fill_price.value,
                target_level=target_level,
            )
        )

        updated = await self._position_mgr.close_position(
            position, fill_price, PositionOutcome.WIN
        )

        # Cancel pending stop-loss order — exactly one of {SL, target} must be active
        if updated.stop_order_id:
            await self._cancel_sibling_order(
                updated.stop_order_id, "target_triggered_cancel_sl"
            )

        _log.info(
            "Target T%d triggered for position %s: fill=%s",
            target_level,
            position.position_id,
            fill_price,
        )
        return updated

    async def handle_time_exit(self, position: Position, exit_price: Price) -> Position:
        """Time exit: close position at current market price."""
        updated = await self._position_mgr.close_position(
            position, exit_price, PositionOutcome.TIME_EXIT
        )
        _log.info(
            "Time exit for position %s @ %s", position.position_id, exit_price
        )
        return updated

    async def apply_trailing_stop(
        self,
        position: Position,
        new_price: Price,
        trail_pct: Decimal,
    ) -> bool:
        """Move stop-loss up (LONG) or down (SHORT) using trail_pct.

        Returns True if stop was moved. Caller must cancel + re-place SL order.
        """
        if trail_pct <= 0:
            return False

        if position.direction == SignalType.LONG:
            new_stop = new_price.value * (1 - trail_pct)
            if (
                position.stop_loss_price is None
                or Decimal(str(new_stop)) > position.stop_loss_price.value
            ):
                position.stop_loss_price = Price(Decimal(str(new_stop)))
                await self._position_repo.save(position)
                return True
        else:  # SHORT
            new_stop = new_price.value * (1 + trail_pct)
            if (
                position.stop_loss_price is None
                or Decimal(str(new_stop)) < position.stop_loss_price.value
            ):
                position.stop_loss_price = Price(Decimal(str(new_stop)))
                await self._position_repo.save(position)
                return True

        return False

    async def check_time_exit_needed(
        self, position: Position, session_start: datetime
    ) -> bool:
        """Return True if position should be time-exited (approaching market close)."""
        elapsed = (datetime.now(UTC) - session_start).total_seconds()
        return elapsed >= (_MARKET_SESSION_SECONDS - _MARKET_CLOSE_BUFFER_SECONDS)

    async def _cancel_sibling_order(self, order_id: object, reason: str) -> None:
        """Cancel the other exit order when one fills (SL↔target mutual exclusion)."""
        try:
            order = await self._order_repo.get_by_id(order_id)
            if order is None or order.is_terminal:
                return
            await self._router.cancel(order, reason)
            _log.info("Sibling order %s cancelled (reason=%s)", order_id, reason)
        except Exception:
            _log.warning(
                "Failed to cancel sibling order %s (reason=%s)", order_id, reason
            )

    async def _publish_safe(self, event: object) -> None:
        try:
            await self._bus.publish(event)
        except Exception:
            _log.warning("Event publish failed for %s", type(event).__name__)


_NULL_UUID = _uuid.UUID("00000000-0000-0000-0000-000000000000")
