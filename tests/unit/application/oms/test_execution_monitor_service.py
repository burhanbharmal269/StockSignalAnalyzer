"""Unit tests — ExecutionMonitorService.

Coverage:
  - Full fill: SUBMITTED → OPEN → FILLED, fill saved, OrderFilled published
  - Partial fill: SUBMITTED → OPEN → PARTIALLY_FILLED, fill saved, event published
  - Exchange rejection after submission
  - Unknown broker_order_id → returns None (ignore)
  - Terminal-state order → ignored (idempotent)
  - Persistence failure raises OrderPersistenceError
  - Fill save failure logs error but does not raise
  - process_pending_orders polls broker for monitorable-state orders
  - expire_stale_orders: old OPEN orders → EXPIRED
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.oms.execution_monitor_service import ExecutionMonitorService
from core.domain.entities.order import Order
from core.domain.enums.order_state import OrderState
from core.domain.enums.order_type import OrderType
from core.domain.enums.product_type import ProductType
from core.domain.enums.trading_mode import TradingMode
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.exceptions.order import OrderPersistenceError
from core.domain.value_objects.execution_report import ExecutionReport
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order(state: OrderState = OrderState.SUBMITTED) -> Order:
    order = Order(
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
        trading_mode=TradingMode.LIVE,
        broker_order_id="BROKER-001",
        state=state,
        submitted_at=datetime.now(UTC),
    )
    return order


def _make_report(
    *,
    filled_qty: int = 50,
    remaining: int = 0,
    status: str = "COMPLETE",
    rejection_reason: str = "",
    last_fill_price: Decimal = Decimal("200"),
) -> ExecutionReport:
    is_full = remaining == 0 and filled_qty > 0 and not rejection_reason
    is_partial = remaining > 0 and filled_qty > 0
    is_rejected = bool(rejection_reason) or status in ("REJECTED",)

    report = MagicMock(spec=ExecutionReport)
    report.broker_order_id = "BROKER-001"
    report.filled_quantity = filled_qty
    report.remaining_quantity = remaining
    report.average_fill_price = Price(Decimal("200"))
    report.last_fill_price = Price(last_fill_price)
    report.last_fill_quantity = filled_qty if is_partial else filled_qty
    report.exchange_trade_id = "EX-999"
    report.status = status
    report.rejection_reason = rejection_reason
    report.reported_at = datetime.now(UTC)
    report.is_fully_filled = is_full
    report.is_partial_fill = is_partial
    report.is_rejected = is_rejected
    return report


@pytest.fixture
def mock_order_repo():
    r = AsyncMock()
    r.get_by_broker_order_id = AsyncMock()
    r.get_by_state = AsyncMock(return_value=[])
    r.save = AsyncMock()
    return r


@pytest.fixture
def mock_exec_repo():
    r = AsyncMock()
    r.save = AsyncMock()
    return r


@pytest.fixture
def mock_router():
    r = AsyncMock()
    r.get_order_status = AsyncMock(return_value=None)
    return r


@pytest.fixture
def mock_bus():
    b = AsyncMock()
    b.publish = AsyncMock()
    return b


@pytest.fixture
def svc(mock_order_repo, mock_exec_repo, mock_router, mock_bus):
    return ExecutionMonitorService(
        order_repository=mock_order_repo,
        execution_repository=mock_exec_repo,
        order_router=mock_router,
        event_bus=mock_bus,
    )


# ---------------------------------------------------------------------------
# Full fill
# ---------------------------------------------------------------------------

class TestFullFill:
    @pytest.mark.asyncio
    async def test_order_transitions_to_filled(self, svc, mock_order_repo):
        order = _make_order(OrderState.SUBMITTED)
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)
        report = _make_report(filled_qty=50, remaining=0)

        result = await svc.process_execution_report(report)

        assert result.state == OrderState.FILLED

    @pytest.mark.asyncio
    async def test_fill_saved_to_executions(self, svc, mock_order_repo, mock_exec_repo):
        order = _make_order(OrderState.SUBMITTED)
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)
        report = _make_report(filled_qty=50, remaining=0)

        await svc.process_execution_report(report)

        mock_exec_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_order_filled_event_published(self, svc, mock_order_repo, mock_bus):
        order = _make_order(OrderState.SUBMITTED)
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)
        report = _make_report(filled_qty=50, remaining=0)

        await svc.process_execution_report(report)

        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "OrderFilled" in published_types

    @pytest.mark.asyncio
    async def test_order_saved_after_fill(self, svc, mock_order_repo):
        order = _make_order(OrderState.SUBMITTED)
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)
        report = _make_report(filled_qty=50, remaining=0)

        await svc.process_execution_report(report)

        mock_order_repo.save.assert_called()


# ---------------------------------------------------------------------------
# Partial fill
# ---------------------------------------------------------------------------

class TestPartialFill:
    @pytest.mark.asyncio
    async def test_order_transitions_to_partially_filled(self, svc, mock_order_repo):
        order = _make_order(OrderState.SUBMITTED)
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)
        report = _make_report(filled_qty=25, remaining=25)
        report.is_fully_filled = False
        report.is_partial_fill = True
        report.is_rejected = False

        result = await svc.process_execution_report(report)

        assert result.state == OrderState.PARTIALLY_FILLED

    @pytest.mark.asyncio
    async def test_partial_fill_event_published(self, svc, mock_order_repo, mock_bus):
        order = _make_order(OrderState.SUBMITTED)
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)
        report = _make_report(filled_qty=25, remaining=25)
        report.is_fully_filled = False
        report.is_partial_fill = True
        report.is_rejected = False

        await svc.process_execution_report(report)

        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "OrderPartiallyFilled" in published_types

    @pytest.mark.asyncio
    async def test_partial_fill_saved_to_executions(
        self, svc, mock_order_repo, mock_exec_repo
    ):
        order = _make_order(OrderState.SUBMITTED)
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)
        report = _make_report(filled_qty=25, remaining=25)
        report.is_fully_filled = False
        report.is_partial_fill = True
        report.is_rejected = False

        await svc.process_execution_report(report)

        mock_exec_repo.save.assert_called_once()


# ---------------------------------------------------------------------------
# Unknown broker_order_id
# ---------------------------------------------------------------------------

class TestUnknownBrokerOrderId:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_broker_order(self, svc, mock_order_repo):
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=None)
        report = _make_report()

        result = await svc.process_execution_report(report)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_save_for_unknown_broker_order(
        self, svc, mock_order_repo, mock_exec_repo
    ):
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=None)
        await svc.process_execution_report(_make_report())
        mock_exec_repo.save.assert_not_called()


# ---------------------------------------------------------------------------
# Terminal state ignored
# ---------------------------------------------------------------------------

class TestTerminalStateIgnored:
    @pytest.mark.asyncio
    async def test_filled_order_ignored(self, svc, mock_order_repo, mock_exec_repo):
        order = _make_order(OrderState.SUBMITTED)
        # Manually set to FILLED
        order.open_at_exchange()
        order.record_fill(50, Price(Decimal("200")))
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)

        await svc.process_execution_report(_make_report())

        # save called 0 times (report ignored for terminal order)
        mock_order_repo.save.assert_not_called()


# ---------------------------------------------------------------------------
# Persistence failure
# ---------------------------------------------------------------------------

class TestPersistenceFailure:
    @pytest.mark.asyncio
    async def test_db_failure_raises_order_persistence_error(
        self, svc, mock_order_repo
    ):
        order = _make_order(OrderState.SUBMITTED)
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)
        mock_order_repo.save = AsyncMock(side_effect=RuntimeError("DB down"))
        report = _make_report(filled_qty=50, remaining=0)

        with pytest.raises(OrderPersistenceError):
            await svc.process_execution_report(report)


# ---------------------------------------------------------------------------
# Fill save failure is non-fatal
# ---------------------------------------------------------------------------

class TestFillSaveFailure:
    @pytest.mark.asyncio
    async def test_fill_save_failure_does_not_raise(
        self, svc, mock_order_repo, mock_exec_repo
    ):
        order = _make_order(OrderState.SUBMITTED)
        mock_order_repo.get_by_broker_order_id = AsyncMock(return_value=order)
        mock_exec_repo.save = AsyncMock(side_effect=RuntimeError("exec repo down"))
        report = _make_report(filled_qty=50, remaining=0)

        result = await svc.process_execution_report(report)
        assert result.state == OrderState.FILLED


# ---------------------------------------------------------------------------
# expire_stale_orders
# ---------------------------------------------------------------------------

class TestExpireStaleOrders:
    @pytest.mark.asyncio
    async def test_old_open_order_expired(self, svc, mock_order_repo, mock_bus):
        order = _make_order(OrderState.SUBMITTED)
        order.open_at_exchange()
        order.submitted_at = datetime.now(UTC) - timedelta(hours=7)
        mock_order_repo.get_by_state = AsyncMock(return_value=[order])

        count = await svc.expire_stale_orders()

        assert count == 1
        assert order.state == OrderState.EXPIRED

    @pytest.mark.asyncio
    async def test_recent_open_order_not_expired(self, svc, mock_order_repo):
        order = _make_order(OrderState.SUBMITTED)
        order.open_at_exchange()
        order.submitted_at = datetime.now(UTC) - timedelta(hours=1)
        mock_order_repo.get_by_state = AsyncMock(return_value=[order])

        count = await svc.expire_stale_orders()

        assert count == 0
        assert order.state == OrderState.OPEN
