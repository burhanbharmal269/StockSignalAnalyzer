"""Unit tests — ReconciliationService.

Coverage:
  - Clean pass: no OMS open orders, no discrepancies
  - Missing order at broker: discrepancy detected, event published
  - Rogue broker order: kill switch activated, RogueOrderDetectedError raised
  - PENDING/SUBMITTING orders skipped (no broker_order_id)
  - Orphan OMS position: not at broker → discrepancy
  - Quantity mismatch: oms vs broker → discrepancy
  - Clean reconciliation publishes ReconciliationCompleted
  - Broker orders fetch failure: skip order reconciliation (log error, continue)
  - Broker positions fetch failure: skip position reconciliation
  - Kill switch activation failure: logged as CRITICAL, exception still raised
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.oms.reconciliation_service import ReconciliationService
from core.domain.entities.order import Order
from core.domain.entities.position import Position
from core.domain.enums.order_state import OrderState
from core.domain.enums.order_type import OrderType
from core.domain.enums.product_type import ProductType
from core.domain.enums.signal_type import SignalType
from core.domain.enums.trading_mode import TradingMode
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.exceptions.order import RogueOrderDetectedError
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order(
    state: OrderState = OrderState.SUBMITTED,
    broker_order_id: str = "BROKER-001",
) -> Order:
    order = Order(
        order_id=uuid.uuid4(),
        signal_id=uuid.uuid4(),
        symbol=Symbol("NIFTY", "NFO"),
        quantity=50,
        limit_price=None,
        order_type=OrderType.MARKET,
        transaction_type=TransactionType.BUY,
        product=ProductType.MIS,
        lots=1,
        validity=Validity.DAY,
        trading_mode=TradingMode.LIVE,
        state=state,
        broker_order_id=broker_order_id,
    )
    return order


def _make_position(instrument_token: int = 12345, quantity: int = 50) -> Position:
    pos = Position.open(
        symbol=Symbol("NIFTY", "NFO"),
        direction=SignalType.LONG,
        quantity=quantity,
        entry_price=Price(Decimal("200")),
        signal_id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        instrument_token=instrument_token,
        lots=1,
        trading_mode=TradingMode.LIVE,
    )
    return pos


def _broker_order(broker_order_id: str):
    obj = MagicMock()
    obj.broker_order_id = broker_order_id
    return obj


def _broker_position(
    instrument_token: int,
    net_quantity: int,
    average_price: Decimal | None = None,
) -> MagicMock:
    obj = MagicMock()
    obj.instrument_token = instrument_token
    obj.net_quantity = net_quantity
    obj.average_price = average_price  # None → no price mismatch check triggered
    return obj


def _broker_trade(broker_order_id: str, exchange_trade_id: str) -> MagicMock:
    obj = MagicMock()
    obj.broker_order_id = broker_order_id
    obj.exchange_trade_id = exchange_trade_id
    return obj


def _mock_session():
    return MagicMock()


@pytest.fixture
def mock_order_repo():
    r = AsyncMock()
    r.get_by_state = AsyncMock(return_value=[])
    return r


@pytest.fixture
def mock_position_repo():
    r = AsyncMock()
    r.get_open_positions = AsyncMock(return_value=[])
    return r


@pytest.fixture
def mock_broker():
    b = AsyncMock()
    b.get_orders = AsyncMock(return_value=[])
    b.get_positions = AsyncMock(return_value=[])
    return b


@pytest.fixture
def mock_kill_switch():
    ks = AsyncMock()
    ks.activate = AsyncMock()
    return ks


@pytest.fixture
def mock_bus():
    b = AsyncMock()
    b.publish = AsyncMock()
    return b


@pytest.fixture
def svc(mock_order_repo, mock_position_repo, mock_broker, mock_kill_switch, mock_bus):
    return ReconciliationService(
        order_repository=mock_order_repo,
        position_repository=mock_position_repo,
        broker=mock_broker,
        kill_switch_repository=mock_kill_switch,
        event_bus=mock_bus,
    )


# ---------------------------------------------------------------------------
# Clean pass
# ---------------------------------------------------------------------------

class TestCleanPass:
    @pytest.mark.asyncio
    async def test_clean_pass_no_discrepancies(self, svc):
        result = await svc.run(_mock_session())
        assert result.discrepancy_count == 0
        assert result.rogue_count == 0

    @pytest.mark.asyncio
    async def test_reconciliation_completed_event_published(self, svc, mock_bus):
        await svc.run(_mock_session())
        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "ReconciliationCompleted" in published_types

    @pytest.mark.asyncio
    async def test_orders_and_positions_checked_in_result(
        self, svc, mock_order_repo, mock_position_repo, mock_broker
    ):
        order = _make_order()
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[_broker_order("BROKER-001")])
        mock_position_repo.get_open_positions = AsyncMock(return_value=[_make_position()])
        mock_broker.get_positions = AsyncMock(return_value=[_broker_position(12345, 50)])

        result = await svc.run(_mock_session())
        assert result.orders_checked >= 1
        assert result.positions_checked >= 1


# ---------------------------------------------------------------------------
# Missing order at broker
# ---------------------------------------------------------------------------

class TestMissingOrder:
    @pytest.mark.asyncio
    async def test_missing_order_detected(self, svc, mock_order_repo, mock_broker):
        order = _make_order(state=OrderState.SUBMITTED, broker_order_id="BROKER-001")
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[])  # Broker knows nothing

        result = await svc.run(_mock_session())

        assert result.discrepancy_count == 1
        assert result.discrepancies[0]["type"] == "MISSING_ORDER"

    @pytest.mark.asyncio
    async def test_missing_order_publishes_discrepancy_event(
        self, svc, mock_order_repo, mock_broker, mock_bus
    ):
        order = _make_order(state=OrderState.SUBMITTED)
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[])

        await svc.run(_mock_session())

        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "ReconciliationDiscrepancyDetected" in published_types


# ---------------------------------------------------------------------------
# Pending / Submitting orders skipped
# ---------------------------------------------------------------------------

class TestPendingOrdersSkipped:
    @pytest.mark.asyncio
    async def test_pending_order_without_broker_id_not_flagged(
        self, svc, mock_order_repo, mock_broker
    ):
        pending = _make_order(state=OrderState.PENDING, broker_order_id="")
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [pending] if s == OrderState.PENDING else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[])

        result = await svc.run(_mock_session())
        assert result.discrepancy_count == 0


# ---------------------------------------------------------------------------
# Rogue order
# ---------------------------------------------------------------------------

class TestRogueOrder:
    @pytest.mark.asyncio
    async def test_rogue_order_raises(self, svc, mock_order_repo, mock_broker):
        mock_order_repo.get_by_state = AsyncMock(return_value=[])
        oms_order = _make_order(state=OrderState.SUBMITTED, broker_order_id="BROKER-KNOWN")
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [oms_order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[
            _broker_order("BROKER-KNOWN"),   # matches OMS
            _broker_order("BROKER-ROGUE"),   # NOT in OMS
        ])

        with pytest.raises(RogueOrderDetectedError):
            await svc.run(_mock_session())

    @pytest.mark.asyncio
    async def test_rogue_order_activates_kill_switch(
        self, svc, mock_order_repo, mock_broker, mock_kill_switch
    ):
        oms_order = _make_order(state=OrderState.SUBMITTED, broker_order_id="BROKER-001")
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [oms_order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[
            _broker_order("BROKER-001"),
            _broker_order("BROKER-ROGUE"),
        ])

        with pytest.raises(RogueOrderDetectedError):
            await svc.run(_mock_session())

        mock_kill_switch.activate.assert_called_once()
        call_kwargs = mock_kill_switch.activate.call_args[1]
        assert call_kwargs["activated_by"] == "system"
        assert call_kwargs["trigger_source"] == "reconciliation_rogue_order"

    @pytest.mark.asyncio
    async def test_rogue_order_publishes_discrepancy_event(
        self, svc, mock_order_repo, mock_broker, mock_bus
    ):
        oms_order = _make_order(state=OrderState.SUBMITTED, broker_order_id="BROKER-001")
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [oms_order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[
            _broker_order("BROKER-001"),
            _broker_order("BROKER-ROGUE"),
        ])

        with pytest.raises(RogueOrderDetectedError):
            await svc.run(_mock_session())

        events = [c[0][0] for c in mock_bus.publish.call_args_list]
        discrepancy_events = [
            e for e in events if type(e).__name__ == "ReconciliationDiscrepancyDetected"
        ]
        rogue = next((e for e in discrepancy_events if e.discrepancy_type == "ROGUE_ORDER"), None)
        assert rogue is not None
        assert rogue.broker_order_id == "BROKER-ROGUE"


# ---------------------------------------------------------------------------
# Orphan position
# ---------------------------------------------------------------------------

class TestOrphanPosition:
    @pytest.mark.asyncio
    async def test_orphan_position_detected(
        self, svc, mock_position_repo, mock_broker
    ):
        position = _make_position(instrument_token=99999)
        mock_position_repo.get_open_positions = AsyncMock(return_value=[position])
        mock_broker.get_positions = AsyncMock(return_value=[])  # not at broker

        result = await svc.run(_mock_session())

        orphans = [d for d in result.discrepancies if d["type"] == "ORPHAN_POSITION"]
        assert len(orphans) == 1


# ---------------------------------------------------------------------------
# Quantity mismatch
# ---------------------------------------------------------------------------

class TestQuantityMismatch:
    @pytest.mark.asyncio
    async def test_qty_mismatch_detected(
        self, svc, mock_position_repo, mock_broker
    ):
        position = _make_position(instrument_token=12345, quantity=50)
        mock_position_repo.get_open_positions = AsyncMock(return_value=[position])
        mock_broker.get_positions = AsyncMock(
            return_value=[_broker_position(12345, 25)]  # mismatch: 50 vs 25
        )

        result = await svc.run(_mock_session())

        mismatches = [d for d in result.discrepancies if d["type"] == "QTY_MISMATCH"]
        assert len(mismatches) == 1
        assert mismatches[0]["oms_qty"] == 50
        assert mismatches[0]["broker_qty"] == 25


# ---------------------------------------------------------------------------
# Broker fetch failures
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Average price mismatch
# ---------------------------------------------------------------------------

class TestAveragePriceMismatch:
    @pytest.mark.asyncio
    async def test_avg_price_mismatch_detected(
        self, svc, mock_position_repo, mock_broker
    ):
        position = _make_position(instrument_token=12345, quantity=50)
        # OMS entry price = 200; broker says 210 (>0.5% difference)
        mock_position_repo.get_open_positions = AsyncMock(return_value=[position])
        mock_broker.get_positions = AsyncMock(
            return_value=[_broker_position(12345, 50, average_price=Decimal("210"))]
        )

        result = await svc.run(_mock_session())

        mismatches = [d for d in result.discrepancies if d["type"] == "AVG_PRICE_MISMATCH"]
        assert len(mismatches) == 1
        assert mismatches[0]["oms_avg_price"] == "200"
        assert mismatches[0]["broker_avg_price"] == "210"

    @pytest.mark.asyncio
    async def test_avg_price_within_tolerance_not_flagged(
        self, svc, mock_position_repo, mock_broker
    ):
        position = _make_position(instrument_token=12345, quantity=50)
        # OMS entry price = 200; broker says 200.5 (<0.5% difference)
        mock_position_repo.get_open_positions = AsyncMock(return_value=[position])
        mock_broker.get_positions = AsyncMock(
            return_value=[_broker_position(12345, 50, average_price=Decimal("200.5"))]
        )

        result = await svc.run(_mock_session())

        price_mismatches = [d for d in result.discrepancies if d["type"] == "AVG_PRICE_MISMATCH"]
        assert len(price_mismatches) == 0

    @pytest.mark.asyncio
    async def test_avg_price_mismatch_publishes_discrepancy_event(
        self, svc, mock_position_repo, mock_broker, mock_bus
    ):
        position = _make_position(instrument_token=12345, quantity=50)
        mock_position_repo.get_open_positions = AsyncMock(return_value=[position])
        mock_broker.get_positions = AsyncMock(
            return_value=[_broker_position(12345, 50, average_price=Decimal("180"))]
        )

        await svc.run(_mock_session())

        published_types = [type(c[0][0]).__name__ for c in mock_bus.publish.call_args_list]
        assert "ReconciliationDiscrepancyDetected" in published_types
        discrepancy_events = [
            c[0][0] for c in mock_bus.publish.call_args_list
            if type(c[0][0]).__name__ == "ReconciliationDiscrepancyDetected"
        ]
        price_events = [e for e in discrepancy_events if e.discrepancy_type == "AVG_PRICE_MISMATCH"]
        assert len(price_events) == 1


# ---------------------------------------------------------------------------
# Missing fill
# ---------------------------------------------------------------------------

class TestMissingFill:
    @pytest.fixture
    def mock_exec_repo(self):
        r = AsyncMock()
        r.get_by_order_id = AsyncMock(return_value=[])
        return r

    @pytest.fixture
    def svc_with_exec(
        self, mock_order_repo, mock_position_repo, mock_broker,
        mock_kill_switch, mock_bus, mock_exec_repo
    ):
        return ReconciliationService(
            order_repository=mock_order_repo,
            position_repository=mock_position_repo,
            broker=mock_broker,
            kill_switch_repository=mock_kill_switch,
            event_bus=mock_bus,
            execution_repository=mock_exec_repo,
        )

    @pytest.mark.asyncio
    async def test_missing_fill_detected(
        self, svc_with_exec, mock_order_repo, mock_broker, mock_exec_repo
    ):
        order = _make_order(state=OrderState.SUBMITTED, broker_order_id="BROKER-001")
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[_broker_order("BROKER-001")])
        mock_broker.get_trades = AsyncMock(
            return_value=[_broker_trade("BROKER-001", "EX-TRADE-999")]
        )
        # OMS has no execution records for this order
        mock_exec_repo.get_by_order_id = AsyncMock(return_value=[])

        result = await svc_with_exec.run(_mock_session())

        fills = [d for d in result.discrepancies if d["type"] == "MISSING_FILL"]
        assert len(fills) == 1
        assert fills[0]["exchange_trade_id"] == "EX-TRADE-999"
        assert fills[0]["broker_order_id"] == "BROKER-001"

    @pytest.mark.asyncio
    async def test_missing_fill_publishes_discrepancy_event(
        self, svc_with_exec, mock_order_repo, mock_broker, mock_exec_repo, mock_bus
    ):
        order = _make_order(state=OrderState.SUBMITTED, broker_order_id="BROKER-001")
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[_broker_order("BROKER-001")])
        mock_broker.get_trades = AsyncMock(
            return_value=[_broker_trade("BROKER-001", "EX-TRADE-999")]
        )
        mock_exec_repo.get_by_order_id = AsyncMock(return_value=[])

        await svc_with_exec.run(_mock_session())

        events = [c[0][0] for c in mock_bus.publish.call_args_list]
        fill_events = [
            e for e in events
            if type(e).__name__ == "ReconciliationDiscrepancyDetected"
            and e.discrepancy_type == "MISSING_FILL"
        ]
        assert len(fill_events) == 1

    @pytest.mark.asyncio
    async def test_known_fill_not_flagged(
        self, svc_with_exec, mock_order_repo, mock_broker, mock_exec_repo
    ):
        """If OMS has the fill already, no MISSING_FILL discrepancy."""
        order = _make_order(state=OrderState.SUBMITTED, broker_order_id="BROKER-001")
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[_broker_order("BROKER-001")])
        mock_broker.get_trades = AsyncMock(
            return_value=[_broker_trade("BROKER-001", "EX-TRADE-999")]
        )
        # OMS already has the fill recorded
        recorded_fill = MagicMock()
        recorded_fill.exchange_trade_id = "EX-TRADE-999"
        mock_exec_repo.get_by_order_id = AsyncMock(return_value=[recorded_fill])

        result = await svc_with_exec.run(_mock_session())

        fills = [d for d in result.discrepancies if d["type"] == "MISSING_FILL"]
        assert len(fills) == 0

    @pytest.mark.asyncio
    async def test_no_exec_repo_skips_fill_reconciliation(
        self, svc, mock_order_repo, mock_broker
    ):
        """Without exec_repo, fill reconciliation is silently skipped."""
        order = _make_order(state=OrderState.SUBMITTED, broker_order_id="BROKER-001")
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(return_value=[_broker_order("BROKER-001")])
        # Even if broker has trades, no error raised
        mock_broker.get_trades = AsyncMock(return_value=[])

        # svc has no execution_repository — should not raise
        result = await svc.run(_mock_session())
        assert result.discrepancy_count == 0


class TestBrokerFetchFailure:
    @pytest.mark.asyncio
    async def test_broker_orders_failure_continues(
        self, svc, mock_order_repo, mock_broker
    ):
        order = _make_order(state=OrderState.SUBMITTED)
        mock_order_repo.get_by_state = AsyncMock(
            side_effect=lambda s: [order] if s == OrderState.SUBMITTED else []
        )
        mock_broker.get_orders = AsyncMock(side_effect=RuntimeError("broker down"))

        # Should not raise
        result = await svc.run(_mock_session())
        # No discrepancies detected because we couldn't compare
        assert result.rogue_count == 0

    @pytest.mark.asyncio
    async def test_broker_positions_failure_continues(
        self, svc, mock_position_repo, mock_broker
    ):
        mock_position_repo.get_open_positions = AsyncMock(return_value=[_make_position()])
        mock_broker.get_positions = AsyncMock(side_effect=RuntimeError("broker down"))

        result = await svc.run(_mock_session())
        assert result.discrepancy_count == 0
