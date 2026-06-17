"""PaperBroker IBroker compliance tests.

Verifies that PaperBrokerAdapter passes all 16 contracts defined in
IBrokerComplianceTests. No network calls; fully self-contained.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from core.domain.entities.broker_session import BrokerSession
from core.domain.value_objects.broker_health import BrokerHealthReport
from core.infrastructure.broker.paper_broker import PaperBrokerAdapter
from core.domain.value_objects.broker_dtos import BrokerOrderRequest
from tests.broker_compliance.base_compliance import IBrokerComplianceTests


def _make_session() -> BrokerSession:
    return BrokerSession(
        session_id="test-paper-session",
        broker_name="paper",
        encrypted_access_token=b"fake",
        api_key="key",
        expires_at=datetime.now(UTC) + timedelta(hours=8),
        is_active=True,
    )


class TestPaperBrokerCompliance(IBrokerComplianceTests):
    """PaperBrokerAdapter must satisfy every IBroker contract."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self._broker = PaperBrokerAdapter()
        self._session = _make_session()

    # PaperBroker-specific: verify broker_name is 'paper'
    def test_paper_broker_name_is_paper(self) -> None:
        assert self._broker.broker_name == "paper"

    # PaperBroker-specific: health check always returns HEALTHY
    @pytest.mark.asyncio
    async def test_paper_health_always_healthy(self) -> None:
        report = await self._broker.health_check()
        assert report.status == "HEALTHY"

    # Override C14: paper broker fills all orders immediately (no OPEN state after placement).
    # Modification is tested via simulate_partial_fill to put the order into OPEN state.
    @pytest.mark.asyncio
    async def test_c14_modify_order_does_not_raise(self) -> None:
        limit_request = BrokerOrderRequest(
            symbol="NIFTY2571724000CE",
            exchange="NFO",
            direction="BUY",
            order_type="LIMIT",
            quantity=50,
            product="INTRADAY",
            limit_price=Decimal("100.00"),
        )
        broker_order_id = await self._broker.place_order(self._session, limit_request)
        # Paper broker fills immediately → manually reopen to OPEN state for modify test
        self._broker._orders[broker_order_id]["status"] = "OPEN"
        # Must not raise; paper broker allows modification of OPEN orders
        await self._broker.modify_order(
            self._session,
            broker_order_id,
            quantity=1,
            limit_price=Decimal("99.00"),
        )
