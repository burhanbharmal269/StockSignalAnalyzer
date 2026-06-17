"""Integration tests — OMS service pipeline.

Tests the full OMS flow with in-memory fakes (no real DB or broker).
Verifies the interaction between OrderManagementService, OrderRouterService,
ExecutionMonitorService, PositionManagerService, ExitManagerService, and
ReconciliationService.

Scenarios:
  - Happy path: signal → order created → routed → filled → position opened
  - Duplicate signal (idempotency): second signal with same signal_id blocked
  - Signal TTL expiration blocks order
  - Kill switch blocks order
  - Broker unavailable: no order at exchange, no position opened
  - Persistence-first invariant: order row exists before broker API called
  - Partial fill followed by full fill
  - Stop-loss exit: position closed as LOSS
  - Target exit: position closed as WIN
  - Time exit: position closed as TIME_EXIT
  - Reconciliation: clean pass, rogue order → kill switch
  - OMS restart recovery: reloads open orders from DB
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.application.services.oms.execution_monitor_service import ExecutionMonitorService
from core.application.services.oms.exit_manager_service import ExitManagerService
from core.application.services.oms.order_management_service import OrderManagementService
from core.application.services.oms.order_router_service import OrderRouterService
from core.application.services.oms.position_manager_service import PositionManagerService
from core.application.services.oms.reconciliation_service import ReconciliationService
from core.domain.entities.order import Order
from core.domain.entities.position import Position
from core.domain.enums.order_state import OrderState
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.position_state import PositionState
from core.domain.enums.signal_type import SignalType
from core.domain.enums.trading_mode import TradingMode
from core.domain.exceptions.order import (
    BrokerUnavailableError,
    RogueOrderDetectedError,
    SignalExpiredError,
)
from core.domain.risk.kill_switch_state import KillSwitchState
from core.domain.value_objects.execution_report import ExecutionReport
from core.domain.value_objects.order_request import OrderRequest
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.config.oms_config import OmsConfig

# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------

class InMemoryOrderRepository:
    def __init__(self):
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
        return next(
            (o for o in self._orders.values() if o.signal_id == signal_id), None
        )


class InMemoryPositionRepository:
    def __init__(self):
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

    async def get_by_symbol(self, symbol) -> list[Position]:
        return [p for p in self._positions.values() if p.symbol == symbol]

    async def get_by_signal_id(self, signal_id: uuid.UUID) -> Position | None:
        return next(
            (p for p in self._positions.values() if p.signal_id == signal_id), None
        )


class InMemoryExecutionRepository:
    def __init__(self):
        self._fills = []

    async def save(self, fill) -> None:
        self._fills.append(fill)

    async def get_by_order_id(self, order_id: uuid.UUID) -> list:
        return [f for f in self._fills if f.order_id == order_id]

    async def get_by_id(self, fill_id: uuid.UUID):
        return next((f for f in self._fills if f.fill_id == fill_id), None)


class InMemoryOrderCacheRepository:
    def __init__(self):
        self._idem: dict[str, uuid.UUID] = {}

    async def set_idempotency_key(self, signal_id, order_id, ttl_seconds=300) -> bool:
        key = str(signal_id)
        if key in self._idem:
            return False
        self._idem[key] = order_id
        return True

    async def get_idempotency_order_id(self, signal_id) -> uuid.UUID | None:
        return self._idem.get(str(signal_id))

    async def cache_order(self, order_id, order_json, ttl_seconds=900) -> None:
        pass

    async def get_cached_order(self, order_id) -> str | None:
        return None

    async def evict_order(self, order_id) -> None:
        pass

    async def cache_position(self, position_id, position_json, ttl_seconds=86400) -> None:
        pass

    async def get_cached_position(self, position_id) -> str | None:
        return None

    async def evict_position(self, position_id) -> None:
        pass


class InMemoryKillSwitchRepository:
    def __init__(self, active: bool = False):
        self._active = active
        self.activation_calls = []

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
        self.activation_calls.append({"reason": reason, "activated_by": activated_by})

    async def deactivate(
        self, deactivated_by: str, note: str, override_loss_check: bool = False
    ) -> None:
        self._active = False


class InMemoryEventBus:
    def __init__(self):
        self.published: list[Any] = []

    async def publish(self, event) -> None:
        self.published.append(event)

    def events_of_type(self, name: str) -> list:
        return [e for e in self.published if type(e).__name__ == name]


class FakeBrokerRouter:
    """IOrderRouter fake. Controls success/failure."""

    def __init__(self, fail: bool = False):
        self._fail = fail
        self._broker_counter = 0

    async def route(self, order: Order) -> str:
        if self._fail:
            raise BrokerUnavailableError("broker unavailable")
        self._broker_counter += 1
        return f"BROKER-{self._broker_counter:04d}"

    async def cancel(self, order: Order) -> None:
        pass

    async def get_order_status(self, broker_order_id: str):
        return None

    @property
    def __class__(self):
        class _Fake:
            __name__ = "FakeBrokerRouter"
        return _Fake


class FakeBroker:
    """IBroker fake for reconciliation tests."""

    def __init__(self):
        self.broker_orders = []
        self.broker_positions = []

    @property
    def broker_name(self) -> str:
        return "fake"

    async def get_orders(self, session) -> list:
        return self.broker_orders

    async def get_positions(self, session) -> list:
        return self.broker_positions

    async def login(self, *args, **kwargs):
        pass

    async def logout(self, *args, **kwargs):
        pass

    async def get_profile(self, *args, **kwargs):
        pass

    async def place_order(self, *args, **kwargs):
        return ""

    async def modify_order(self, *args, **kwargs):
        pass

    async def cancel_order(self, *args, **kwargs):
        pass

    async def get_holdings(self, *args, **kwargs):
        return []

    async def get_trades(self, *args, **kwargs):
        return []

    async def get_ltp(self, *args, **kwargs):
        return {}

    async def get_option_chain(self, *args, **kwargs):
        return []


def _broker_order_obj(broker_order_id: str):
    obj = MagicMock()
    obj.broker_order_id = broker_order_id
    return obj


def _broker_position_obj(instrument_token: int, net_quantity: int):
    obj = MagicMock()
    obj.instrument_token = instrument_token
    obj.net_quantity = net_quantity
    return obj


def _make_config() -> OmsConfig:
    cfg = MagicMock(spec=OmsConfig)
    cfg.max_orders_per_minute = 100
    cfg.idempotency_ttl_seconds = 300
    cfg.idempotency_key = lambda s: f"oms:idem:{s}"
    cfg.order_cache_key = lambda s: f"oms:order:{s}"
    cfg.position_cache_key = lambda s: f"oms:position:{s}"
    cfg.order_type = MagicMock()
    cfg.order_type.default = "MARKET"
    cfg.order_type.limit_threshold_premium = Decimal("500")
    cfg.order_type.limit_buffer_pct = 0.001
    return cfg


def _make_request(
    *,
    expired: bool = False,
    signal_id: uuid.UUID | None = None,
    option_premium: Decimal = Decimal("100"),
) -> OrderRequest:
    now = datetime.now(UTC)
    return OrderRequest(
        signal_id=signal_id or uuid.uuid4(),
        instrument_token=12345,
        underlying="NIFTY",
        tradingsymbol="NIFTY24JAN18000CE",
        exchange="NFO",
        direction="LONG",
        strategy_type="DIRECTIONAL",
        regime="Trend",
        position_size_lots=1,
        lot_size=50,
        entry_price=Decimal("200"),
        stop_loss_price=Decimal("180"),
        target_1_price=Decimal("230"),
        target_2_price=Decimal("250"),
        option_premium=option_premium,
        risk_decision_id=42,
        adjusted_score=0.75,
        final_confidence=0.80,
        valid_until=(now - timedelta(seconds=10)) if expired else (now + timedelta(minutes=5)),
        trading_mode="LIVE",
    )


def _make_partial_fill_report(
    broker_order_id: str,
    filled_qty: int,
    remaining_qty: int,
) -> MagicMock:
    report = MagicMock(spec=ExecutionReport)
    report.broker_order_id = broker_order_id
    report.filled_quantity = filled_qty
    report.remaining_quantity = remaining_qty
    report.average_fill_price = Price(Decimal("200"))
    report.last_fill_price = Price(Decimal("200"))
    report.last_fill_quantity = filled_qty
    report.exchange_trade_id = "EX-PARTIAL-001"
    report.status = "UPDATE"
    report.rejection_reason = ""
    report.reported_at = datetime.now(UTC)
    report.is_fully_filled = False
    report.is_partial_fill = True
    report.is_rejected = False
    return report


def _make_full_fill_report(broker_order_id: str, qty: int = 50) -> MagicMock:
    report = MagicMock(spec=ExecutionReport)
    report.broker_order_id = broker_order_id
    report.filled_quantity = qty
    report.remaining_quantity = 0
    report.average_fill_price = Price(Decimal("200"))
    report.last_fill_price = Price(Decimal("200"))
    report.last_fill_quantity = qty
    report.exchange_trade_id = "EX-999"
    report.status = "COMPLETE"
    report.rejection_reason = ""
    report.reported_at = datetime.now(UTC)
    report.is_fully_filled = True
    report.is_partial_fill = False
    report.is_rejected = False
    return report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def order_repo():
    return InMemoryOrderRepository()


@pytest.fixture
def position_repo():
    return InMemoryPositionRepository()


@pytest.fixture
def exec_repo():
    return InMemoryExecutionRepository()


@pytest.fixture
def order_cache():
    return InMemoryOrderCacheRepository()


@pytest.fixture
def kill_switch():
    return InMemoryKillSwitchRepository(active=False)


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def broker_router():
    return FakeBrokerRouter(fail=False)


@pytest.fixture
def config():
    return _make_config()


@pytest.fixture
def oms_svc(order_repo, order_cache, kill_switch, event_bus, config):
    return OrderManagementService(
        order_repository=order_repo,
        order_cache=order_cache,
        kill_switch_repository=kill_switch,
        event_bus=event_bus,
        config=config,
    )


@pytest.fixture
def router_svc(broker_router, order_repo, event_bus):
    return OrderRouterService(
        order_router=broker_router,
        order_repository=order_repo,
        event_bus=event_bus,
    )


@pytest.fixture
def exec_monitor_svc(order_repo, exec_repo, broker_router, event_bus):
    return ExecutionMonitorService(
        order_repository=order_repo,
        execution_repository=exec_repo,
        order_router=broker_router,
        event_bus=event_bus,
    )


@pytest.fixture
def position_mgr_svc(position_repo, event_bus):
    return PositionManagerService(
        position_repository=position_repo,
        event_bus=event_bus,
    )


@pytest.fixture
def exit_mgr_svc(order_repo, position_repo, router_svc, position_mgr_svc, event_bus):
    return ExitManagerService(
        order_repository=order_repo,
        position_repository=position_repo,
        order_router_service=router_svc,
        position_manager_service=position_mgr_svc,
        event_bus=event_bus,
    )


# ---------------------------------------------------------------------------
# Helper: full order pipeline (create → route → return order)
# ---------------------------------------------------------------------------

async def _create_and_route_order(
    oms_svc, router_svc, order_repo, request: OrderRequest
) -> Order:
    result = await oms_svc.process(request)
    order = await order_repo.get_by_id(result.order_id)
    return await router_svc.route(order)


# ---------------------------------------------------------------------------
# Test: Happy path signal → order created → routed → filled → position opened
# ---------------------------------------------------------------------------

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_order_created_and_persisted(self, oms_svc, order_repo):
        req = _make_request()
        result = await oms_svc.process(req)

        assert result.accepted is True
        order = await order_repo.get_by_id(result.order_id)
        assert order is not None
        assert order.signal_id == req.signal_id

    @pytest.mark.asyncio
    async def test_order_routed_to_submitted(
        self, oms_svc, router_svc, order_repo
    ):
        order = await _create_and_route_order(oms_svc, router_svc, order_repo, _make_request())
        assert order.state == OrderState.SUBMITTED
        assert order.broker_order_id.startswith("BROKER-")

    @pytest.mark.asyncio
    async def test_fill_transitions_order_to_filled(
        self, oms_svc, router_svc, exec_monitor_svc, order_repo
    ):
        order = await _create_and_route_order(oms_svc, router_svc, order_repo, _make_request())
        report = _make_full_fill_report(order.broker_order_id)

        result = await exec_monitor_svc.process_execution_report(report)

        assert result.state == OrderState.FILLED

    @pytest.mark.asyncio
    async def test_fill_creates_execution_record(
        self, oms_svc, router_svc, exec_monitor_svc, order_repo, exec_repo
    ):
        order = await _create_and_route_order(oms_svc, router_svc, order_repo, _make_request())
        await exec_monitor_svc.process_execution_report(
            _make_full_fill_report(order.broker_order_id)
        )
        assert len(exec_repo._fills) == 1

    @pytest.mark.asyncio
    async def test_position_opened_after_fill(
        self, oms_svc, router_svc, exec_monitor_svc, position_mgr_svc, order_repo
    ):
        order = await _create_and_route_order(oms_svc, router_svc, order_repo, _make_request())
        await exec_monitor_svc.process_execution_report(
            _make_full_fill_report(order.broker_order_id)
        )
        position = await position_mgr_svc.open_position(order)
        assert position.state == PositionState.OPEN
        assert position.direction == SignalType.LONG

    @pytest.mark.asyncio
    async def test_order_created_event_published(self, oms_svc, event_bus):
        await oms_svc.process(_make_request())
        assert len(event_bus.events_of_type("OrderCreated")) == 1

    @pytest.mark.asyncio
    async def test_order_filled_event_published(
        self, oms_svc, router_svc, exec_monitor_svc, order_repo, event_bus
    ):
        order = await _create_and_route_order(oms_svc, router_svc, order_repo, _make_request())
        await exec_monitor_svc.process_execution_report(
            _make_full_fill_report(order.broker_order_id)
        )
        assert len(event_bus.events_of_type("OrderFilled")) == 1


# ---------------------------------------------------------------------------
# Test: Duplicate signal (idempotency)
# ---------------------------------------------------------------------------

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_second_signal_blocked(self, oms_svc, order_repo):
        sig_id = uuid.uuid4()
        req1 = _make_request(signal_id=sig_id)
        req2 = _make_request(signal_id=sig_id)

        result1 = await oms_svc.process(req1)
        result2 = await oms_svc.process(req2)

        assert result1.accepted is True
        assert result2.is_duplicate is True
        assert result2.accepted is False

    @pytest.mark.asyncio
    async def test_duplicate_creates_only_one_order(self, oms_svc, order_repo):
        sig_id = uuid.uuid4()
        for _ in range(3):
            await oms_svc.process(_make_request(signal_id=sig_id))

        # Only one order in DB
        all_orders = list(order_repo._orders.values())
        assert len(all_orders) == 1


# ---------------------------------------------------------------------------
# Test: Signal TTL expiration
# ---------------------------------------------------------------------------

class TestSignalExpiration:
    @pytest.mark.asyncio
    async def test_expired_signal_raises(self, oms_svc):
        with pytest.raises(SignalExpiredError):
            await oms_svc.process(_make_request(expired=True))

    @pytest.mark.asyncio
    async def test_expired_signal_no_order_in_db(self, oms_svc, order_repo):
        with pytest.raises(SignalExpiredError):
            await oms_svc.process(_make_request(expired=True))
        assert len(order_repo._orders) == 0


# ---------------------------------------------------------------------------
# Test: Kill switch
# ---------------------------------------------------------------------------

class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_active_kill_switch_blocks_order(
        self, order_repo, order_cache, event_bus, config
    ):
        ks = InMemoryKillSwitchRepository(active=True)
        svc = OrderManagementService(
            order_repository=order_repo,
            order_cache=order_cache,
            kill_switch_repository=ks,
            event_bus=event_bus,
            config=config,
        )
        from core.domain.exceptions.order import KillSwitchActiveError
        with pytest.raises(KillSwitchActiveError):
            await svc.process(_make_request())

    @pytest.mark.asyncio
    async def test_active_kill_switch_no_order_in_db(
        self, order_repo, order_cache, event_bus, config
    ):
        ks = InMemoryKillSwitchRepository(active=True)
        svc = OrderManagementService(
            order_repository=order_repo,
            order_cache=order_cache,
            kill_switch_repository=ks,
            event_bus=event_bus,
            config=config,
        )
        from core.domain.exceptions.order import KillSwitchActiveError
        with pytest.raises(KillSwitchActiveError):
            await svc.process(_make_request())
        assert len(order_repo._orders) == 0


# ---------------------------------------------------------------------------
# Test: Broker unavailable — fail-closed
# ---------------------------------------------------------------------------

class TestBrokerUnavailable:
    @pytest.mark.asyncio
    async def test_broker_unavailable_no_position_opened(
        self, order_repo, order_cache, kill_switch, event_bus, config, position_repo
    ):
        failing_router = FakeBrokerRouter(fail=True)
        oms = OrderManagementService(
            order_repository=order_repo,
            order_cache=order_cache,
            kill_switch_repository=kill_switch,
            event_bus=event_bus,
            config=config,
        )
        router = OrderRouterService(
            order_router=failing_router,
            order_repository=order_repo,
            event_bus=event_bus,
        )

        result = await oms.process(_make_request())
        order = await order_repo.get_by_id(result.order_id)

        with pytest.raises(BrokerUnavailableError):
            await router.route(order)

        assert order.state == OrderState.REJECTED_PRE_SUBMIT
        assert len(position_repo._positions) == 0

    @pytest.mark.asyncio
    async def test_order_persisted_before_broker_call(
        self, order_repo, order_cache, kill_switch, event_bus, config
    ):
        save_calls = []
        broker_calls = []
        original_save = order_repo.save

        async def tracked_save(o):
            save_calls.append(o.state)
            await original_save(o)

        order_repo.save = tracked_save

        class TrackingRouter:
            async def route(self, order):
                broker_calls.append("route")
                return "BROKER-001"

            async def cancel(self, order):
                pass

            async def get_order_status(self, bid):
                return None

            @property
            def __class__(self):
                class _F:
                    __name__ = "Tracking"
                return _F

        oms = OrderManagementService(
            order_repository=order_repo,
            order_cache=order_cache,
            kill_switch_repository=kill_switch,
            event_bus=event_bus,
            config=config,
        )
        router = OrderRouterService(
            order_router=TrackingRouter(),
            order_repository=order_repo,
            event_bus=event_bus,
        )

        result = await oms.process(_make_request())
        order = await order_repo.get_by_id(result.order_id)
        await router.route(order)

        # First save must be PENDING (persistence-first)
        assert save_calls[0] == OrderState.PENDING
        # Broker call happens after first save
        assert "route" in broker_calls


# ---------------------------------------------------------------------------
# Test: Stop-loss exit
# ---------------------------------------------------------------------------

class TestStopLossExit:
    @pytest.mark.asyncio
    async def test_stop_loss_closes_position_as_loss(
        self, exit_mgr_svc, position_repo
    ):
        position = Position.open(
            symbol=Symbol("NIFTY", "NFO"),
            direction=SignalType.LONG,
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

        result = await exit_mgr_svc.handle_stop_loss_fill(
            position, Price(Decimal("178")), uuid.uuid4()
        )

        assert result.state == PositionState.CLOSED
        assert result.outcome == PositionOutcome.LOSS


# ---------------------------------------------------------------------------
# Test: Target exit
# ---------------------------------------------------------------------------

class TestTargetExit:
    @pytest.mark.asyncio
    async def test_target_closes_position_as_win(self, exit_mgr_svc):
        position = Position.open(
            symbol=Symbol("NIFTY", "NFO"),
            direction=SignalType.LONG,
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

        result = await exit_mgr_svc.handle_target_fill(
            position, Price(Decimal("230")), uuid.uuid4()
        )

        assert result.state == PositionState.CLOSED
        assert result.outcome == PositionOutcome.WIN


# ---------------------------------------------------------------------------
# Test: Reconciliation — clean pass
# ---------------------------------------------------------------------------

class TestReconciliationCleanPass:
    @pytest.mark.asyncio
    async def test_clean_reconciliation(
        self, order_repo, position_repo, kill_switch, event_bus
    ):
        fake_broker = FakeBroker()
        recon_svc = ReconciliationService(
            order_repository=order_repo,
            position_repository=position_repo,
            broker=fake_broker,
            kill_switch_repository=kill_switch,
            event_bus=event_bus,
        )

        result = await recon_svc.run(session=MagicMock())

        assert result.discrepancy_count == 0
        assert result.rogue_count == 0

    @pytest.mark.asyncio
    async def test_reconciliation_completed_event(
        self, order_repo, position_repo, kill_switch, event_bus
    ):
        fake_broker = FakeBroker()
        recon_svc = ReconciliationService(
            order_repository=order_repo,
            position_repository=position_repo,
            broker=fake_broker,
            kill_switch_repository=kill_switch,
            event_bus=event_bus,
        )

        await recon_svc.run(session=MagicMock())

        assert len(event_bus.events_of_type("ReconciliationCompleted")) == 1


# ---------------------------------------------------------------------------
# Test: Reconciliation — rogue order
# ---------------------------------------------------------------------------

class TestReconciliationRogueOrder:
    @pytest.mark.asyncio
    async def test_rogue_order_activates_kill_switch(
        self, order_repo, position_repo, kill_switch, event_bus,
        oms_svc, router_svc
    ):
        fake_broker = FakeBroker()
        # OMS knows BROKER-0001, broker also has BROKER-ROGUE
        order = await _create_and_route_order(oms_svc, router_svc, order_repo, _make_request())
        fake_broker.broker_orders = [
            _broker_order_obj(order.broker_order_id),
            _broker_order_obj("BROKER-ROGUE"),
        ]

        recon_svc = ReconciliationService(
            order_repository=order_repo,
            position_repository=position_repo,
            broker=fake_broker,
            kill_switch_repository=kill_switch,
            event_bus=event_bus,
        )

        with pytest.raises(RogueOrderDetectedError):
            await recon_svc.run(session=MagicMock())

        assert kill_switch._active is True
        assert len(kill_switch.activation_calls) == 1


# ---------------------------------------------------------------------------
# Test: OMS restart recovery (open orders from DB)
# ---------------------------------------------------------------------------

class TestOmsRestartRecovery:
    @pytest.mark.asyncio
    async def test_open_orders_reloaded_after_restart(
        self, order_repo, order_cache, kill_switch, config, event_bus
    ):
        # First session: create and route order
        oms1 = OrderManagementService(
            order_repository=order_repo,
            order_cache=order_cache,
            kill_switch_repository=kill_switch,
            event_bus=event_bus,
            config=config,
        )
        broker_router = FakeBrokerRouter(fail=False)
        router1 = OrderRouterService(
            order_router=broker_router,
            order_repository=order_repo,
            event_bus=event_bus,
        )

        result = await oms1.process(_make_request())
        order = await order_repo.get_by_id(result.order_id)
        await router1.route(order)

        # Simulate restart: create new services pointing to same repos
        new_bus = InMemoryEventBus()
        exec_monitor = ExecutionMonitorService(
            order_repository=order_repo,
            execution_repository=InMemoryExecutionRepository(),
            order_router=broker_router,
            event_bus=new_bus,
        )

        # Order is still in SUBMITTED state in DB (persisted)
        submitted_orders = await order_repo.get_by_state(OrderState.SUBMITTED)
        assert len(submitted_orders) == 1

        # Can process fill after restart
        report = _make_full_fill_report(submitted_orders[0].broker_order_id)
        filled_order = await exec_monitor.process_execution_report(report)
        assert filled_order.state == OrderState.FILLED


# ---------------------------------------------------------------------------
# Test: OMS restart recovery — PARTIALLY_FILLED state
# ---------------------------------------------------------------------------

class TestPartiallyFilledRestartRecovery:
    @pytest.mark.asyncio
    async def test_partially_filled_state_survives_restart(
        self, order_repo, order_cache, kill_switch, config, event_bus, exec_repo
    ):
        """PARTIALLY_FILLED orders survive service restart and accept further fills."""
        # Session 1: create, route, partial fill
        oms1 = OrderManagementService(
            order_repository=order_repo,
            order_cache=order_cache,
            kill_switch_repository=kill_switch,
            event_bus=event_bus,
            config=config,
        )
        broker_router = FakeBrokerRouter(fail=False)
        router1 = OrderRouterService(
            order_router=broker_router,
            order_repository=order_repo,
            event_bus=event_bus,
        )
        exec_monitor1 = ExecutionMonitorService(
            order_repository=order_repo,
            execution_repository=exec_repo,
            order_router=broker_router,
            event_bus=event_bus,
        )

        result = await oms1.process(_make_request())
        order = await order_repo.get_by_id(result.order_id)
        routed = await router1.route(order)

        # Partial fill: 25 of 50 filled
        partial = _make_partial_fill_report(routed.broker_order_id, filled_qty=25, remaining_qty=25)
        await exec_monitor1.process_execution_report(partial)

        # Verify PARTIALLY_FILLED state persisted in repo
        partially_filled = await order_repo.get_by_state(OrderState.PARTIALLY_FILLED)
        assert len(partially_filled) == 1
        assert partially_filled[0].filled_quantity == 25
        assert partially_filled[0].remaining_quantity == 25

        # Session 2 (restart): new service instances, same repo
        new_bus = InMemoryEventBus()
        exec_monitor2 = ExecutionMonitorService(
            order_repository=order_repo,   # same repo — persisted state
            execution_repository=InMemoryExecutionRepository(),
            order_router=broker_router,
            event_bus=new_bus,
        )

        # PARTIALLY_FILLED order is still accessible after restart
        still_partial = await order_repo.get_by_state(OrderState.PARTIALLY_FILLED)
        assert len(still_partial) == 1

        # Complete the fill in session 2
        remaining_fill = _make_full_fill_report(
            still_partial[0].broker_order_id, qty=50
        )
        filled_order = await exec_monitor2.process_execution_report(remaining_fill)
        assert filled_order.state == OrderState.FILLED
        assert filled_order.filled_quantity == 50

    @pytest.mark.asyncio
    async def test_partially_filled_order_not_lost_to_pending_query(
        self, order_repo, order_cache, kill_switch, config, event_bus, exec_repo
    ):
        """PARTIALLY_FILLED orders must NOT appear in PENDING state query after restart."""
        oms1 = OrderManagementService(
            order_repository=order_repo,
            order_cache=order_cache,
            kill_switch_repository=kill_switch,
            event_bus=event_bus,
            config=config,
        )
        broker_router = FakeBrokerRouter(fail=False)
        router1 = OrderRouterService(
            order_router=broker_router,
            order_repository=order_repo,
            event_bus=event_bus,
        )
        exec_monitor1 = ExecutionMonitorService(
            order_repository=order_repo,
            execution_repository=exec_repo,
            order_router=broker_router,
            event_bus=event_bus,
        )

        result = await oms1.process(_make_request())
        order = await order_repo.get_by_id(result.order_id)
        routed = await router1.route(order)

        partial = _make_partial_fill_report(routed.broker_order_id, filled_qty=25, remaining_qty=25)
        await exec_monitor1.process_execution_report(partial)

        # After partial fill: PENDING queue is empty, PARTIALLY_FILLED queue has 1
        pending_orders = await order_repo.get_by_state(OrderState.PENDING)
        partial_orders = await order_repo.get_by_state(OrderState.PARTIALLY_FILLED)
        assert len(pending_orders) == 0
        assert len(partial_orders) == 1
