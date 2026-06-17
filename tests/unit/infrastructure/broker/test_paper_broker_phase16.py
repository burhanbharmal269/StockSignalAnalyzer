"""Phase 16 tests for PaperBrokerAdapter — new methods and capabilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from core.domain.entities.broker_session import BrokerSession
from core.domain.exceptions.broker import BrokerOrderError, BrokerSessionExpiredError
from core.domain.value_objects.broker_dtos import BrokerOrderRequest
from core.domain.value_objects.broker_health import BrokerHealthStatus
from core.infrastructure.broker.paper_broker import PaperBrokerAdapter


def _make_session(expired: bool = False) -> BrokerSession:
    expires_at = (
        datetime.now(UTC) - timedelta(hours=1)
        if expired
        else datetime(2099, 12, 31, tzinfo=UTC)
    )
    return BrokerSession.create(
        broker_name="paper",
        api_key="test",
        encrypted_access_token="paper_mode",
        expires_at=expires_at,
    )


def _buy(qty: int = 50, symbol: str = "NIFTY", exchange: str = "NFO") -> BrokerOrderRequest:
    return BrokerOrderRequest(
        symbol=symbol,
        exchange=exchange,
        direction="BUY",
        quantity=qty,
        order_type="MARKET",
        product="INTRADAY",
        limit_price=None,
        trigger_price=None,
        tag="test",
    )


def _sell(qty: int = 50, symbol: str = "NIFTY", exchange: str = "NFO") -> BrokerOrderRequest:
    return BrokerOrderRequest(
        symbol=symbol,
        exchange=exchange,
        direction="SELL",
        quantity=qty,
        order_type="MARKET",
        product="INTRADAY",
        limit_price=None,
        trigger_price=None,
        tag="test",
    )


@pytest.fixture
def broker() -> PaperBrokerAdapter:
    b = PaperBrokerAdapter(initial_capital=Decimal("500000"))
    yield b
    b.reset()


@pytest.fixture
def session() -> BrokerSession:
    return _make_session()


class TestConnectDisconnect:
    async def test_connect_succeeds_valid_session(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        await broker.connect(session)  # should not raise

    async def test_connect_raises_expired_session(self, broker: PaperBrokerAdapter) -> None:
        expired = _make_session(expired=True)
        with pytest.raises(BrokerSessionExpiredError):
            await broker.connect(expired)

    async def test_disconnect_does_not_raise(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        await broker.disconnect(session)  # no-op, should not raise


class TestGetOrder:
    async def test_get_order_returns_placed_order(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        order_id = await broker.place_order(session, _buy())
        result = await broker.get_order(session, order_id)
        assert result is not None
        assert result.broker_order_id == order_id
        assert result.status == "COMPLETE"

    async def test_get_order_returns_none_for_unknown(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        result = await broker.get_order(session, "PAPER-99999999")
        assert result is None

    async def test_get_order_cancelled_shows_cancelled_status(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        order_id = await broker.place_order(session, _buy())
        await broker.cancel_order(session, order_id)
        result = await broker.get_order(session, order_id)
        assert result is not None
        assert result.status == "CANCELLED"


class TestGetPosition:
    async def test_get_position_after_buy(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy(qty=50))
        pos = await broker.get_position(session, "NIFTY", "NFO")
        assert pos is not None
        assert pos.symbol == "NIFTY"
        assert pos.quantity == 50

    async def test_get_position_returns_none_when_no_position(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        pos = await broker.get_position(session, "BANKNIFTY", "NFO")
        assert pos is None

    async def test_get_position_returns_none_after_flat(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy(qty=50))
        await broker.place_order(session, _sell(qty=50))
        pos = await broker.get_position(session, "NIFTY", "NFO")
        assert pos is None

    async def test_get_position_net_quantity_positive_for_long(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy(qty=50))
        pos = await broker.get_position(session, "NIFTY", "NFO")
        assert pos is not None
        assert pos.net_quantity == 50


class TestGetMargin:
    async def test_initial_margin_full_capital_available(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        margin = await broker.get_margin(session)
        assert margin.available_cash == Decimal("500000")
        assert margin.used_margin == Decimal("0")
        assert margin.total_margin == Decimal("500000")

    async def test_margin_decreases_after_buy(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy(qty=50))  # 50 × 22000 × 0.2 = 220000 margin
        margin = await broker.get_margin(session)
        assert margin.used_margin > Decimal("0")
        assert margin.available_cash < Decimal("500000")

    async def test_margin_segment_is_equity(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        margin = await broker.get_margin(session)
        assert margin.segment == "equity"


class TestHealthCheck:
    async def test_health_check_returns_healthy(self, broker: PaperBrokerAdapter) -> None:
        report = await broker.health_check()
        assert report.status == BrokerHealthStatus.HEALTHY
        assert report.broker_name == "paper"
        assert report.latency_ms == 0.0

    async def test_health_check_no_session_required(self, broker: PaperBrokerAdapter) -> None:
        # health_check takes no session — should always work
        report = await broker.health_check()
        assert report is not None


class TestPositionNetQuantity:
    async def test_positions_include_net_quantity(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy(qty=75))
        positions = await broker.get_positions(session)
        assert len(positions) == 1
        assert positions[0].net_quantity == 75

    async def test_quantity_is_abs_of_net_quantity(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy(qty=50))
        positions = await broker.get_positions(session)
        pos = positions[0]
        assert pos.quantity == abs(pos.net_quantity)


class TestSimulatePartialFill:
    async def test_simulate_partial_fill_sets_filled_quantity(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        order_id = await broker.place_order(session, _buy(qty=100))
        broker.simulate_partial_fill(order_id, filled_qty=40)
        order = await broker.get_order(session, order_id)
        assert order is not None
        assert order.filled_quantity == 40
        assert order.status == "OPEN"

    async def test_simulate_partial_fill_complete_sets_complete(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        order_id = await broker.place_order(session, _buy(qty=100))
        broker.simulate_partial_fill(order_id, filled_qty=100)
        order = await broker.get_order(session, order_id)
        assert order is not None
        assert order.status == "COMPLETE"

    async def test_simulate_partial_fill_unknown_order_raises(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        with pytest.raises(BrokerOrderError):
            broker.simulate_partial_fill("PAPER-99999999", filled_qty=10)


class TestReset:
    async def test_reset_clears_used_margin(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy(qty=50))
        broker.reset()
        session2 = _make_session()
        margin = await broker.get_margin(session2)
        assert margin.used_margin == Decimal("0")
        assert margin.available_cash == Decimal("500000")
