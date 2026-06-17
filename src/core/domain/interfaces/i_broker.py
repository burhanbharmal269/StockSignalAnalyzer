"""IBroker — domain port for broker API communication.

All broker operations must go through this interface. No component outside
the infrastructure/broker/ package may import KiteConnect, Angel, or any
other broker SDK directly.

Reference: docs/04_BROKER_ABSTRACTION.md, docs/09_CLAUDE_EXECUTION_RULES.md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.entities.broker_session import BrokerSession
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
    from core.domain.value_objects.broker_health import BrokerHealthReport


class IBroker(ABC):
    """Broker-agnostic interface for authentication, orders, and market data.

    Implementations: KiteBroker, PaperBrokerAdapter (and future adapters).
    The application layer never imports a concrete broker class.

    All methods are async. Synchronous broker SDKs (e.g. KiteConnect) must
    wrap their calls in asyncio.get_event_loop().run_in_executor().
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Short identifier for the broker (e.g. 'kite', 'paper')."""

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    @abstractmethod
    async def login(
        self,
        api_key: str,
        request_token: str,
        api_secret: str,
    ) -> BrokerSession:
        """Authenticate and return an encrypted BrokerSession.

        The access token is encrypted before being stored in BrokerSession.
        The plaintext token is discarded after encryption.

        Raises:
            BrokerAuthenticationError: On invalid credentials or token.
        """

    @abstractmethod
    async def logout(self, session: BrokerSession) -> None:
        """Invalidate the session at the broker and deactivate locally."""

    @abstractmethod
    async def get_profile(self, session: BrokerSession) -> BrokerProfile:
        """Return the authenticated user's profile information."""

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    @abstractmethod
    async def place_order(
        self,
        session: BrokerSession,
        request: BrokerOrderRequest,
    ) -> str:
        """Submit an order and return the broker-assigned order ID.

        Raises:
            BrokerSessionExpiredError: If session.is_expired().
            BrokerOrderError: If the broker rejects the order.
        """

    @abstractmethod
    async def modify_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
        quantity: int | None = None,
        limit_price: Decimal | None = None,
        trigger_price: Decimal | None = None,
    ) -> None:
        """Modify an open order's quantity or price.

        Raises:
            BrokerSessionExpiredError: If session.is_expired().
            BrokerOrderError: If the broker rejects the modification.
        """

    @abstractmethod
    async def cancel_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
    ) -> None:
        """Cancel an open order.

        Raises:
            BrokerSessionExpiredError: If session.is_expired().
            BrokerOrderError: If cancellation fails.
        """

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_positions(self, session: BrokerSession) -> list[BrokerPosition]:
        """Return all open intraday and overnight positions."""

    @abstractmethod
    async def get_holdings(self, session: BrokerSession) -> list[BrokerHolding]:
        """Return all delivery holdings."""

    @abstractmethod
    async def get_orders(self, session: BrokerSession) -> list[BrokerOrder]:
        """Return today's complete order book."""

    @abstractmethod
    async def get_trades(self, session: BrokerSession) -> list[BrokerTrade]:
        """Return today's executed trades."""

    # ------------------------------------------------------------------
    # Market data (REST)
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_ltp(
        self,
        session: BrokerSession,
        instruments: list[str],
    ) -> dict[str, Decimal]:
        """Return last-traded prices for the given instrument strings.

        Args:
            instruments: List of "EXCHANGE:SYMBOL" strings (e.g. ["NSE:NIFTY50"]).

        Returns:
            Mapping from instrument string to last-traded price (Decimal).
        """

    @abstractmethod
    async def get_option_chain(
        self,
        session: BrokerSession,
        symbol: str,
        expiry: date,
    ) -> list[OptionChainEntry]:
        """Return a full option chain snapshot for *symbol* at *expiry*.

        Includes all CE and PE strikes with OI, volume, and price data.
        """

    # ------------------------------------------------------------------
    # Phase 16 additions
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self, session: BrokerSession) -> None:
        """Establish a broker connection (e.g. WebSocket or REST keep-alive).

        For REST-only brokers this may be a no-op health ping.
        """

    @abstractmethod
    async def disconnect(self, session: BrokerSession) -> None:
        """Close the broker connection gracefully."""

    @abstractmethod
    async def get_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
    ) -> BrokerOrder | None:
        """Return a single order by its broker-assigned ID, or None if not found."""

    @abstractmethod
    async def get_position(
        self,
        session: BrokerSession,
        symbol: str,
        exchange: str,
    ) -> BrokerPosition | None:
        """Return a single open position for *symbol*/*exchange*, or None."""

    @abstractmethod
    async def get_margin(self, session: BrokerSession) -> BrokerMargin:
        """Return current margin details (cash, used, total) from the broker."""

    @abstractmethod
    async def health_check(self) -> BrokerHealthReport:
        """Probe broker connectivity and return a health report.

        Does not require an authenticated session — only checks reachability.
        Returns BrokerHealthReport with status HEALTHY / DEGRADED / DOWN.
        """
