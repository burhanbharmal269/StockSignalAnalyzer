"""Unit tests — PositionManagerService.

Coverage:
  - open_position: creates Position, persists, publishes PositionOpened
  - open_position: no fill price on order → ValueError
  - close_position: LONG WIN, LONG LOSS, SHORT WIN, BREAKEVEN
  - close_position: publishes PositionClosed on full close
  - partial_close: state PARTIALLY_CLOSED, no PositionClosed event
  - assign_stop_order / assign_target_order: persists and returns
  - move_stop_to_breakeven: sets stop_loss_price to entry
  - PositionPersistenceError on DB failure
  - Event bus failure is non-fatal
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from core.application.services.oms.position_manager_service import PositionManagerService
from core.domain.entities.order import Order
from core.domain.entities.position import Position
from core.domain.enums.order_type import OrderType
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.position_state import PositionState
from core.domain.enums.product_type import ProductType
from core.domain.enums.signal_type import SignalType
from core.domain.enums.trading_mode import TradingMode
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.exceptions.order import PositionPersistenceError
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_filled_order(direction: str = "BUY") -> Order:
    tx = TransactionType.BUY if direction == "BUY" else TransactionType.SELL
    order = Order(
        order_id=uuid.uuid4(),
        signal_id=uuid.uuid4(),
        symbol=Symbol("NIFTY", "NFO"),
        quantity=50,
        limit_price=None,
        instrument_token=12345,
        order_type=OrderType.MARKET,
        transaction_type=tx,
        product=ProductType.MIS,
        lots=1,
        validity=Validity.DAY,
        trading_mode=TradingMode.LIVE,
        broker_order_id="BROKER-001",
        filled_quantity=50,
        average_fill_price=Price(Decimal("200")),
    )
    return order


def _make_open_position(direction: SignalType = SignalType.LONG) -> Position:
    return Position.open(
        symbol=Symbol("NIFTY", "NFO"),
        direction=direction,
        quantity=50,
        entry_price=Price(Decimal("200")),
        signal_id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        instrument_token=12345,
        lots=1,
        stop_loss_price=Price(Decimal("180")),
        target_1_price=Price(Decimal("230")),
        trading_mode=TradingMode.LIVE,
    )


@pytest.fixture
def mock_repo():
    r = AsyncMock()
    r.save = AsyncMock()
    r.get_by_id = AsyncMock()
    return r


@pytest.fixture
def mock_bus():
    b = AsyncMock()
    b.publish = AsyncMock()
    return b


@pytest.fixture
def svc(mock_repo, mock_bus):
    return PositionManagerService(
        position_repository=mock_repo,
        event_bus=mock_bus,
    )


# ---------------------------------------------------------------------------
# open_position
# ---------------------------------------------------------------------------

class TestOpenPosition:
    @pytest.mark.asyncio
    async def test_opens_and_returns_position(self, svc, mock_repo):
        order = _make_filled_order("BUY")
        position = await svc.open_position(order)
        assert position.state == PositionState.OPEN
        assert position.direction == SignalType.LONG

    @pytest.mark.asyncio
    async def test_short_order_creates_short_position(self, svc):
        order = _make_filled_order("SELL")
        position = await svc.open_position(order)
        assert position.direction == SignalType.SHORT

    @pytest.mark.asyncio
    async def test_position_persisted(self, svc, mock_repo):
        order = _make_filled_order()
        await svc.open_position(order)
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_position_opened_event_published(self, svc, mock_bus):
        order = _make_filled_order()
        await svc.open_position(order)
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "PositionOpened" in published_types

    @pytest.mark.asyncio
    async def test_no_fill_price_raises(self, svc):
        order = _make_filled_order()
        order.average_fill_price = None
        with pytest.raises(ValueError):
            await svc.open_position(order)

    @pytest.mark.asyncio
    async def test_db_failure_raises_position_persistence_error(self, svc, mock_repo):
        mock_repo.save = AsyncMock(side_effect=RuntimeError("DB down"))
        order = _make_filled_order()
        with pytest.raises(PositionPersistenceError):
            await svc.open_position(order)


# ---------------------------------------------------------------------------
# close_position
# ---------------------------------------------------------------------------

class TestClosePosition:
    @pytest.mark.asyncio
    async def test_full_close_sets_closed_state(self, svc):
        position = _make_open_position(SignalType.LONG)
        await svc.close_position(position, Price(Decimal("230")), PositionOutcome.WIN)
        assert position.state == PositionState.CLOSED

    @pytest.mark.asyncio
    async def test_full_close_publishes_position_closed(self, svc, mock_bus):
        position = _make_open_position(SignalType.LONG)
        await svc.close_position(position, Price(Decimal("230")), PositionOutcome.WIN)
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "PositionClosed" in published_types

    @pytest.mark.asyncio
    async def test_loss_outcome_recorded(self, svc):
        position = _make_open_position(SignalType.LONG)
        await svc.close_position(position, Price(Decimal("180")), PositionOutcome.LOSS)
        assert position.outcome == PositionOutcome.LOSS

    @pytest.mark.asyncio
    async def test_short_win_outcome(self, svc):
        position = _make_open_position(SignalType.SHORT)
        # SHORT: sell at 200, target at 170 → WIN
        await svc.close_position(position, Price(Decimal("170")), PositionOutcome.WIN)
        assert position.outcome == PositionOutcome.WIN

    @pytest.mark.asyncio
    async def test_time_exit_outcome(self, svc):
        position = _make_open_position()
        await svc.close_position(position, Price(Decimal("205")), PositionOutcome.TIME_EXIT)
        assert position.outcome == PositionOutcome.TIME_EXIT

    @pytest.mark.asyncio
    async def test_position_persisted_on_close(self, svc, mock_repo):
        position = _make_open_position()
        await svc.close_position(position, Price(Decimal("230")), PositionOutcome.WIN)
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_failure_on_close_raises(self, svc, mock_repo):
        mock_repo.save = AsyncMock(side_effect=RuntimeError("DB down"))
        position = _make_open_position()
        with pytest.raises(PositionPersistenceError):
            await svc.close_position(position, Price(Decimal("230")), PositionOutcome.WIN)


# ---------------------------------------------------------------------------
# Partial close
# ---------------------------------------------------------------------------

class TestPartialClose:
    @pytest.mark.asyncio
    async def test_partial_close_state(self, svc):
        position = _make_open_position()
        await svc.close_position(
            position, Price(Decimal("220")), PositionOutcome.WIN, quantity=25
        )
        assert position.state == PositionState.PARTIALLY_CLOSED

    @pytest.mark.asyncio
    async def test_partial_close_no_position_closed_event(self, svc, mock_bus):
        position = _make_open_position()
        await svc.close_position(
            position, Price(Decimal("220")), PositionOutcome.WIN, quantity=25
        )
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "PositionClosed" not in published_types


# ---------------------------------------------------------------------------
# assign_stop_order / assign_target_order
# ---------------------------------------------------------------------------

class TestAssignOrders:
    @pytest.mark.asyncio
    async def test_assign_stop_order(self, svc, mock_repo):
        position = _make_open_position()
        stop_id = uuid.uuid4()
        result = await svc.assign_stop_order(position, stop_id)
        assert result.stop_order_id == stop_id
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_assign_target_order(self, svc, mock_repo):
        position = _make_open_position()
        target_id = uuid.uuid4()
        result = await svc.assign_target_order(position, target_id)
        assert result.target_order_id == target_id
        mock_repo.save.assert_called_once()


# ---------------------------------------------------------------------------
# move_stop_to_breakeven
# ---------------------------------------------------------------------------

class TestBreakeven:
    @pytest.mark.asyncio
    async def test_stop_moves_to_entry_price(self, svc):
        position = _make_open_position()
        original_sl = position.stop_loss_price
        await svc.move_stop_to_breakeven(position)
        assert position.stop_loss_price == position.entry_price
        assert position.stop_loss_price != original_sl

    @pytest.mark.asyncio
    async def test_breakeven_persists(self, svc, mock_repo):
        position = _make_open_position()
        await svc.move_stop_to_breakeven(position)
        mock_repo.save.assert_called_once()


# ---------------------------------------------------------------------------
# Event bus resilience
# ---------------------------------------------------------------------------

class TestEventBusResilience:
    @pytest.mark.asyncio
    async def test_event_bus_failure_does_not_propagate(self, svc, mock_bus):
        mock_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))
        order = _make_filled_order()
        position = await svc.open_position(order)
        assert position.state == PositionState.OPEN
