"""Unit tests — ExitManagerService.

Coverage:
  - place_stop_loss_order: creates SL_MARKET order, assigns to position, publishes StopLossPlaced
  - place_stop_loss_order: no stop price → returns None
  - place_target_order: creates LIMIT order, assigns to position, publishes TargetPlaced
  - place_target_order: no target price → returns None
  - handle_stop_loss_fill: closes position as LOSS, publishes StopLossTriggered
  - handle_stop_loss_fill: breakeven fill → BREAKEVEN outcome
  - handle_target_fill: closes position as WIN, publishes TargetTriggered
  - handle_time_exit: closes position as TIME_EXIT
  - apply_trailing_stop: moves LONG stop up, SHORT stop down
  - apply_trailing_stop: does not move stop when already tighter
  - broker failure on SL placement → returns None (non-fatal)
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from core.application.services.oms.exit_manager_service import ExitManagerService
from core.domain.entities.position import Position
from core.domain.enums.order_state import OrderState
from core.domain.enums.order_type import OrderType
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.signal_type import SignalType
from core.domain.enums.trading_mode import TradingMode
from core.domain.exceptions.order import BrokerUnavailableError
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(
    direction: SignalType = SignalType.LONG,
    stop_loss_price: Decimal | None = Decimal("180"),
    target_price: Decimal | None = Decimal("230"),
) -> Position:
    return Position.open(
        symbol=Symbol("NIFTY", "NFO"),
        direction=direction,
        quantity=50,
        entry_price=Price(Decimal("200")),
        signal_id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        instrument_token=12345,
        lots=1,
        stop_loss_price=Price(stop_loss_price) if stop_loss_price else None,
        target_1_price=Price(target_price) if target_price else None,
        trading_mode=TradingMode.LIVE,
    )


def _make_routed_order():
    from core.domain.entities.order import Order
    from core.domain.enums.order_type import OrderType
    from core.domain.enums.product_type import ProductType
    from core.domain.enums.transaction_type import TransactionType
    from core.domain.enums.validity import Validity

    order = Order(
        order_id=uuid.uuid4(),
        signal_id=uuid.uuid4(),
        symbol=Symbol("NIFTY", "NFO"),
        quantity=50,
        limit_price=None,
        order_type=OrderType.SL_MARKET,
        transaction_type=TransactionType.SELL,
        product=ProductType.MIS,
        lots=1,
        validity=Validity.DAY,
        trading_mode=TradingMode.LIVE,
        state=OrderState.SUBMITTED,
        broker_order_id="BROKER-SL-001",
    )
    return order


@pytest.fixture
def mock_order_repo():
    r = AsyncMock()
    r.save = AsyncMock()
    return r


@pytest.fixture
def mock_position_repo():
    r = AsyncMock()
    r.save = AsyncMock()
    return r


@pytest.fixture
def mock_router_service():
    svc = AsyncMock()

    async def _smart_route(order, correlation_id=""):
        # Return an order that mirrors the input order's type
        from core.domain.entities.order import Order
        routed = Order(
            order_id=uuid.uuid4(),
            signal_id=order.signal_id,
            symbol=order.symbol,
            quantity=order.quantity,
            limit_price=order.limit_price,
            order_type=order.order_type,
            transaction_type=order.transaction_type,
            product=order.product,
            lots=order.lots,
            validity=order.validity,
            trading_mode=order.trading_mode,
            state=OrderState.SUBMITTED,
            broker_order_id=f"BROKER-{uuid.uuid4().hex[:6].upper()}",
        )
        return routed

    svc.route = AsyncMock(side_effect=_smart_route)
    return svc


@pytest.fixture
def mock_position_manager():
    mgr = AsyncMock()

    async def _assign_stop(pos, stop_id):
        pos.assign_stop_order(stop_id)
        return pos

    async def _assign_target(pos, target_id):
        pos.assign_target_order(target_id)
        return pos

    async def _close(pos, price, outcome, quantity=None):
        pos.close(price, quantity or pos.quantity, outcome)
        return pos

    mgr.assign_stop_order = AsyncMock(side_effect=_assign_stop)
    mgr.assign_target_order = AsyncMock(side_effect=_assign_target)
    mgr.close_position = AsyncMock(side_effect=_close)
    return mgr


@pytest.fixture
def mock_bus():
    b = AsyncMock()
    b.publish = AsyncMock()
    return b


@pytest.fixture
def svc(mock_order_repo, mock_position_repo, mock_router_service, mock_position_manager, mock_bus):
    return ExitManagerService(
        order_repository=mock_order_repo,
        position_repository=mock_position_repo,
        order_router_service=mock_router_service,
        position_manager_service=mock_position_manager,
        event_bus=mock_bus,
    )


# ---------------------------------------------------------------------------
# place_stop_loss_order
# ---------------------------------------------------------------------------

class TestPlaceStopLossOrder:
    @pytest.mark.asyncio
    async def test_sl_order_returned(self, svc, mock_router_service):
        position = _make_position()
        result = await svc.place_stop_loss_order(position)
        assert result is not None
        assert result.order_type == OrderType.SL_MARKET

    @pytest.mark.asyncio
    async def test_sl_placed_event_published(self, svc, mock_bus):
        position = _make_position()
        await svc.place_stop_loss_order(position)
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "StopLossPlaced" in published_types

    @pytest.mark.asyncio
    async def test_stop_order_assigned_to_position(self, svc, mock_position_manager):
        position = _make_position()
        await svc.place_stop_loss_order(position)
        mock_position_manager.assign_stop_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_sl_price_returns_none(self, svc):
        position = _make_position(stop_loss_price=None)
        result = await svc.place_stop_loss_order(position)
        assert result is None

    @pytest.mark.asyncio
    async def test_broker_failure_returns_none(self, svc, mock_router_service):
        mock_router_service.route = AsyncMock(side_effect=BrokerUnavailableError("down"))
        position = _make_position()
        result = await svc.place_stop_loss_order(position)
        assert result is None


# ---------------------------------------------------------------------------
# place_target_order
# ---------------------------------------------------------------------------

class TestPlaceTargetOrder:
    @pytest.mark.asyncio
    async def test_target_order_returned(self, svc):
        position = _make_position()
        result = await svc.place_target_order(position, target_level=1)
        assert result is not None
        assert result.order_type == OrderType.LIMIT

    @pytest.mark.asyncio
    async def test_target_placed_event_published(self, svc, mock_bus):
        position = _make_position()
        await svc.place_target_order(position)
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "TargetPlaced" in published_types

    @pytest.mark.asyncio
    async def test_no_target_price_returns_none(self, svc):
        position = _make_position(target_price=None)
        result = await svc.place_target_order(position)
        assert result is None


# ---------------------------------------------------------------------------
# handle_stop_loss_fill
# ---------------------------------------------------------------------------

class TestStopLossFill:
    @pytest.mark.asyncio
    async def test_position_closed_as_loss(self, svc, mock_position_manager):
        position = _make_position()
        stop_id = uuid.uuid4()
        await svc.handle_stop_loss_fill(position, Price(Decimal("178")), stop_id)
        mock_position_manager.close_position.assert_called_once()
        _, kwargs_or_args = mock_position_manager.close_position.call_args
        # Outcome should be LOSS
        call_args = mock_position_manager.close_position.call_args[0]
        assert call_args[2] == PositionOutcome.LOSS

    @pytest.mark.asyncio
    async def test_stop_loss_triggered_event_published(self, svc, mock_bus):
        position = _make_position()
        await svc.handle_stop_loss_fill(position, Price(Decimal("178")), uuid.uuid4())
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "StopLossTriggered" in published_types

    @pytest.mark.asyncio
    async def test_fill_at_entry_is_breakeven(self, svc, mock_position_manager):
        position = _make_position()
        # Manually set stop_loss = entry (breakeven stop)
        position.stop_loss_price = position.entry_price
        await svc.handle_stop_loss_fill(position, position.entry_price, uuid.uuid4())
        call_args = mock_position_manager.close_position.call_args[0]
        assert call_args[2] == PositionOutcome.BREAKEVEN


# ---------------------------------------------------------------------------
# handle_target_fill
# ---------------------------------------------------------------------------

class TestTargetFill:
    @pytest.mark.asyncio
    async def test_position_closed_as_win(self, svc, mock_position_manager):
        position = _make_position()
        await svc.handle_target_fill(position, Price(Decimal("230")), uuid.uuid4())
        call_args = mock_position_manager.close_position.call_args[0]
        assert call_args[2] == PositionOutcome.WIN

    @pytest.mark.asyncio
    async def test_target_triggered_event_published(self, svc, mock_bus):
        position = _make_position()
        await svc.handle_target_fill(position, Price(Decimal("230")), uuid.uuid4())
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "TargetTriggered" in published_types


# ---------------------------------------------------------------------------
# handle_time_exit
# ---------------------------------------------------------------------------

class TestTimeExit:
    @pytest.mark.asyncio
    async def test_time_exit_outcome(self, svc, mock_position_manager):
        position = _make_position()
        await svc.handle_time_exit(position, Price(Decimal("210")))
        call_args = mock_position_manager.close_position.call_args[0]
        assert call_args[2] == PositionOutcome.TIME_EXIT


# ---------------------------------------------------------------------------
# apply_trailing_stop
# ---------------------------------------------------------------------------

class TestTrailingStop:
    @pytest.mark.asyncio
    async def test_long_stop_moves_up(self, svc, mock_position_repo):
        position = _make_position(direction=SignalType.LONG, stop_loss_price=Decimal("180"))
        new_price = Price(Decimal("220"))
        trail_pct = Decimal("0.05")  # 5% trail → new stop = 220 * 0.95 = 209

        moved = await svc.apply_trailing_stop(position, new_price, trail_pct)

        assert moved is True
        assert position.stop_loss_price.value > Decimal("180")

    @pytest.mark.asyncio
    async def test_long_stop_not_moved_when_already_tighter(
        self, svc, mock_position_repo
    ):
        position = _make_position(direction=SignalType.LONG, stop_loss_price=Decimal("215"))
        # new price 220, 5% trail = 209 < 215 → should NOT move
        moved = await svc.apply_trailing_stop(
            position, Price(Decimal("220")), Decimal("0.05")
        )
        assert moved is False

    @pytest.mark.asyncio
    async def test_short_stop_moves_down(self, svc, mock_position_repo):
        position = _make_position(direction=SignalType.SHORT, stop_loss_price=Decimal("220"))
        new_price = Price(Decimal("180"))
        trail_pct = Decimal("0.05")  # 5% trail → new stop = 180 * 1.05 = 189

        moved = await svc.apply_trailing_stop(position, new_price, trail_pct)

        assert moved is True
        assert position.stop_loss_price.value < Decimal("220")

    @pytest.mark.asyncio
    async def test_zero_trail_pct_no_move(self, svc):
        position = _make_position(stop_loss_price=Decimal("180"))
        moved = await svc.apply_trailing_stop(
            position, Price(Decimal("220")), Decimal("0")
        )
        assert moved is False


# ---------------------------------------------------------------------------
# Sibling order cancellation (invariant: exactly one of {SL, target} active)
# ---------------------------------------------------------------------------

class TestSiblingOrderCancellation:
    @pytest.mark.asyncio
    async def test_stop_loss_fill_cancels_pending_target_order(
        self, svc, mock_order_repo, mock_router_service
    ):
        """When SL fills, the pending target order must be cancelled."""
        from core.domain.entities.order import Order
        from core.domain.enums.order_state import OrderState
        from core.domain.enums.product_type import ProductType
        from core.domain.enums.transaction_type import TransactionType
        from core.domain.enums.validity import Validity

        target_order_id = uuid.uuid4()
        target_order = Order(
            order_id=target_order_id,
            signal_id=uuid.uuid4(),
            symbol=Symbol("NIFTY", "NFO"),
            quantity=50,
            limit_price=Price(Decimal("230")),
            order_type=OrderType.LIMIT,
            transaction_type=TransactionType.SELL,
            product=ProductType.MIS,
            lots=1,
            validity=Validity.DAY,
            trading_mode=TradingMode.LIVE,
            state=OrderState.OPEN,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=target_order)

        position = _make_position()
        position.assign_target_order(target_order_id)

        await svc.handle_stop_loss_fill(position, Price(Decimal("178")), uuid.uuid4())

        mock_router_service.cancel.assert_called_once()
        call_args = mock_router_service.cancel.call_args[0]
        assert call_args[0].order_id == target_order_id

    @pytest.mark.asyncio
    async def test_target_fill_cancels_pending_stop_loss_order(
        self, svc, mock_order_repo, mock_router_service
    ):
        """When target fills, the pending SL order must be cancelled."""
        from core.domain.entities.order import Order
        from core.domain.enums.order_state import OrderState
        from core.domain.enums.product_type import ProductType
        from core.domain.enums.transaction_type import TransactionType
        from core.domain.enums.validity import Validity

        sl_order_id = uuid.uuid4()
        sl_order = Order(
            order_id=sl_order_id,
            signal_id=uuid.uuid4(),
            symbol=Symbol("NIFTY", "NFO"),
            quantity=50,
            limit_price=None,
            order_type=OrderType.SL_MARKET,
            transaction_type=TransactionType.SELL,
            product=ProductType.MIS,
            lots=1,
            validity=Validity.DAY,
            trading_mode=TradingMode.LIVE,
            state=OrderState.OPEN,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=sl_order)

        position = _make_position()
        position.assign_stop_order(sl_order_id)

        await svc.handle_target_fill(position, Price(Decimal("230")), uuid.uuid4())

        mock_router_service.cancel.assert_called_once()
        call_args = mock_router_service.cancel.call_args[0]
        assert call_args[0].order_id == sl_order_id

    @pytest.mark.asyncio
    async def test_no_cancel_if_sibling_already_terminal(
        self, svc, mock_order_repo, mock_router_service
    ):
        """No cancel call when sibling order is already in a terminal state."""
        from core.domain.entities.order import Order
        from core.domain.enums.order_state import OrderState
        from core.domain.enums.product_type import ProductType
        from core.domain.enums.transaction_type import TransactionType
        from core.domain.enums.validity import Validity

        target_order_id = uuid.uuid4()
        filled_target = Order(
            order_id=target_order_id,
            signal_id=uuid.uuid4(),
            symbol=Symbol("NIFTY", "NFO"),
            quantity=50,
            limit_price=Price(Decimal("230")),
            order_type=OrderType.LIMIT,
            transaction_type=TransactionType.SELL,
            product=ProductType.MIS,
            lots=1,
            validity=Validity.DAY,
            trading_mode=TradingMode.LIVE,
            state=OrderState.FILLED,  # Already terminal — no cancel needed
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=filled_target)

        position = _make_position()
        position.assign_target_order(target_order_id)

        await svc.handle_stop_loss_fill(position, Price(Decimal("178")), uuid.uuid4())

        mock_router_service.cancel.assert_not_called()
