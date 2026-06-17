"""Unit tests for PaperBrokerAdapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from core.domain.entities.broker_session import BrokerSession
from core.domain.exceptions.broker import BrokerOrderError, BrokerSessionExpiredError
from core.domain.value_objects.broker_dtos import BrokerOrderRequest
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


def _buy_request(
    symbol: str = "NIFTY",
    exchange: str = "NFO",
    quantity: int = 50,
    order_type: str = "MARKET",
    limit_price: Decimal | None = None,
) -> BrokerOrderRequest:
    return BrokerOrderRequest(
        symbol=symbol,
        exchange=exchange,
        direction="BUY",
        quantity=quantity,
        order_type=order_type,
        product="INTRADAY",
        limit_price=limit_price,
        trigger_price=None,
        tag="test",
    )


def _sell_request(
    symbol: str = "NIFTY",
    exchange: str = "NFO",
    quantity: int = 50,
) -> BrokerOrderRequest:
    return BrokerOrderRequest(
        symbol=symbol,
        exchange=exchange,
        direction="SELL",
        quantity=quantity,
        order_type="MARKET",
        product="INTRADAY",
        limit_price=None,
        trigger_price=None,
        tag="test",
    )


@pytest.fixture
def broker() -> PaperBrokerAdapter:
    b = PaperBrokerAdapter()
    yield b
    b.reset()


@pytest.fixture
def session() -> BrokerSession:
    return _make_session()


class TestBrokerNameAndLogin:
    def test_broker_name_is_paper(self, broker: PaperBrokerAdapter) -> None:
        assert broker.broker_name == "paper"

    async def test_login_returns_session(self, broker: PaperBrokerAdapter) -> None:
        s = await broker.login(api_key="k", request_token="r", api_secret="s")
        assert s.broker_name == "paper"
        assert s.is_active is True
        assert s.is_expired() is False

    async def test_logout_deactivates_session(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        await broker.logout(session)
        assert session.is_active is False

    async def test_get_profile_returns_paper_user(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        profile = await broker.get_profile(session)
        assert profile.user_id == "PAPER_USER"
        assert profile.broker_name == "paper"


class TestPlaceOrder:
    async def test_place_market_buy_returns_order_id(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        order_id = await broker.place_order(session, _buy_request())
        assert order_id.startswith("PAPER-")

    async def test_place_market_buy_fills_at_ltp_plus_slippage(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        order_id = await broker.place_order(session, _buy_request())
        orders = await broker.get_orders(session)
        assert any(
            o.broker_order_id == order_id and o.average_price > Decimal("22000")
            for o in orders
        )

    async def test_place_market_sell_fills_at_ltp_minus_slippage(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        order_id = await broker.place_order(session, _sell_request())
        orders = await broker.get_orders(session)
        assert any(
            o.broker_order_id == order_id and o.average_price < Decimal("22000")
            for o in orders
        )

    async def test_limit_order_fills_at_limit_price(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        req = _buy_request(order_type="LIMIT", limit_price=Decimal("21990"))
        order_id = await broker.place_order(session, req)
        orders = await broker.get_orders(session)
        assert any(
            o.broker_order_id == order_id and o.average_price == Decimal("21990")
            for o in orders
        )

    async def test_order_defaults_to_default_ltp_when_not_set(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        order_id = await broker.place_order(session, _buy_request())
        orders = await broker.get_orders(session)
        assert any(o.broker_order_id == order_id for o in orders)

    async def test_multiple_orders_get_unique_ids(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        id1 = await broker.place_order(session, _buy_request())
        id2 = await broker.place_order(session, _buy_request())
        assert id1 != id2

    async def test_place_order_expired_session_raises(
        self, broker: PaperBrokerAdapter
    ) -> None:
        expired_session = _make_session(expired=True)
        with pytest.raises(BrokerSessionExpiredError):
            await broker.place_order(expired_session, _buy_request())


class TestCancelOrder:
    async def test_cancel_order_marks_cancelled(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        order_id = await broker.place_order(session, _buy_request())
        orders_before = await broker.get_orders(session)
        placed = next(o for o in orders_before if o.broker_order_id == order_id)
        assert placed.status == "COMPLETE"

        await broker.cancel_order(session, order_id)
        orders_after = await broker.get_orders(session)
        cancelled = next(o for o in orders_after if o.broker_order_id == order_id)
        assert cancelled.status == "CANCELLED"

    async def test_cancel_nonexistent_order_raises(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        with pytest.raises(BrokerOrderError):
            await broker.cancel_order(session, "PAPER-99999999")


class TestPositions:
    async def test_buy_creates_long_position(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy_request(quantity=50))
        positions = await broker.get_positions(session)
        assert len(positions) == 1
        assert positions[0].quantity == 50
        assert positions[0].symbol == "NIFTY"

    async def test_buy_and_sell_same_quantity_closes_position(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy_request(quantity=50))
        await broker.place_order(session, _sell_request(quantity=50))
        positions = await broker.get_positions(session)
        assert positions == []

    async def test_no_positions_initially(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        positions = await broker.get_positions(session)
        assert positions == []


class TestGetLTP:
    async def test_get_ltp_returns_injected_price(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22500"))
        result = await broker.get_ltp(session, ["NFO:NIFTY"])
        assert result["NFO:NIFTY"] == Decimal("22500")

    async def test_get_ltp_returns_default_when_unknown(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        result = await broker.get_ltp(session, ["BSE:RELIANCE"])
        assert result["BSE:RELIANCE"] == Decimal("100")


class TestReset:
    async def test_reset_clears_orders(
        self, broker: PaperBrokerAdapter, session: BrokerSession
    ) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("22000"))
        await broker.place_order(session, _buy_request())
        broker.reset()
        session2 = _make_session()
        orders = await broker.get_orders(session2)
        assert orders == []

    async def test_reset_clears_ltp(self, broker: PaperBrokerAdapter) -> None:
        broker.set_ltp("NFO", "NIFTY", Decimal("99999"))
        broker.reset()
        session2 = _make_session()
        result = await broker.get_ltp(session2, ["NFO:NIFTY"])
        assert result["NFO:NIFTY"] == Decimal("100")
