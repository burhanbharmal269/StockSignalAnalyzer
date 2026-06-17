"""PositionManagerService — opens, updates, and closes positions.

Responsibilities:
  1. Open a position when the primary order fills (OrderFilled event handler)
  2. Update MTM P&L on price ticks
  3. Close a position (stop-loss or target fill)
  4. Persist position after every mutation
  5. Publish position lifecycle events

Position sizing comes from Risk Engine (via OrderRequest). OMS never calculates size.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from decimal import Decimal

from core.domain.entities.order import Order
from core.domain.entities.position import Position
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.signal_type import SignalType
from core.domain.events.order_events import PositionClosed, PositionOpened
from core.domain.exceptions.order import PositionPersistenceError
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_position_repository import IPositionRepository
from core.domain.value_objects.price import Price

_log = logging.getLogger(__name__)


class PositionManagerService:
    """Manages position lifecycle from open through close."""

    def __init__(
        self,
        position_repository: IPositionRepository,
        event_bus: IEventBus,
    ) -> None:
        self._repo = position_repository
        self._bus = event_bus

    async def open_position(self, order: Order, underlying: str = "") -> Position:
        """Create and persist a position when the primary order fills.

        Called by ExitManagerService (or event handler) after OrderFilled.
        Raises PositionPersistenceError if DB save fails.
        """
        if order.average_fill_price is None:
            raise ValueError(
                f"Cannot open position: order {order.order_id} has no fill price"
            )

        direction = (
            SignalType.LONG
            if order.transaction_type.value == "BUY"
            else SignalType.SHORT
        )

        position = Position.open(
            symbol=order.symbol,
            direction=direction,
            quantity=order.filled_quantity or order.quantity,
            entry_price=order.average_fill_price,
            signal_id=order.signal_id,
            order_id=order.order_id,
            instrument_token=order.instrument_token,
            lots=order.lots,
            trading_mode=order.trading_mode,
        )

        await self._save(position)

        await self._publish_safe(
            PositionOpened(
                position_id=position.position_id,
                order_id=order.order_id,
                signal_id=order.signal_id,
                instrument_token=order.instrument_token,
                underlying=underlying or order.tradingsymbol,
                direction=direction.value,
                lots=order.lots,
                quantity=position.quantity,
                entry_price=order.average_fill_price.value,
                stop_loss_price=position.stop_loss_price.value
                if position.stop_loss_price
                else Decimal("0"),
                target_1_price=position.target_1_price.value
                if position.target_1_price
                else Decimal("0"),
                trading_mode=position.trading_mode.value,
                regime_at_open=position.regime_at_open,
            )
        )

        _log.info(
            "Position opened: %s %s %s qty=%d @ %s",
            position.position_id,
            direction.value,
            position.symbol,
            position.quantity,
            position.entry_price,
        )
        return position

    async def update_mark_to_market(
        self, position_id: object, new_price: Price
    ) -> Position | None:
        """Update current price and MTM P&L for a position.

        Returns updated position, or None if not found.
        Does not persist — MTM is high-frequency; callers batch persistence.
        """
        from uuid import UUID
        pid = position_id if isinstance(position_id, UUID) else UUID(str(position_id))
        position = await self._repo.get_by_id(pid)
        if position is None:
            return None
        position.update_price(new_price)
        return position

    async def close_position(
        self,
        position: Position,
        exit_price: Price,
        outcome: PositionOutcome,
        quantity: int | None = None,
    ) -> Position:
        """Close (or partially close) the position and persist.

        If quantity is None, fully closes.
        Raises PositionPersistenceError if DB save fails.
        """
        closed_qty = quantity or position.quantity

        if closed_qty < position.quantity:
            position.partial_close(exit_price, closed_qty)
        else:
            position.close(exit_price, closed_qty, outcome)

        await self._save(position)

        if position.state.value == "CLOSED":
            await self._publish_safe(
                PositionClosed(
                    position_id=position.position_id,
                    signal_id=position.signal_id or _NULL_UUID,
                    direction=position.direction.value,
                    entry_price=position.entry_price.value,
                    exit_price=exit_price.value,
                    lots=position.lots,
                    realized_pnl=position.realized_pnl.value,
                    outcome=outcome.value,
                    trading_mode=position.trading_mode.value,
                )
            )

        _log.info(
            "Position %s closed: outcome=%s realized_pnl=%s",
            position.position_id,
            outcome.value,
            position.realized_pnl,
        )
        return position

    async def assign_stop_order(
        self, position: Position, stop_order_id: object
    ) -> Position:
        """Record stop-loss order ID on position and persist."""
        position.assign_stop_order(stop_order_id)
        await self._save(position)
        return position

    async def assign_target_order(
        self, position: Position, target_order_id: object
    ) -> Position:
        """Record target order ID on position and persist."""
        position.assign_target_order(target_order_id)
        await self._save(position)
        return position

    async def move_stop_to_breakeven(self, position: Position) -> Position:
        """Move stop-loss to entry price after T1 is hit."""
        position.move_stop_to_breakeven()
        await self._save(position)
        _log.info(
            "Position %s: stop moved to breakeven @ %s",
            position.position_id, position.entry_price,
        )
        return position

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _save(self, position: Position) -> None:
        try:
            await self._repo.save(position)
        except Exception as exc:
            raise PositionPersistenceError(
                f"Failed to persist position {position.position_id}: {exc}"
            ) from exc

    async def _publish_safe(self, event: object) -> None:
        try:
            await self._bus.publish(event)
        except Exception:
            _log.warning("Event publish failed for %s", type(event).__name__)


_NULL_UUID = _uuid.UUID("00000000-0000-0000-0000-000000000000")
