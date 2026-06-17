"""AngelBrokerAdapter IBroker compliance tests.

All SmartAPI SDK calls are mocked at asyncio.to_thread level.
No real network calls are made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.entities.broker_session import BrokerSession
from tests.broker_compliance.base_compliance import IBrokerComplianceTests


def _make_session() -> BrokerSession:
    return BrokerSession(
        session_id="test-angel-session",
        broker_name="angel",
        encrypted_access_token=b"encrypted_token_bytes",
        api_key="test_api_key",
        expires_at=datetime.now(UTC) + timedelta(hours=8),
        is_active=True,
    )


class _FakeSmartApi:
    """Minimal SmartAPI mock returning plausible responses."""

    def placeOrder(self, params):  # noqa: N802
        return {"status": True, "data": {"orderid": "ANGEL-123456"}}

    def modifyOrder(self, params):  # noqa: N802
        return {"status": True, "data": {}}

    def cancelOrder(self, order_id, params):  # noqa: N802
        return {"status": True, "data": {}}

    def orderBook(self):  # noqa: N802
        return {"status": True, "data": []}

    def position(self):
        return {"status": True, "data": []}

    def holding(self):
        return {"status": True, "data": []}

    def tradeBook(self):  # noqa: N802
        return {"status": True, "data": []}

    def ltpData(self, exchange, symbol, token):  # noqa: N802
        return {"status": True, "data": {"ltp": 22500.50}}

    def getOrderStatus(self, order_id):  # noqa: N802
        return {"status": False, "data": None}  # simulates not found → None

    def getRMS(self):  # noqa: N802
        return {
            "status": True,
            "data": {
                "availablecash": "50000.00",
                "utilisedpayableamount": "10000.00",
                "net": "40000.00",
            },
        }

    def rmsLimit(self):  # noqa: N802
        return {
            "status": True,
            "data": {
                "availablecash": "50000.00",
                "utilisedpayableamount": "10000.00",
                "net": "40000.00",
            },
        }

    def getOptionChainDetails(self, exchange, name, expiry, strike_price):  # noqa: N802
        return {"status": True, "data": {"fetched": []}}

    def getProfile(self, refresh_token):  # noqa: N802
        return {
            "status": True,
            "data": {
                "clientcode": "A12345",
                "name": "Test User",
                "email": "test@example.com",
                "mobileno": "9999999999",
                "exchanges": ["NSE", "NFO"],
            },
        }

    def setAccessToken(self, token):  # noqa: N802
        pass  # no-op


@pytest.mark.asyncio
class TestAngelBrokerCompliance(IBrokerComplianceTests):
    """AngelBrokerAdapter must satisfy every IBroker contract (with mocked SDK)."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch) -> None:
        try:
            from core.infrastructure.broker.angel_broker import AngelBrokerAdapter
        except ImportError:
            pytest.skip("AngelBrokerAdapter not importable — skipping compliance tests")

        self._fake_smartapi = _FakeSmartApi()

        # Patch asyncio.to_thread so that sync SDK calls run synchronously in tests
        async def _fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        monkeypatch.setattr("asyncio.to_thread", _fake_to_thread)

        config = MagicMock()
        config.angel_api_key = "test_key"
        config.angel_client_code = "A12345"

        token_encryptor = MagicMock()
        token_encryptor.decrypt = AsyncMock(return_value="decrypted_access_token")

        self._broker = AngelBrokerAdapter(
            config=config,
            token_encryptor=token_encryptor,
        )

        # Bypass the real SDK instantiation: always return the fake
        fake = self._fake_smartapi

        async def _fake_get_authenticated_sdk(session):
            return fake, "decrypted_access_token"

        self._broker._get_authenticated_sdk = _fake_get_authenticated_sdk

        self._session = _make_session()

    # Angel-specific: broker_name must be 'angel'
    def test_angel_broker_name_is_angel(self) -> None:
        assert self._broker.broker_name == "angel"
