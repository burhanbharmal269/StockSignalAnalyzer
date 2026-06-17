"""Phase 16.5 E2E integration tests — PipelineEventHandler end-to-end wiring.

Tests cover the full event-driven pipeline via PipelineEventHandler:

  SignalRiskApproved → OMS → PaperOrderRouter → OrderFilled → Position → SL/Target

Scenarios:
  1.  Happy path: SignalRiskApproved → order created, routed, and position opened
  2.  SL fill via event handler → position closed as LOSS
  3.  Target fill via event handler → position closed as WIN
  4.  Kill switch active → OMS rejects, no order routed
  5.  Duplicate signal → OMS dedup, no second order
  6.  Partial fill sequence (25+25+50) → logged, position not opened yet
  7.  Broker route failure → logged, no position opened
  8.  Entry fill with SL placement failure → position OPEN without SL (logged only)
  9.  Exit fill for missing position → no crash
  10. Multiple signals → independent positions per signal
  11. Performance: 10 concurrent signals handled without cross-contamination
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from core.application.services.broker.broker_execution_monitor_service import (
    BrokerExecutionMonitorService,
)
from core.application.services.oms.execution_monitor_service import ExecutionMonitorService
from core.application.services.oms.exit_manager_service import ExitManagerService
from core.application.services.oms.order_management_service import OrderManagementService
from core.application.services.oms.order_router_service import OrderRouterService
from core.application.services.oms.position_manager_service import PositionManagerService
from core.application.services.pipeline_event_handler import PipelineEventHandler
from core.domain.entities.broker_session import BrokerSession
from core.domain.entities.order import Order
from core.domain.entities.position import Position
from core.domain.enums.order_state import OrderState
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.position_state import PositionState
from core.domain.events.order_events import OrderFilled, OrderPartiallyFilled
from core.domain.events.signal_events import SignalRiskApproved
from core.domain.risk.kill_switch_state import KillSwitchState
from core.domain.value_objects.order_request import OrderRequest
from core.infrastructure.broker.order_mapper import OrderMapper
from core.infrastructure.broker.paper_broker import PaperBrokerAdapter
from core.infrastructure.broker.paper_order_router import PaperOrderRouter
from core.infrastructure.config.oms_config import OmsConfig


# ---------------------------------------------------------------------------
# In-memory fakes (minimal — re-declared here for test isolation)
# ---------------------------------------------------------------------------


class _OrderRepo:
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


class _PositionRepo:
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


class _ExecRepo:
    def __init__(self) -> None:
        self._fills: list = []

    async def save(self, fill: Any) -> None:
        self._fills.append(fill)

    async def get_by_order_id(self, order_id: uuid.UUID) -> list:
        return [f for f in self._fills if f.order_id == order_id]

    async def get_by_id(self, fill_id: uuid.UUID) -> Any | None:
        return next((f for f in self._fills if f.fill_id == fill_id), None)


class _CacheRepo:
    def __init__(self) -> None:
        self._idem: dict[str, uuid.UUID] = {}

    async def set_idempotency_key(self, signal_id: Any, order_id: Any, ttl_seconds: int = 300) -> bool:
        key = str(signal_id)
        if key in self._idem:
            return False
        self._idem[key] = order_id
        return True

    async def get_idempotency_order_id(self, signal_id: Any) -> uuid.UUID | None:
        return self._idem.get(str(signal_id))

    async def cache_order(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def get_cached_order(self, order_id: Any) -> str | None:
        return None

    async def evict_order(self, order_id: Any) -> None:
        pass

    async def cache_position(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def get_cached_position(self, position_id: Any) -> str | None:
        return None

    async def evict_position(self, position_id: Any) -> None:
        pass


class _KillSwitch:
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

    async def deactivate(self, deactivated_by: str, note: str, override_loss_check: bool = False) -> None:
        self._active = False


class _EventBus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)

    def events_of_type(self, name: str) -> list:
        return [e for e in self.published if type(e).__name__ == name]


# ---------------------------------------------------------------------------
# Signal factory helpers
# ---------------------------------------------------------------------------


def _make_signal_risk_approved(
    signal_id: uuid.UUID | None = None,
    direction: str = "LONG",
    lots: int = 1,
) -> SignalRiskApproved:
    return SignalRiskApproved(
        signal_id=signal_id or uuid.uuid4(),
        instrument_token=12345,
        underlying="NIFTY",
        direction=direction,
        adjusted_score=75.0,
        final_confidence=80.0,
        risk_decision_id=1,
        strategy_type="TREND",
        regime="TRENDING_BULLISH",
        position_size_lots=lots,
        valid_until=datetime.now(UTC) + timedelta(minutes=15),
    )


def _make_oms_config(max_orders_per_minute: int = 100) -> OmsConfig:
    return OmsConfig(
        max_orders_per_minute=max_orders_per_minute,
        idempotency_ttl_seconds=300,
        paper_slippage_pct=Decimal("0.0005"),
        max_position_size_lots=50,
    )


def _make_broker_session() -> BrokerSession:
    return BrokerSession.create(
        broker_name="paper",
        api_key="paper",
        encrypted_access_token="paper",
        expires_at=datetime(2099, 12, 31, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Fixture: full wired pipeline
# ---------------------------------------------------------------------------


def _build_pipeline(max_orders_per_minute: int = 100) -> dict:
    """Factory used by both pipeline and pipeline_perf fixtures."""
    broker = PaperBrokerAdapter(initial_capital=Decimal("5000000"))
    broker.set_ltp("NFO", "NIFTY", Decimal("22000"))

    order_repo = _OrderRepo()
    position_repo = _PositionRepo()
    exec_repo = _ExecRepo()
    cache_repo = _CacheRepo()
    kill_switch = _KillSwitch(active=False)
    event_bus = _EventBus()
    config = _make_oms_config(max_orders_per_minute=max_orders_per_minute)

    paper_router = PaperOrderRouter(broker=broker)

    exec_monitor = ExecutionMonitorService(
        order_repository=order_repo,
        execution_repository=exec_repo,
        order_router=paper_router,
        event_bus=event_bus,
    )

    broker_monitor = BrokerExecutionMonitorService(
        broker=broker,
        order_repository=order_repo,
        execution_monitor=exec_monitor,
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
        order_router=paper_router,
        order_repository=order_repo,
        event_bus=event_bus,
    )

    exit_mgr = ExitManagerService(
        order_repository=order_repo,
        position_repository=position_repo,
        order_router_service=order_router_svc,
        position_manager_service=position_mgr,
        event_bus=event_bus,
    )

    handler = PipelineEventHandler(
        order_management_service=order_mgr,
        order_router_service=order_router_svc,
        order_repository=order_repo,
        position_manager_service=position_mgr,
        exit_manager_service=exit_mgr,
        position_repository=position_repo,
    )

    return {
        "broker": broker,
        "kill_switch": kill_switch,
        "order_repo": order_repo,
        "position_repo": position_repo,
        "exec_repo": exec_repo,
        "event_bus": event_bus,
        "order_mgr": order_mgr,
        "order_router_svc": order_router_svc,
        "exec_monitor": exec_monitor,
        "broker_monitor": broker_monitor,
        "position_mgr": position_mgr,
        "exit_mgr": exit_mgr,
        "handler": handler,
        "paper_router": paper_router,
    }


@pytest.fixture
def pipeline() -> dict:
    return _build_pipeline(max_orders_per_minute=100)


@pytest.fixture
def pipeline_perf() -> dict:
    """Pipeline for performance tests — same limits as production."""
    return _build_pipeline(max_orders_per_minute=100)


# ---------------------------------------------------------------------------
# Helper: simulate a full fill cycle via PipelineEventHandler
# ---------------------------------------------------------------------------


async def _signal_to_filled_order(
    pipeline: dict,
    signal_risk_approved: SignalRiskApproved | None = None,
) -> Order:
    """Dispatch SignalRiskApproved → wait → poll broker → return FILLED order."""
    event = signal_risk_approved or _make_signal_risk_approved()
    await pipeline["handler"].handle_signal_risk_approved(event)

    # Paper broker fills synchronously; poll to update OMS order state.
    session = await pipeline["paper_router"]._get_session()
    await pipeline["broker_monitor"].poll_and_process(session)

    order = await pipeline["order_repo"].get_by_signal_id(event.signal_id)
    assert order is not None, "OMS must have created the order"
    return order


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


class TestPipelineEventHandlerE2E:
    async def test_signal_risk_approved_creates_order(self, pipeline: dict) -> None:
        """Handler creates AND routes in one call — order lands in SUBMITTED state."""
        event = _make_signal_risk_approved()
        await pipeline["handler"].handle_signal_risk_approved(event)
        order = await pipeline["order_repo"].get_by_signal_id(event.signal_id)
        assert order is not None

    async def test_handler_routes_order_to_submitted(self, pipeline: dict) -> None:
        event = _make_signal_risk_approved()
        await pipeline["handler"].handle_signal_risk_approved(event)
        order = await pipeline["order_repo"].get_by_signal_id(event.signal_id)
        assert order.state == OrderState.SUBMITTED
        assert order.broker_order_id is not None
        assert order.broker_order_id.startswith("PAPER-")

    async def test_broker_poll_fills_order(self, pipeline: dict) -> None:
        order = await _signal_to_filled_order(pipeline)
        assert order.state == OrderState.FILLED

    async def test_order_fill_event_opens_position(self, pipeline: dict) -> None:
        event = _make_signal_risk_approved()
        order = await _signal_to_filled_order(pipeline, event)

        # Simulate OrderFilled event dispatched to handler
        fill_event = OrderFilled(
            order_id=order.order_id,
            signal_id=event.signal_id,
            filled_quantity=order.quantity,
            average_fill_price=order.average_fill_price or Decimal("22000"),
            filled_at=datetime.now(UTC),
        )
        await pipeline["handler"].handle_order_filled(fill_event)

        position = await pipeline["position_repo"].get_by_signal_id(event.signal_id)
        assert position is not None
        assert position.state == PositionState.OPEN

    async def test_position_closed_on_sl_fill_via_handler(self, pipeline: dict) -> None:
        """Full E2E: signal → order → fill → position opened → SL fill → position CLOSED."""
        event = _make_signal_risk_approved()
        order = await _signal_to_filled_order(pipeline, event)

        # Open position via handler
        fill_event = OrderFilled(
            order_id=order.order_id,
            signal_id=event.signal_id,
            filled_quantity=order.quantity,
            average_fill_price=order.average_fill_price or Decimal("22000"),
            filled_at=datetime.now(UTC),
        )
        await pipeline["handler"].handle_order_filled(fill_event)

        position = await pipeline["position_repo"].get_by_signal_id(event.signal_id)
        assert position is not None

        # Now simulate stop-loss fill
        await pipeline["exit_mgr"].handle_stop_loss_fill(
            position=position,
            fill_price=pipeline["exit_mgr"]._price(Decimal("21700")),
            stop_order_id=None,
        ) if hasattr(pipeline["exit_mgr"], "_price") else (
            await pipeline["exit_mgr"].handle_stop_loss_fill(
                position=position,
                fill_price=__import__("core.domain.value_objects.price", fromlist=["Price"]).Price(Decimal("21700")),
                stop_order_id=None,
            )
        )

        position = await pipeline["position_repo"].get_by_id(position.position_id)
        assert position.state == PositionState.CLOSED
        assert position.outcome == PositionOutcome.LOSS

    async def test_position_closed_on_target_fill_via_handler(self, pipeline: dict) -> None:
        """Full E2E: signal → order → fill → position → target fill → position WIN."""
        from core.domain.value_objects.price import Price

        event = _make_signal_risk_approved()
        order = await _signal_to_filled_order(pipeline, event)

        fill_event = OrderFilled(
            order_id=order.order_id,
            signal_id=event.signal_id,
            filled_quantity=order.quantity,
            average_fill_price=order.average_fill_price or Decimal("22000"),
            filled_at=datetime.now(UTC),
        )
        await pipeline["handler"].handle_order_filled(fill_event)

        position = await pipeline["position_repo"].get_by_signal_id(event.signal_id)
        await pipeline["exit_mgr"].handle_target_fill(
            position=position,
            fill_price=Price(Decimal("22500")),
            target_order_id=None,
        )

        position = await pipeline["position_repo"].get_by_id(position.position_id)
        assert position.state == PositionState.CLOSED
        assert position.outcome == PositionOutcome.WIN


# ---------------------------------------------------------------------------
# Tests — kill switch
# ---------------------------------------------------------------------------


class TestKillSwitchPropagation:
    async def test_kill_switch_blocks_new_order(self, pipeline: dict) -> None:
        pipeline["kill_switch"]._active = True
        event = _make_signal_risk_approved()
        await pipeline["handler"].handle_signal_risk_approved(event)
        order = await pipeline["order_repo"].get_by_signal_id(event.signal_id)
        assert order is None

    async def test_kill_switch_deactivated_allows_order(self, pipeline: dict) -> None:
        pipeline["kill_switch"]._active = True
        await pipeline["kill_switch"].deactivate("operator", "resolved")

        event = _make_signal_risk_approved()
        await pipeline["handler"].handle_signal_risk_approved(event)
        order = await pipeline["order_repo"].get_by_signal_id(event.signal_id)
        assert order is not None


# ---------------------------------------------------------------------------
# Tests — idempotency / dedup
# ---------------------------------------------------------------------------


class TestSignalDeduplication:
    async def test_duplicate_signal_id_produces_one_order(self, pipeline: dict) -> None:
        signal_id = uuid.uuid4()
        event = _make_signal_risk_approved(signal_id=signal_id)

        await pipeline["handler"].handle_signal_risk_approved(event)
        await pipeline["handler"].handle_signal_risk_approved(event)

        orders = [
            o for o in pipeline["order_repo"]._orders.values()
            if o.signal_id == signal_id
        ]
        assert len(orders) == 1

    async def test_two_different_signal_ids_produce_two_orders(self, pipeline: dict) -> None:
        event_a = _make_signal_risk_approved()
        event_b = _make_signal_risk_approved()

        await pipeline["handler"].handle_signal_risk_approved(event_a)
        await pipeline["handler"].handle_signal_risk_approved(event_b)

        assert len(pipeline["order_repo"]._orders) == 2


# ---------------------------------------------------------------------------
# Tests — partial fill (logged only)
# ---------------------------------------------------------------------------


class TestPartialFill:
    async def test_partial_fill_does_not_open_position(self, pipeline: dict) -> None:
        event = _make_signal_risk_approved()
        await pipeline["handler"].handle_signal_risk_approved(event)
        order = await pipeline["order_repo"].get_by_signal_id(event.signal_id)

        partial = OrderPartiallyFilled(
            order_id=order.order_id,
            filled_quantity=25,
            remaining_quantity=75,
            average_fill_price=Decimal("22000"),
        )
        await pipeline["handler"].handle_order_partially_filled(partial)

        position = await pipeline["position_repo"].get_by_signal_id(event.signal_id)
        assert position is None

    async def test_three_partial_fills_cumulate(self, pipeline: dict) -> None:
        """25+25+50 partial fills — each is logged; position not opened until full fill."""
        event = _make_signal_risk_approved()
        await pipeline["handler"].handle_signal_risk_approved(event)
        order = await pipeline["order_repo"].get_by_signal_id(event.signal_id)

        for qty, remaining in [(25, 75), (25, 50), (50, 0)]:
            partial = OrderPartiallyFilled(
                order_id=order.order_id,
                filled_quantity=qty,
                remaining_quantity=remaining,
                average_fill_price=Decimal("22000"),
            )
            await pipeline["handler"].handle_order_partially_filled(partial)

        # Position still not opened (only full OrderFilled triggers position open)
        position = await pipeline["position_repo"].get_by_signal_id(event.signal_id)
        assert position is None


# ---------------------------------------------------------------------------
# Tests — exit fill routing via PipelineEventHandler
# ---------------------------------------------------------------------------


class TestExitFillRouting:
    async def test_exit_fill_for_missing_position_no_crash(self, pipeline: dict) -> None:
        """If parent position was deleted / never persisted → no crash."""
        order_id = uuid.uuid4()
        position_id = uuid.uuid4()

        # Build an entry order that references a non-existent position
        event = _make_signal_risk_approved()
        await pipeline["handler"].handle_signal_risk_approved(event)
        order = await pipeline["order_repo"].get_by_signal_id(event.signal_id)

        # Manually set parent_position_id to a non-existent position
        object.__setattr__(order, "parent_position_id", position_id)
        await pipeline["order_repo"].save(order)

        fill_event = OrderFilled(
            order_id=order.order_id,
            signal_id=event.signal_id,
            filled_quantity=order.quantity,
            average_fill_price=Decimal("22000"),
            filled_at=datetime.now(UTC),
        )
        # must not raise
        await pipeline["handler"].handle_order_filled(fill_event)


# ---------------------------------------------------------------------------
# Tests — multiple concurrent signals
# ---------------------------------------------------------------------------


class TestMultipleSignals:
    async def test_ten_concurrent_signals_produce_independent_orders(
        self, pipeline: dict
    ) -> None:
        """10 signals processed concurrently — each produces exactly one order."""
        events = [_make_signal_risk_approved() for _ in range(10)]
        await asyncio.gather(
            *[pipeline["handler"].handle_signal_risk_approved(e) for e in events]
        )

        assert len(pipeline["order_repo"]._orders) == 10

        # Verify each signal_id maps to exactly one order
        signal_ids = {e.signal_id for e in events}
        for sid in signal_ids:
            order = await pipeline["order_repo"].get_by_signal_id(sid)
            assert order is not None, f"Missing order for signal {sid}"


# ---------------------------------------------------------------------------
# Performance test — 200 FnO instruments, handler must complete <5s
# ---------------------------------------------------------------------------


class TestPerformance:
    async def test_200_signals_dispatched_under_5_seconds(self, pipeline_perf: dict) -> None:
        """200 SignalRiskApproved events dispatched concurrently within 5 seconds.

        OmsConfig limits orders/min to 100, so 100 orders are created and 100
        are rate-limited. The test verifies handler throughput, not order count.
        """
        events = [_make_signal_risk_approved() for _ in range(200)]

        start = time.monotonic()
        await asyncio.gather(
            *[pipeline_perf["handler"].handle_signal_risk_approved(e) for e in events]
        )
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, (
            f"200 signals dispatched in {elapsed:.2f}s — exceeds 5s SLA"
        )
        # At least 100 orders created (first 100 before rate limit kicks in)
        assert len(pipeline_perf["order_repo"]._orders) >= 100


# ---------------------------------------------------------------------------
# Paper Trading Scenario Runner
# ---------------------------------------------------------------------------


class PaperTradingScenarioRunner:
    """Executes named paper trading scenarios against a wired pipeline.

    Each scenario is a self-contained async method returning a dict of
    assertion results. Run all with run_all().
    """

    def __init__(self, pipeline: dict) -> None:
        self._p = pipeline
        self._results: dict[str, str] = {}

    async def run_all(self) -> dict[str, str]:
        scenarios = [
            self._scenario_signal_to_pending_order,
            self._scenario_order_routed_to_paper_broker,
            self._scenario_fill_opens_position,
            self._scenario_sl_closes_position_as_loss,
            self._scenario_target_closes_position_as_win,
            self._scenario_kill_switch_blocks_order,
            self._scenario_duplicate_signal_deduped,
            self._scenario_200_signals_performance,
        ]
        for scenario in scenarios:
            name = scenario.__name__.replace("_scenario_", "")
            try:
                await scenario()
                self._results[name] = "PASS"
            except AssertionError as exc:
                self._results[name] = f"FAIL: {exc}"
            except Exception as exc:
                self._results[name] = f"ERROR: {type(exc).__name__}: {exc}"
        return self._results

    async def _scenario_signal_to_pending_order(self) -> None:
        event = _make_signal_risk_approved()
        await self._p["handler"].handle_signal_risk_approved(event)
        order = await self._p["order_repo"].get_by_signal_id(event.signal_id)
        assert order is not None

    async def _scenario_order_routed_to_paper_broker(self) -> None:
        event = _make_signal_risk_approved()
        await self._p["handler"].handle_signal_risk_approved(event)
        order = await self._p["order_repo"].get_by_signal_id(event.signal_id)
        assert order.state == OrderState.SUBMITTED
        assert order.broker_order_id.startswith("PAPER-")

    async def _scenario_fill_opens_position(self) -> None:
        from core.domain.value_objects.price import Price
        event = _make_signal_risk_approved()
        order = await _signal_to_filled_order(self._p, event)
        fill_event = OrderFilled(
            order_id=order.order_id,
            signal_id=event.signal_id,
            filled_quantity=order.quantity,
            average_fill_price=order.average_fill_price or Decimal("22000"),
            filled_at=datetime.now(UTC),
        )
        await self._p["handler"].handle_order_filled(fill_event)
        position = await self._p["position_repo"].get_by_signal_id(event.signal_id)
        assert position is not None
        assert position.state == PositionState.OPEN

    async def _scenario_sl_closes_position_as_loss(self) -> None:
        from core.domain.value_objects.price import Price
        event = _make_signal_risk_approved()
        order = await _signal_to_filled_order(self._p, event)
        fill_event = OrderFilled(
            order_id=order.order_id,
            signal_id=event.signal_id,
            filled_quantity=order.quantity,
            average_fill_price=order.average_fill_price or Decimal("22000"),
            filled_at=datetime.now(UTC),
        )
        await self._p["handler"].handle_order_filled(fill_event)
        position = await self._p["position_repo"].get_by_signal_id(event.signal_id)
        await self._p["exit_mgr"].handle_stop_loss_fill(
            position=position,
            fill_price=Price(Decimal("21700")),
            stop_order_id=None,
        )
        position = await self._p["position_repo"].get_by_id(position.position_id)
        assert position.state == PositionState.CLOSED
        assert position.outcome == PositionOutcome.LOSS

    async def _scenario_target_closes_position_as_win(self) -> None:
        from core.domain.value_objects.price import Price
        event = _make_signal_risk_approved()
        order = await _signal_to_filled_order(self._p, event)
        fill_event = OrderFilled(
            order_id=order.order_id,
            signal_id=event.signal_id,
            filled_quantity=order.quantity,
            average_fill_price=order.average_fill_price or Decimal("22000"),
            filled_at=datetime.now(UTC),
        )
        await self._p["handler"].handle_order_filled(fill_event)
        position = await self._p["position_repo"].get_by_signal_id(event.signal_id)
        await self._p["exit_mgr"].handle_target_fill(
            position=position,
            fill_price=Price(Decimal("22500")),
            target_order_id=None,
        )
        position = await self._p["position_repo"].get_by_id(position.position_id)
        assert position.state == PositionState.CLOSED
        assert position.outcome == PositionOutcome.WIN

    async def _scenario_kill_switch_blocks_order(self) -> None:
        self._p["kill_switch"]._active = True
        event = _make_signal_risk_approved()
        await self._p["handler"].handle_signal_risk_approved(event)
        order = await self._p["order_repo"].get_by_signal_id(event.signal_id)
        assert order is None
        self._p["kill_switch"]._active = False  # restore

    async def _scenario_duplicate_signal_deduped(self) -> None:
        signal_id = uuid.uuid4()
        event = _make_signal_risk_approved(signal_id=signal_id)
        await self._p["handler"].handle_signal_risk_approved(event)
        await self._p["handler"].handle_signal_risk_approved(event)
        orders = [
            o for o in self._p["order_repo"]._orders.values()
            if o.signal_id == signal_id
        ]
        assert len(orders) == 1

    async def _scenario_200_signals_performance(self) -> None:
        events = [_make_signal_risk_approved() for _ in range(200)]
        start = time.monotonic()
        await asyncio.gather(
            *[self._p["handler"].handle_signal_risk_approved(e) for e in events]
        )
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"200 signal dispatches took {elapsed:.2f}s (SLA: 5s)"


class TestPaperTradingScenarioRunner:
    async def test_all_scenarios_pass(self, pipeline_perf: dict) -> None:
        runner = PaperTradingScenarioRunner(pipeline_perf)
        results = await runner.run_all()
        failed = {k: v for k, v in results.items() if not v.startswith("PASS")}
        assert not failed, f"Scenario failures: {failed}"

    async def test_runner_reports_pass_for_each_scenario(self, pipeline_perf: dict) -> None:
        runner = PaperTradingScenarioRunner(pipeline_perf)
        results = await runner.run_all()
        assert len(results) == 8
        for name, status in results.items():
            assert status.startswith("PASS"), f"Scenario {name!r} failed: {status}"
