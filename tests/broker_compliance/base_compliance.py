"""IBrokerComplianceTests — base class for all broker adapter compliance tests.

Every broker adapter that implements IBroker MUST pass all tests in this class.
Concrete subclasses set `_broker` and `_session` in setUp-style fixtures.

Compliance tests verify the CONTRACT, not the broker's real API.
Real API calls are mocked at the adapter boundary.

Usage:
    class TestMyBrokerCompliance(IBrokerComplianceTests):
        @pytest.fixture(autouse=True)
        def setup(self, mocker):
            self._broker = MyBrokerAdapter(...)
            self._session = FakeBrokerSession()
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from core.domain.interfaces.i_broker import IBroker
from core.domain.value_objects.broker_dtos import BrokerOrderRequest
from core.domain.value_objects.broker_health import BrokerHealthReport


class IBrokerComplianceTests:
    """Protocol compliance tests for IBroker implementations.

    Each test verifies one behavioral contract that ALL broker adapters must honour.
    Subclasses inject _broker (IBroker) and _session (BrokerSession-like).
    """

    _broker: IBroker
    _session: object

    # ------------------------------------------------------------------
    # Contract C-01: broker_name is a non-empty string
    # ------------------------------------------------------------------

    def test_c01_broker_name_is_non_empty_string(self) -> None:
        name = self._broker.broker_name
        assert isinstance(name, str), "broker_name must be str"
        assert len(name) > 0, "broker_name must not be empty"

    # ------------------------------------------------------------------
    # Contract C-02: place_order returns a non-empty string (broker order ID)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c02_place_order_returns_string_order_id(self) -> None:
        request = self._make_order_request()
        result = await self._broker.place_order(self._session, request)
        assert isinstance(result, str), "place_order must return str broker_order_id"
        assert len(result) > 0, "place_order must return non-empty broker_order_id"

    # ------------------------------------------------------------------
    # Contract C-03: get_orders returns a list (may be empty)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c03_get_orders_returns_list(self) -> None:
        result = await self._broker.get_orders(self._session)
        assert isinstance(result, list), "get_orders must return list"

    # ------------------------------------------------------------------
    # Contract C-04: get_positions returns a list (may be empty)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c04_get_positions_returns_list(self) -> None:
        result = await self._broker.get_positions(self._session)
        assert isinstance(result, list), "get_positions must return list"

    # ------------------------------------------------------------------
    # Contract C-05: get_holdings returns a list (may be empty)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c05_get_holdings_returns_list(self) -> None:
        result = await self._broker.get_holdings(self._session)
        assert isinstance(result, list), "get_holdings must return list"

    # ------------------------------------------------------------------
    # Contract C-06: get_trades returns a list (may be empty)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c06_get_trades_returns_list(self) -> None:
        result = await self._broker.get_trades(self._session)
        assert isinstance(result, list), "get_trades must return list"

    # ------------------------------------------------------------------
    # Contract C-07: get_ltp returns dict mapping instrument strings to Decimal
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c07_get_ltp_returns_decimal_prices(self) -> None:
        result = await self._broker.get_ltp(self._session, ["NSE:NIFTY50"])
        assert isinstance(result, dict), "get_ltp must return dict"
        for key, value in result.items():
            assert isinstance(key, str), f"LTP key {key!r} must be str"
            assert isinstance(value, Decimal), f"LTP value for {key!r} must be Decimal"

    # ------------------------------------------------------------------
    # Contract C-08: get_option_chain returns a list
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c08_get_option_chain_returns_list(self) -> None:
        result = await self._broker.get_option_chain(
            self._session, "NIFTY", date(2026, 7, 31)
        )
        assert isinstance(result, list), "get_option_chain must return list"

    # ------------------------------------------------------------------
    # Contract C-09: health_check returns BrokerHealthReport
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c09_health_check_returns_health_report(self) -> None:
        result = await self._broker.health_check()
        assert isinstance(result, BrokerHealthReport), (
            f"health_check must return BrokerHealthReport, got {type(result)}"
        )
        assert result.status in ("HEALTHY", "DEGRADED", "DOWN"), (
            f"BrokerHealthReport.status must be HEALTHY/DEGRADED/DOWN, got {result.status!r}"
        )

    # ------------------------------------------------------------------
    # Contract C-10: cancel_order does not raise on valid broker_order_id
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c10_cancel_order_does_not_raise(self) -> None:
        broker_order_id = await self._broker.place_order(
            self._session, self._make_order_request()
        )
        # Must not raise; return value is not specified by the interface
        await self._broker.cancel_order(self._session, broker_order_id)

    # ------------------------------------------------------------------
    # Contract C-11: get_order returns None for unknown order ID
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c11_get_order_returns_none_for_unknown_id(self) -> None:
        result = await self._broker.get_order(self._session, "nonexistent-order-xyz-999")
        assert result is None, (
            "get_order must return None for an unknown broker_order_id"
        )

    # ------------------------------------------------------------------
    # Contract C-12: get_position returns None for unknown symbol
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c12_get_position_returns_none_for_unknown_symbol(self) -> None:
        result = await self._broker.get_position(self._session, "UNKNOWN_SYM_XYZ", "NSE")
        assert result is None, (
            "get_position must return None for an unknown symbol/exchange"
        )

    # ------------------------------------------------------------------
    # Contract C-13: get_margin returns an object with cash / used / total
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c13_get_margin_has_required_fields(self) -> None:
        result = await self._broker.get_margin(self._session)
        assert result is not None, "get_margin must not return None"
        assert hasattr(result, "available_cash") or hasattr(result, "net"), (
            "BrokerMargin must have available_cash or net"
        )

    # ------------------------------------------------------------------
    # Contract C-14: modify_order does not raise on valid inputs
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c14_modify_order_does_not_raise(self) -> None:
        broker_order_id = await self._broker.place_order(
            self._session, self._make_order_request()
        )
        await self._broker.modify_order(
            self._session,
            broker_order_id,
            quantity=1,
            limit_price=Decimal("100.00"),
        )

    # ------------------------------------------------------------------
    # Contract C-15: connect/disconnect are no-ops or succeed without error
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c15_connect_disconnect_succeed(self) -> None:
        await self._broker.connect(self._session)
        await self._broker.disconnect(self._session)

    # ------------------------------------------------------------------
    # Contract C-16: get_profile returns a non-None BrokerProfile
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_c16_get_profile_returns_non_none(self) -> None:
        result = await self._broker.get_profile(self._session)
        assert result is not None, "get_profile must not return None"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_order_request() -> BrokerOrderRequest:
        return BrokerOrderRequest(
            symbol="NIFTY2571724000CE",
            exchange="NFO",
            direction="BUY",
            order_type="MARKET",
            quantity=50,
            product="INTRADAY",
        )
