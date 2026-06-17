"""Unit tests — PaperOrderRouter.

Covers:
  - route(): places order with paper broker and returns broker_order_id
  - route(): lazy session init on first call
  - route(): reuses existing active session on second call
  - cancel(): calls broker cancel with broker_order_id
  - cancel(): noop when broker_order_id is None/empty
  - get_order_status(): returns ExecutionReport for known order
  - get_order_status(): returns None for unknown broker_order_id
  - get_order_status(): returns None when broker raises
  - _get_session(): creates new session when current is inactive
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.entities.broker_session import BrokerSession
from core.domain.entities.order import Order
from core.domain.enums.order_state import OrderState
from core.domain.enums.order_type import OrderType
from core.domain.enums.product_type import ProductType
from core.domain.enums.trading_mode import TradingMode
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.value_objects.broker_dtos import BrokerOrder
from core.domain.value_objects.execution_report import ExecutionReport
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.broker.paper_order_router import PaperOrderRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(active: bool = True) -> BrokerSession:
    s = BrokerSession.create(
        broker_name="paper",
        api_key="paper",
        encrypted_access_token="paper",
        expires_at=datetime(2099, 12, 31, tzinfo=UTC),
    )
    if not active:
        s.deactivate()
    return s


def _make_order(broker_order_id: str | None = None) -> Order:
    return Order(
        order_id=uuid.uuid4(),
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
        trading_mode=TradingMode.PAPER,
        broker_order_id=broker_order_id,
        state=OrderState.PENDING,
        submitted_at=None,
    )


def _make_broker_order(broker_order_id: str = "PAPER-001") -> MagicMock:
    b = MagicMock(spec=BrokerOrder)
    b.broker_order_id = broker_order_id
    b.status = "COMPLETE"
    b.filled_quantity = 50
    b.average_price = Decimal("22000")
    b.exchange_timestamp = datetime.now(UTC)
    b.quantity = 50
    b.order_type = "MARKET"
    b.transaction_type = "BUY"
    b.product = "MIS"
    b.symbol = "NIFTY"
    b.exchange = "NFO"
    b.tag = ""
    b.limit_price = None
    b.trigger_price = None
    return b


def _make_broker_stub(
    broker_order_id: str = "PAPER-001",
    login_raises: Exception | None = None,
    place_raises: Exception | None = None,
    cancel_raises: Exception | None = None,
    get_order_returns: MagicMock | None = None,
    get_order_raises: Exception | None = None,
) -> MagicMock:
    broker = MagicMock()
    session = _make_session()

    if login_raises:
        broker.login = AsyncMock(side_effect=login_raises)
    else:
        broker.login = AsyncMock(return_value=session)

    if place_raises:
        broker.place_order = AsyncMock(side_effect=place_raises)
    else:
        broker.place_order = AsyncMock(return_value=broker_order_id)

    if cancel_raises:
        broker.cancel_order = AsyncMock(side_effect=cancel_raises)
    else:
        broker.cancel_order = AsyncMock()

    if get_order_raises:
        broker.get_order = AsyncMock(side_effect=get_order_raises)
    else:
        broker.get_order = AsyncMock(return_value=get_order_returns)

    return broker


# ---------------------------------------------------------------------------
# route()
# ---------------------------------------------------------------------------


class TestPaperOrderRouterRoute:
    async def test_route_returns_broker_order_id(self) -> None:
        broker = _make_broker_stub(broker_order_id="PAPER-42")
        router = PaperOrderRouter(broker=broker)
        order = _make_order()
        result = await router.route(order)
        assert result == "PAPER-42"

    async def test_route_calls_place_order_once(self) -> None:
        broker = _make_broker_stub()
        router = PaperOrderRouter(broker=broker)
        await router.route(_make_order())
        broker.place_order.assert_awaited_once()

    async def test_route_initialises_session_on_first_call(self) -> None:
        broker = _make_broker_stub()
        router = PaperOrderRouter(broker=broker)
        assert router._session is None
        await router.route(_make_order())
        broker.login.assert_awaited_once()
        assert router._session is not None

    async def test_route_reuses_session_on_second_call(self) -> None:
        broker = _make_broker_stub()
        router = PaperOrderRouter(broker=broker)
        await router.route(_make_order())
        await router.route(_make_order())
        broker.login.assert_awaited_once()

    async def test_route_reinitialises_inactive_session(self) -> None:
        broker = _make_broker_stub()
        router = PaperOrderRouter(broker=broker)
        # Manually plant an inactive session
        inactive = _make_session(active=False)
        router._session = inactive
        await router.route(_make_order())
        broker.login.assert_awaited_once()

    async def test_route_propagates_broker_error(self) -> None:
        broker = _make_broker_stub(place_raises=RuntimeError("broker error"))
        router = PaperOrderRouter(broker=broker)
        with pytest.raises(RuntimeError, match="broker error"):
            await router.route(_make_order())


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------


class TestPaperOrderRouterCancel:
    async def test_cancel_calls_broker_cancel(self) -> None:
        broker = _make_broker_stub()
        router = PaperOrderRouter(broker=broker)
        order = _make_order(broker_order_id="PAPER-99")
        await router.cancel(order)
        broker.cancel_order.assert_awaited_once()
        call_args = broker.cancel_order.call_args
        assert "PAPER-99" in str(call_args)

    async def test_cancel_noop_when_no_broker_order_id(self) -> None:
        broker = _make_broker_stub()
        router = PaperOrderRouter(broker=broker)
        order = _make_order(broker_order_id=None)
        await router.cancel(order)
        broker.cancel_order.assert_not_awaited()

    async def test_cancel_swallows_broker_error(self) -> None:
        broker = _make_broker_stub(cancel_raises=RuntimeError("cancel error"))
        router = PaperOrderRouter(broker=broker)
        order = _make_order(broker_order_id="PAPER-99")
        # must not raise
        await router.cancel(order)


# ---------------------------------------------------------------------------
# get_order_status()
# ---------------------------------------------------------------------------


class TestPaperOrderRouterGetOrderStatus:
    async def test_returns_none_for_unknown_broker_order(self) -> None:
        broker = _make_broker_stub(get_order_returns=None)
        router = PaperOrderRouter(broker=broker)
        result = await router.get_order_status("PAPER-UNKNOWN")
        assert result is None

    async def test_returns_none_when_broker_raises(self) -> None:
        broker = _make_broker_stub(get_order_raises=RuntimeError("broker error"))
        router = PaperOrderRouter(broker=broker)
        result = await router.get_order_status("PAPER-XXX")
        assert result is None

    async def test_returns_execution_report_for_known_order(self) -> None:
        broker_order = _make_broker_order("PAPER-001")
        broker = _make_broker_stub(get_order_returns=broker_order)
        router = PaperOrderRouter(broker=broker)

        with patch(
            "core.application.services.broker.broker_execution_monitor_service"
            ".BrokerExecutionMonitorService._to_execution_report",
            return_value=MagicMock(spec=ExecutionReport),
        ):
            result = await router.get_order_status("PAPER-001")

        assert result is not None
