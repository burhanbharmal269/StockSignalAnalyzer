"""Unit tests — OrderRouterService.

Coverage:
  - Happy path: PENDING → SUBMITTING → SUBMITTED
  - Persistence after each transition
  - OrderValidated event published before routing
  - OrderRouted event published on success
  - BrokerUnavailableError → REJECTED_PRE_SUBMIT (fail-closed)
  - Unexpected exception wrapped as BrokerUnavailableError
  - Cancel: cancels at broker + transitions + publishes OrderCancelled
  - Event bus failure does not propagate
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from core.application.services.oms.order_router_service import OrderRouterService
from core.domain.entities.order import Order
from core.domain.enums.order_state import OrderState
from core.domain.enums.order_type import OrderType
from core.domain.enums.product_type import ProductType
from core.domain.enums.trading_mode import TradingMode
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.exceptions.order import BrokerUnavailableError, OrderPersistenceError
from core.domain.value_objects.symbol import Symbol


def _make_order(state: OrderState = OrderState.PENDING) -> Order:
    order = Order.create(
        signal_id=uuid.uuid4(),
        symbol=Symbol("NIFTY", "NFO"),
        quantity=50,
        limit_price=None,
        instrument_token=12345,
        order_type=OrderType.MARKET,
        transaction_type=TransactionType.BUY,
        product=ProductType.MIS,
        lots=1,
        validity=Validity.DAY,
        trading_mode=TradingMode.LIVE,
    )
    return order


@pytest.fixture
def mock_router():
    r = AsyncMock()
    r.route = AsyncMock(return_value="BROKER-001")
    r.cancel = AsyncMock()
    r.__class__.__name__ = "MockBrokerRouter"
    return r


@pytest.fixture
def mock_repo():
    r = AsyncMock()
    r.save = AsyncMock()
    return r


@pytest.fixture
def mock_bus():
    b = AsyncMock()
    b.publish = AsyncMock()
    return b


@pytest.fixture
def svc(mock_router, mock_repo, mock_bus):
    return OrderRouterService(
        order_router=mock_router,
        order_repository=mock_repo,
        event_bus=mock_bus,
    )


# ---------------------------------------------------------------------------
# Happy path routing
# ---------------------------------------------------------------------------

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_order_transitions_to_submitted(self, svc, mock_router):
        order = _make_order()
        result = await svc.route(order)
        assert result.state == OrderState.SUBMITTED

    @pytest.mark.asyncio
    async def test_broker_order_id_set_on_order(self, svc):
        order = _make_order()
        result = await svc.route(order)
        assert result.broker_order_id == "BROKER-001"

    @pytest.mark.asyncio
    async def test_order_saved_twice(self, svc, mock_repo):
        order = _make_order()
        await svc.route(order)
        assert mock_repo.save.call_count == 2

    @pytest.mark.asyncio
    async def test_order_validated_event_published(self, svc, mock_bus):
        order = _make_order()
        await svc.route(order)
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "OrderValidated" in published_types

    @pytest.mark.asyncio
    async def test_order_routed_event_published(self, svc, mock_bus):
        order = _make_order()
        await svc.route(order)
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "OrderRouted" in published_types

    @pytest.mark.asyncio
    async def test_validated_before_routed(self, svc, mock_bus):
        order = _make_order()
        await svc.route(order)
        names = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert names.index("OrderValidated") < names.index("OrderRouted")

    @pytest.mark.asyncio
    async def test_persistence_before_broker_call(self, svc, mock_repo, mock_router):
        call_order = []
        mock_repo.save = AsyncMock(side_effect=lambda o: call_order.append("save"))
        mock_router.route = AsyncMock(side_effect=lambda o: call_order.append("broker") or "B-001")

        order = _make_order()
        await svc.route(order)
        assert call_order[0] == "save"  # First save (SUBMITTING) before broker call


# ---------------------------------------------------------------------------
# Broker unavailable — fail-closed
# ---------------------------------------------------------------------------

class TestBrokerUnavailable:
    @pytest.mark.asyncio
    async def test_broker_error_raises_broker_unavailable(self, svc, mock_router):
        mock_router.route = AsyncMock(side_effect=BrokerUnavailableError("timeout"))
        order = _make_order()
        with pytest.raises(BrokerUnavailableError):
            await svc.route(order)

    @pytest.mark.asyncio
    async def test_broker_error_transitions_to_rejected_pre_submit(self, svc, mock_router):
        mock_router.route = AsyncMock(side_effect=BrokerUnavailableError("timeout"))
        order = _make_order()
        try:
            await svc.route(order)
        except BrokerUnavailableError:
            pass
        assert order.state == OrderState.REJECTED_PRE_SUBMIT

    @pytest.mark.asyncio
    async def test_broker_error_persists_rejected_state(self, svc, mock_router, mock_repo):
        mock_router.route = AsyncMock(side_effect=BrokerUnavailableError("timeout"))
        order = _make_order()
        try:
            await svc.route(order)
        except BrokerUnavailableError:
            pass
        # Two saves: SUBMITTING then REJECTED_PRE_SUBMIT
        assert mock_repo.save.call_count == 2
        saved_states = [c[0][0].state for c in mock_repo.save.call_args_list]
        assert OrderState.REJECTED_PRE_SUBMIT in saved_states

    @pytest.mark.asyncio
    async def test_broker_error_publishes_order_rejected(self, svc, mock_router, mock_bus):
        mock_router.route = AsyncMock(side_effect=BrokerUnavailableError("timeout"))
        order = _make_order()
        try:
            await svc.route(order)
        except BrokerUnavailableError:
            pass
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "OrderRejected" in published_types

    @pytest.mark.asyncio
    async def test_unexpected_exception_wrapped_as_broker_unavailable(
        self, svc, mock_router
    ):
        mock_router.route = AsyncMock(side_effect=RuntimeError("network blip"))
        order = _make_order()
        with pytest.raises(BrokerUnavailableError):
            await svc.route(order)


# ---------------------------------------------------------------------------
# Persistence failure
# ---------------------------------------------------------------------------

class TestPersistenceFailure:
    @pytest.mark.asyncio
    async def test_db_failure_raises_order_persistence_error(self, svc, mock_repo):
        mock_repo.save = AsyncMock(side_effect=RuntimeError("DB down"))
        order = _make_order()
        with pytest.raises(OrderPersistenceError):
            await svc.route(order)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_transitions_to_cancelled(self, svc, mock_router):
        order = _make_order()
        # Route to SUBMITTED then move to OPEN before cancel
        await svc.route(order)
        order.open_at_exchange()
        result = await svc.cancel(order, reason="signal_expired")
        assert result.state == OrderState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_calls_broker(self, svc, mock_router):
        order = _make_order()
        await svc.route(order)
        order.open_at_exchange()
        await svc.cancel(order, "reason")
        mock_router.cancel.assert_called_once_with(order)

    @pytest.mark.asyncio
    async def test_cancel_publishes_order_cancelled(self, svc, mock_bus):
        order = _make_order()
        await svc.route(order)
        order.open_at_exchange()
        mock_bus.publish.reset_mock()
        await svc.cancel(order, "reason")
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "OrderCancelled" in published_types

    @pytest.mark.asyncio
    async def test_cancel_broker_failure_still_marks_cancelled(
        self, svc, mock_router, mock_repo
    ):
        mock_router.cancel = AsyncMock(side_effect=RuntimeError("broker down"))
        order = _make_order()
        await svc.route(order)
        order.open_at_exchange()
        result = await svc.cancel(order, "reason")
        assert result.state == OrderState.CANCELLED


# ---------------------------------------------------------------------------
# Event bus resilience
# ---------------------------------------------------------------------------

class TestEventBusResilience:
    @pytest.mark.asyncio
    async def test_event_bus_failure_does_not_propagate(self, svc, mock_bus):
        mock_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))
        order = _make_order()
        result = await svc.route(order)
        assert result.state == OrderState.SUBMITTED
