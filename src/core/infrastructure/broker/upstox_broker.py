"""UpstoxBrokerAdapter — placeholder IBroker for Upstox API (not yet implemented)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.domain.entities.broker_session import BrokerSession
from core.domain.interfaces.i_broker import IBroker
from core.domain.value_objects.broker_dtos import (
    BrokerHolding,
    BrokerMargin,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
    BrokerProfile,
    BrokerTrade,
    OptionChainEntry,
)
from core.domain.value_objects.broker_health import BrokerHealthReport, BrokerHealthStatus


class UpstoxBrokerAdapter(IBroker):
    """Placeholder adapter for Upstox. Not implemented."""

    @property
    def broker_name(self) -> str:
        return "upstox"

    def _not_implemented(self) -> None:
        raise NotImplementedError("UpstoxBrokerAdapter is not yet implemented.")

    async def login(self, api_key: str, request_token: str, api_secret: str) -> BrokerSession:
        self._not_implemented()

    async def logout(self, session: BrokerSession) -> None:
        self._not_implemented()

    async def get_profile(self, session: BrokerSession) -> BrokerProfile:
        self._not_implemented()

    async def place_order(self, session: BrokerSession, request: BrokerOrderRequest) -> str:
        self._not_implemented()

    async def modify_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
        quantity: int | None = None,
        limit_price: Decimal | None = None,
        trigger_price: Decimal | None = None,
    ) -> None:
        self._not_implemented()

    async def cancel_order(self, session: BrokerSession, broker_order_id: str) -> None:
        self._not_implemented()

    async def get_positions(self, session: BrokerSession) -> list[BrokerPosition]:
        self._not_implemented()

    async def get_holdings(self, session: BrokerSession) -> list[BrokerHolding]:
        self._not_implemented()

    async def get_orders(self, session: BrokerSession) -> list[BrokerOrder]:
        self._not_implemented()

    async def get_trades(self, session: BrokerSession) -> list[BrokerTrade]:
        self._not_implemented()

    async def get_ltp(self, session: BrokerSession, instruments: list[str]) -> dict[str, Decimal]:
        self._not_implemented()

    async def get_option_chain(
        self,
        session: BrokerSession,
        symbol: str,
        expiry: date,
    ) -> list[OptionChainEntry]:
        self._not_implemented()

    async def connect(self, session: BrokerSession) -> None:
        self._not_implemented()

    async def disconnect(self, session: BrokerSession) -> None:
        self._not_implemented()

    async def get_order(self, session: BrokerSession, broker_order_id: str) -> BrokerOrder | None:
        self._not_implemented()

    async def get_position(
        self, session: BrokerSession, symbol: str, exchange: str
    ) -> BrokerPosition | None:
        self._not_implemented()

    async def get_margin(self, session: BrokerSession) -> BrokerMargin:
        self._not_implemented()

    async def health_check(self) -> BrokerHealthReport:
        return BrokerHealthReport(
            broker_name="upstox",
            status=BrokerHealthStatus.DOWN,
            error="UpstoxBrokerAdapter not implemented",
        )
