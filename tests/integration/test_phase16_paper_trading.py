"""Phase 16 integration test — full paper trading flow.

Signal → OMS → PaperBroker → Fill → Position → Exit → Position Closed

Uses real PaperBrokerAdapter (in-memory) wired to the OMS service pipeline.
No mocks for broker operations — the paper broker simulates real broker behaviour.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from core.application.services.broker.broker_execution_monitor_service import (
    BrokerExecutionMonitorService,
)
from core.application.services.broker.broker_health_service import BrokerHealthService
from core.application.services.broker.execution_guard_service import ExecutionGuardService
from core.application.services.oms.execution_monitor_service import ExecutionMonitorService
from core.application.services.oms.exit_manager_service import ExitManagerService
from core.application.services.oms.order_management_service import OrderManagementService
from core.application.services.oms.order_router_service import OrderRouterService
from core.application.services.oms.position_manager_service import PositionManagerService
from core.domain.entities.broker_session import BrokerSession
from core.domain.entities.order import Order
from core.domain.entities.position import Position
from core.domain.enums.order_state import OrderState
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.position_state import PositionState
from core.domain.exceptions.broker import ExecutionGuardError
from core.domain.risk.kill_switch_state import KillSwitchState
from core.domain.value_objects.broker_health import BrokerHealthStatus
from core.domain.value_objects.execution_report import ExecutionReport
from core.domain.value_objects.order_request import OrderRequest
from core.domain.value_objects.price import Price
from core.infrastructure.broker.order_mapper import OrderMapper
from core.infrastructure.broker.paper_broker import PaperBrokerAdapter
from core.infrastructure.config.oms_config import OmsConfig

# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------

class InMemOrderRepo:
    def __init__(self) -> None:
        self._orders: dict[uuid.UUID, Order] = {}

    async def save(self, order: Order) -> None:
        self._orders[order.order_id] = order

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        return self._orders.get(order_id)

    async def get_by_broker_order_id(self, broker_order_id: str) -> Order | None:
        return next(
            (o for o in self._orders.values() if o.broker_order_id == broker_order_id),
            None,
        )

    async def get_by_state(self, state: OrderState) -> list[Order]:
        return [o for o in self._orders.values() if o.state == state]

    async def get_by_signal_id(self, signal_id: uuid.UUID) -> Order | None:
        return next((o for o in self._orders.values() if o.signal_id == signal_id), None)


class InMemPositionRepo:
    def __init__(self) -> None:
        self._positions: dict[uuid.UUID, Position] = {}

    async def save(self, position: Position) -> None:
        self._positions[position.position_id] = position

    async def get_by_id(self, position_id: uuid.UUID) -> Position | None:
        return self._positions.get(position_id)

    async def get_open_positions(self) -> list[Position]:
        return [
            p for p in self._positions.values()
            if p.state in (PositionState.OPEN, PositionState.PARTIALLY_CLOSED)
        ]

    async def get_by_symbol(self, symbol: Any) -> list[Position]:
        return [p for p in self._positions.values() if p.symbol == symbol]

    async def get_by_signal_id(self, signal_id: uuid.UUID) -> Position | None:
        return next((p for p in self._positions.values() if p.signal_id == signal_id), None)


class InMemExecRepo:
    def __init__(self) -> None:
        self._fills: list = []

    async def save(self, fill: Any) -> None:
        self._fills.append(fill)

    async def get_by_order_id(self, order_id: uuid.UUID) -> list:
        return [f for f in self._fills if f.order_id == order_id]

    async def get_by_id(self, fill_id: uuid.UUID) -> Any | None:
        return next((f for f in self._fills if f.fill_id == fill_id), None)


class InMemCacheRepo:
    def __init__(self) -> None:
        self._idem: dict[str, uuid.UUID] = {}

    async def set_idempotency_key(
        self, signal_id: Any, order_id: Any, ttl_seconds: int = 300
    ) -> bool:
        key = str(signal_id)
        if key in self._idem:
            return False
        self._idem[key] = order_id
        return True

    async def get_idempotency_order_id(self, signal_id: Any) -> uuid.UUID | None:
        return self._idem.get(str(signal_id))

    async def cache_order(self, order_id: Any, order_json: str, ttl_seconds: int = 900) -> None:
        pass

    async def get_cached_order(self, order_id: Any) -> str | None:
        return None

    async def evict_order(self, order_id: Any) -> None:
        pass

    async def cache_position(
        self, position_id: Any, position_json: str, ttl_seconds: int = 86400
    ) -> None:
        pass

    async def get_cached_position(self, position_id: Any) -> str | None:
        return None

    async def evict_position(self, position_id: Any) -> None:
        pass


class InMemKillSwitch:
    def __init__(self, active: bool = False) -> None:
        self._active = active

    async def get_state(self) -> KillSwitchState:
        return KillSwitchState(
            is_active=self._active,
            activated_at=datetime.now(UTC) if self._active else None,
            activated_by="system" if self._active else None,
            activation_reason="test" if self._active else None,
            deactivated_at=None,
            deactivated_by=None,
            deactivation_note=None,
        )

    async def activate(self, reason: str, activated_by: str, trigger_source: str) -> None:
        self._active = True

    async def deactivate(
        self, deactivated_by: str, note: str, override_loss_check: bool = False
    ) -> None:
        self._active = False


class InMemEventBus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)

    def events_of_type(self, name: str) -> list:
        return [e for e in self.published if type(e).__name__ == name]


class PaperOrderRouter:
    """IOrderRouter backed by PaperBrokerAdapter."""

    def __init__(self, broker: PaperBrokerAdapter, session: BrokerSession) -> None:
        self._broker = broker
        self._session = session

    async def route(self, order: Order) -> str:
        req = OrderMapper.to_broker_request(order)
        return await self._broker.place_order(self._session, req)

    async def cancel(self, order: Order, reason: str = "") -> None:
        if order.broker_order_id:
            await self._broker.cancel_order(self._session, order.broker_order_id)

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport | None:
        broker_order = await self._broker.get_order(self._session, broker_order_id)
        if broker_order is None:
            return None
        return BrokerExecutionMonitorService._to_execution_report(broker_order, uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_oms_config() -> OmsConfig:
    return OmsConfig(
        max_orders_per_minute=100,
        idempotency_ttl_seconds=300,
        paper_slippage_pct=Decimal("0.0005"),
        max_position_size_lots=50,
    )


def _make_session() -> BrokerSession:
    return BrokerSession.create(
        broker_name="paper",
        api_key="key",
        encrypted_access_token="paper_mode",
        expires_at=datetime(2099, 12, 31, tzinfo=UTC),
    )


def _make_signal(
    tradingsymbol: str = "NIFTY",
    exchange: str = "NFO",
    entry_price: Decimal = Decimal("22000"),
    sl_price: Decimal = Decimal("21800"),
    target_price: Decimal = Decimal("22400"),
    direction: str = "LONG",
    position_size_lots: int = 1,
    lot_size: int = 50,
) -> OrderRequest:
    return OrderRequest(
        signal_id=uuid.uuid4(),
        instrument_token=12345,
        underlying="NIFTY",
        tradingsymbol=tradingsymbol,
        exchange=exchange,
        direction=direction,
        strategy_type="TREND",
        regime="TRENDING_BULLISH",
        position_size_lots=position_size_lots,
        lot_size=lot_size,
        entry_price=entry_price,
        stop_loss_price=sl_price,
        target_1_price=target_price,
        target_2_price=None,
        option_premium=None,
        risk_decision_id=1,
        adjusted_score=75.0,
        final_confidence=80.0,
        valid_until=datetime.now(UTC) + timedelta(minutes=15),
        trading_mode="PAPER",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def setup() -> dict:
    broker = PaperBrokerAdapter(initial_capital=Decimal("1000000"))
    broker.set_ltp("NFO", "NIFTY", Decimal("22000"))

    session = _make_session()

    order_repo = InMemOrderRepo()
    position_repo = InMemPositionRepo()
    exec_repo = InMemExecRepo()
    cache_repo = InMemCacheRepo()
    kill_switch = InMemKillSwitch(active=False)
    event_bus = InMemEventBus()
    config = _make_oms_config()

    router = PaperOrderRouter(broker=broker, session=session)

    exec_monitor = ExecutionMonitorService(
        order_repository=order_repo,
        execution_repository=exec_repo,
        order_router=router,
        event_bus=event_bus,
    )
    position_mgr = PositionManagerService(
        position_repository=position_repo,
        event_bus=event_bus,
    )
    order_mgr = OrderManagementService(
        order_repository=order_repo,
        order_cache=cache_repo,
        kill_switch_repository=kill_switch,
        event_bus=event_bus,
        config=config,
    )
    order_router_svc = OrderRouterService(
        order_router=router,
        order_repository=order_repo,
        event_bus=event_bus,
    )
    exit_mgr = ExitManagerService(
        order_repository=order_repo,
        position_repository=position_repo,
        order_router_service=router,
        position_manager_service=position_mgr,
        event_bus=event_bus,
    )
    broker_monitor = BrokerExecutionMonitorService(
        broker=broker,
        order_repository=order_repo,
        execution_monitor=exec_monitor,
    )
    return {
        "broker": broker,
        "session": session,
        "kill_switch": kill_switch,
        "order_repo": order_repo,
        "position_repo": position_repo,
        "exec_repo": exec_repo,
        "event_bus": event_bus,
        "order_mgr": order_mgr,
        "order_router_svc": order_router_svc,
        "exec_monitor": exec_monitor,
        "position_mgr": position_mgr,
        "exit_mgr": exit_mgr,
        "broker_monitor": broker_monitor,
    }


# ---------------------------------------------------------------------------
# Helper: create → route order (returns routed Order)
# ---------------------------------------------------------------------------

async def _create_and_route(setup: dict, request: OrderRequest) -> Order:
    result = await setup["order_mgr"].process(request)
    order = await setup["order_repo"].get_by_id(result.order_id)
    return await setup["order_router_svc"].route(order)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPaperTradingFlow:
    """Full paper trading integration: Signal → OMS → Broker → Fill → Position → Exit."""

    async def test_signal_creates_order_in_pending_state(self, setup: dict) -> None:
        request = _make_signal()
        result = await setup["order_mgr"].process(request)
        assert result.accepted is True
        order = await setup["order_repo"].get_by_id(result.order_id)
        assert order is not None
        assert order.state == OrderState.PENDING

    async def test_route_sends_order_to_paper_broker(self, setup: dict) -> None:
        request = _make_signal()
        order = await _create_and_route(setup, request)
        assert order.state == OrderState.SUBMITTED
        assert order.broker_order_id.startswith("PAPER-")

    async def test_poll_detects_paper_broker_fill(self, setup: dict) -> None:
        """BrokerExecutionMonitorService polls paper broker and processes the fill."""
        request = _make_signal()
        order = await _create_and_route(setup, request)
        assert order.state == OrderState.SUBMITTED

        # Paper broker fills immediately on place_order — poll should detect it
        updated = await setup["broker_monitor"].poll_and_process(setup["session"])
        assert updated >= 1

        order = await setup["order_repo"].get_by_id(order.order_id)
        assert order.state == OrderState.FILLED

    async def test_fill_enables_position_open(self, setup: dict) -> None:
        """After fill, position can be explicitly opened."""
        request = _make_signal()
        order = await _create_and_route(setup, request)

        # Poll to process the fill
        await setup["broker_monitor"].poll_and_process(setup["session"])
        order = await setup["order_repo"].get_by_id(order.order_id)

        # Open position
        position = await setup["position_mgr"].open_position(order)
        assert position.state == PositionState.OPEN

    async def test_position_closed_on_stop_loss(self, setup: dict) -> None:
        """Fill → position opened → SL fill → position closed as LOSS."""
        request = _make_signal()
        order = await _create_and_route(setup, request)
        await setup["broker_monitor"].poll_and_process(setup["session"])
        order = await setup["order_repo"].get_by_id(order.order_id)
        position = await setup["position_mgr"].open_position(order)

        await setup["exit_mgr"].handle_stop_loss_fill(
            position=position,
            fill_price=Price(Decimal("21700")),
            stop_order_id=None,
        )

        position = await setup["position_repo"].get_by_id(position.position_id)
        assert position.state == PositionState.CLOSED
        assert position.outcome == PositionOutcome.LOSS

    async def test_position_closed_on_target(self, setup: dict) -> None:
        """Fill → position opened → target fill → position closed as WIN."""
        request = _make_signal()
        order = await _create_and_route(setup, request)
        await setup["broker_monitor"].poll_and_process(setup["session"])
        order = await setup["order_repo"].get_by_id(order.order_id)
        position = await setup["position_mgr"].open_position(order)

        await setup["exit_mgr"].handle_target_fill(
            position=position,
            fill_price=Price(Decimal("22500")),
            target_order_id=None,
        )

        position = await setup["position_repo"].get_by_id(position.position_id)
        assert position.state == PositionState.CLOSED
        assert position.outcome == PositionOutcome.WIN

    async def test_full_flow_signal_to_position_closed(self, setup: dict) -> None:
        """Complete flow: Signal → OMS → Broker → Fill → Position → SL → Closed."""
        # 1. Create signal
        request = _make_signal()

        # 2. Create OMS order (persisted PENDING)
        result = await setup["order_mgr"].process(request)
        order = await setup["order_repo"].get_by_id(result.order_id)

        # 3. Route to paper broker (SUBMITTED)
        order = await setup["order_router_svc"].route(order)
        assert order.state == OrderState.SUBMITTED

        # 4. Poll broker — paper broker fills immediately
        await setup["broker_monitor"].poll_and_process(setup["session"])
        order = await setup["order_repo"].get_by_id(order.order_id)
        assert order.state == OrderState.FILLED

        # 5. Open position
        position = await setup["position_mgr"].open_position(order)
        assert position.state == PositionState.OPEN

        # 6. Exit on stop-loss
        await setup["exit_mgr"].handle_stop_loss_fill(
            position=position,
            fill_price=Price(Decimal("21700")),
            stop_order_id=None,
        )

        # 7. Verify position is closed
        final_position = await setup["position_repo"].get_by_id(position.position_id)
        assert final_position.state == PositionState.CLOSED
        assert final_position.outcome == PositionOutcome.LOSS

        # 8. Verify events published throughout the pipeline
        assert len(setup["event_bus"].events_of_type("OrderFilled")) >= 1
        assert len(setup["event_bus"].events_of_type("PositionOpened")) >= 1
        assert len(setup["event_bus"].events_of_type("PositionClosed")) >= 1

    async def test_margin_decreases_after_trade(self, setup: dict) -> None:
        """Paper broker tracks margin usage after a trade."""
        margin_before = await setup["broker"].get_margin(setup["session"])
        assert margin_before.used_margin == Decimal("0")

        await _create_and_route(setup, _make_signal())

        margin_after = await setup["broker"].get_margin(setup["session"])
        assert margin_after.used_margin > Decimal("0")
        assert margin_after.available_cash < Decimal("1000000")


class TestExecutionGuardWithPaperBroker:
    """ExecutionGuardService wired to real PaperBrokerAdapter."""

    def _make_guard(
        self, kill_switch: InMemKillSwitch, broker: PaperBrokerAdapter
    ) -> ExecutionGuardService:
        return ExecutionGuardService(
            kill_switch_repository=kill_switch,
            broker=broker,
            enforce_market_hours=False,
        )

    async def test_guard_passes_for_paper_broker(self) -> None:
        broker = PaperBrokerAdapter()
        kill_switch = InMemKillSwitch(active=False)
        session = _make_session()
        guard = self._make_guard(kill_switch, broker)
        await guard.guard(session)  # should not raise

    async def test_guard_fails_when_kill_switch_active(self) -> None:
        broker = PaperBrokerAdapter()
        kill_switch = InMemKillSwitch(active=True)
        session = _make_session()
        guard = self._make_guard(kill_switch, broker)
        with pytest.raises(ExecutionGuardError) as exc_info:
            await guard.guard(session)
        assert exc_info.value.guard == "kill_switch"

    async def test_cancellation_bypasses_kill_switch(self) -> None:
        broker = PaperBrokerAdapter()
        kill_switch = InMemKillSwitch(active=True)
        session = _make_session()
        guard = self._make_guard(kill_switch, broker)
        # should NOT raise for cancellations even with kill switch active
        await guard.guard(session, is_cancellation=True)


class TestBrokerHealthWithPaperBroker:
    """BrokerHealthService wired to real PaperBrokerAdapter."""

    async def test_health_check_paper_broker_healthy_no_session(self) -> None:
        broker = PaperBrokerAdapter()
        svc = BrokerHealthService(broker)
        report = await svc.check(session=None)
        assert report.status == BrokerHealthStatus.HEALTHY

    async def test_health_check_paper_broker_healthy_with_session(self) -> None:
        broker = PaperBrokerAdapter()
        session = _make_session()
        svc = BrokerHealthService(broker)
        report = await svc.check(session=session)
        assert report.status == BrokerHealthStatus.HEALTHY
        assert report.details.get("connectivity") == "ok"
        assert report.details.get("auth") == "ok"
        assert report.details.get("orders") == "ok"
        assert report.details.get("positions") == "ok"
        assert report.details.get("margin") == "ok"

    async def test_health_latency_is_non_negative(self) -> None:
        broker = PaperBrokerAdapter()
        svc = BrokerHealthService(broker)
        report = await svc.check(session=None)
        assert report.latency_ms >= 0
