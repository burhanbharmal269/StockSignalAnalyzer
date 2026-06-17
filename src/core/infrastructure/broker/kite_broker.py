"""KiteBroker — IBroker adapter for the Kite Connect API.

Uses composition: a KiteConnect SDK instance is created per call and discarded.
No KiteConnect types are exposed outside this module.

The kiteconnect package is an optional hard dependency at runtime.
Unit tests use PaperBrokerAdapter instead; this adapter is integration-tested
against the live sandbox only.

Reference: docs/04_BROKER_ABSTRACTION.md, docs/23_SECURITY_BASELINE.md §1.1
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from core.domain.entities.broker_session import BrokerSession
from core.domain.exceptions.broker import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerHealthCheckError,
    BrokerOrderError,
    BrokerSessionExpiredError,
)
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
from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from core.infrastructure.broker.token_encryptor import TokenEncryptor
    from core.infrastructure.config.broker_config import BrokerConfig

logger = get_logger(__name__)

_IST = ZoneInfo("Asia/Kolkata")

# Internal product → Kite product code
_PRODUCT_MAP: dict[str, str] = {
    "INTRADAY": "MIS",
    "OVERNIGHT": "NRML",
    "DELIVERY": "CNC",
}

# Internal order type → Kite order type
_ORDER_TYPE_MAP: dict[str, str] = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL_LIMIT": "SL",
    "SL_MARKET": "SL-M",
}

# Internal direction → Kite transaction type
_DIRECTION_MAP: dict[str, str] = {
    "BUY": "BUY",
    "SELL": "SELL",
}


def _next_kite_expiry() -> datetime:
    """Return the next Kite token expiry time (06:00 IST) as a UTC datetime."""
    now_ist = datetime.now(_IST)
    expiry_ist = now_ist.replace(hour=6, minute=0, second=0, microsecond=0)
    if now_ist >= expiry_ist:
        expiry_ist = expiry_ist + timedelta(days=1)
    return expiry_ist.astimezone(UTC)


class KiteBroker(IBroker):
    """Kite Connect broker adapter.

    All KiteConnect SDK calls are synchronous; they are wrapped in
    run_in_executor() to avoid blocking the asyncio event loop.

    Requires: pip install kiteconnect
    """

    def __init__(
        self,
        token_encryptor: TokenEncryptor,
        config: BrokerConfig,
    ) -> None:
        self._encryptor = token_encryptor
        self._config = config

    @property
    def broker_name(self) -> str:
        return "kite"

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def login(
        self,
        api_key: str,
        request_token: str,
        api_secret: str,
    ) -> BrokerSession:
        logger.info("kite_broker.login.start", api_key_prefix=api_key[:4])
        try:
            kite = self._make_kite(api_key)
            loop = asyncio.get_event_loop()
            session_data: dict[str, Any] = await loop.run_in_executor(
                None,
                lambda: kite.generate_session(request_token, api_secret=api_secret),
            )
        except Exception as exc:
            logger.error("kite_broker.login.failed", error=str(exc))
            msg = f"Kite login failed: {exc}"
            raise BrokerAuthenticationError(msg) from exc

        access_token: str = session_data["access_token"]
        encrypted = await self._encryptor.encrypt(access_token)

        session = BrokerSession.create(
            broker_name="kite",
            api_key=api_key,
            encrypted_access_token=encrypted,
            expires_at=_next_kite_expiry(),
        )
        logger.info("kite_broker.login.success", session_id=str(session.session_id))
        return session

    async def logout(self, session: BrokerSession) -> None:
        logger.info("kite_broker.logout", session_id=str(session.session_id))
        try:
            kite = await self._authenticated_kite(session)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, kite.invalidate_access_token)
        except (BrokerSessionExpiredError, BrokerConnectionError):
            raise
        except Exception as exc:
            logger.warning("kite_broker.logout.failed", error=str(exc))
        finally:
            session.deactivate()

    async def get_profile(self, session: BrokerSession) -> BrokerProfile:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        try:
            data: dict[str, Any] = await loop.run_in_executor(None, kite.profile)
        except Exception as exc:
            msg = f"get_profile failed: {exc}"
            raise BrokerConnectionError(msg) from exc
        return BrokerProfile(
            user_id=data.get("user_id", ""),
            full_name=data.get("user_name", ""),
            email=data.get("email", ""),
            broker_name="kite",
        )

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def place_order(
        self,
        session: BrokerSession,
        request: BrokerOrderRequest,
    ) -> str:
        kite = await self._authenticated_kite(session)
        product = _PRODUCT_MAP.get(request.product, "MIS")
        order_type = _ORDER_TYPE_MAP.get(request.order_type, "MARKET")
        direction = _DIRECTION_MAP.get(request.direction, request.direction)

        loop = asyncio.get_event_loop()
        try:
            order_id = await loop.run_in_executor(
                None,
                lambda: kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=request.exchange,
                    tradingsymbol=request.symbol,
                    transaction_type=direction,
                    quantity=request.quantity,
                    product=product,
                    order_type=order_type,
                    price=float(request.limit_price) if request.limit_price else None,
                    trigger_price=(
                        float(request.trigger_price) if request.trigger_price else None
                    ),
                    tag=request.tag or None,
                ),
            )
        except Exception as exc:
            logger.error(
                "kite_broker.place_order.failed",
                symbol=request.symbol,
                error=str(exc),
            )
            msg = f"place_order failed: {exc}"
            raise BrokerOrderError(msg) from exc

        logger.info(
            "kite_broker.place_order.success",
            broker_order_id=str(order_id),
            symbol=request.symbol,
            direction=request.direction,
            quantity=request.quantity,
        )
        return str(order_id)

    async def modify_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
        quantity: int | None = None,
        limit_price: Decimal | None = None,
        trigger_price: Decimal | None = None,
    ) -> None:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        kwargs: dict[str, Any] = {"order_id": broker_order_id, "variety": kite.VARIETY_REGULAR}
        if quantity is not None:
            kwargs["quantity"] = quantity
        if limit_price is not None:
            kwargs["price"] = float(limit_price)
        if trigger_price is not None:
            kwargs["trigger_price"] = float(trigger_price)
        try:
            await loop.run_in_executor(None, lambda: kite.modify_order(**kwargs))
        except Exception as exc:
            msg = f"modify_order failed: {exc}"
            raise BrokerOrderError(msg) from exc

    async def cancel_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
    ) -> None:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: kite.cancel_order(
                    variety=kite.VARIETY_REGULAR,
                    order_id=broker_order_id,
                ),
            )
        except Exception as exc:
            logger.error(
                "kite_broker.cancel_order.failed",
                broker_order_id=broker_order_id,
                error=str(exc),
            )
            msg = f"cancel_order failed: {exc}"
            raise BrokerOrderError(msg) from exc

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def get_positions(self, session: BrokerSession) -> list[BrokerPosition]:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        data: dict[str, Any] = await loop.run_in_executor(None, kite.positions)
        positions = []
        for raw in data.get("net", []):
            net_qty = int(raw.get("net_quantity", raw["quantity"]))
            positions.append(
                BrokerPosition(
                    symbol=raw["tradingsymbol"],
                    exchange=raw["exchange"],
                    product=raw["product"],
                    quantity=abs(int(raw["quantity"])),
                    average_price=Decimal(str(raw["average_price"])),
                    last_price=Decimal(str(raw["last_price"])),
                    pnl=Decimal(str(raw["pnl"])),
                    day_pnl=Decimal(str(raw.get("day_change", 0))),
                    net_quantity=net_qty,
                )
            )
        return positions

    async def get_holdings(self, session: BrokerSession) -> list[BrokerHolding]:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        data: list[dict[str, Any]] = await loop.run_in_executor(None, kite.holdings)
        return [
            BrokerHolding(
                symbol=row["tradingsymbol"],
                exchange=row["exchange"],
                isin=row.get("isin", ""),
                quantity=int(row["quantity"]),
                average_price=Decimal(str(row["average_price"])),
                last_price=Decimal(str(row["last_price"])),
                pnl=Decimal(str(row["pnl"])),
            )
            for row in data
        ]

    async def get_orders(self, session: BrokerSession) -> list[BrokerOrder]:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        data: list[dict[str, Any]] = await loop.run_in_executor(None, kite.orders)
        return [_map_kite_order(row) for row in data]

    async def get_trades(self, session: BrokerSession) -> list[BrokerTrade]:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        data: list[dict[str, Any]] = await loop.run_in_executor(None, kite.trades)
        return [
            BrokerTrade(
                trade_id=str(row["trade_id"]),
                broker_order_id=str(row["order_id"]),
                symbol=row["tradingsymbol"],
                exchange=row["exchange"],
                direction=row["transaction_type"],
                quantity=int(row["quantity"]),
                price=Decimal(str(row["average_price"])),
                traded_at=_parse_kite_dt(row.get("fill_timestamp")),
            )
            for row in data
        ]

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_ltp(
        self,
        session: BrokerSession,
        instruments: list[str],
    ) -> dict[str, Decimal]:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        data: dict[str, Any] = await loop.run_in_executor(
            None, lambda: kite.ltp(instruments)
        )
        return {
            instrument: Decimal(str(quote["last_price"]))
            for instrument, quote in data.items()
        }

    async def get_option_chain(
        self,
        session: BrokerSession,
        symbol: str,
        expiry: date,
    ) -> list[OptionChainEntry]:
        """Fetch full option chain via Kite instruments filtered by expiry.

        Kite does not have a dedicated option chain endpoint; this method
        queries the instrument master and LTP for each strike.
        """
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        instruments: list[dict[str, Any]] = await loop.run_in_executor(
            None, lambda: kite.instruments("NFO")
        )
        chain_instruments = [
            inst
            for inst in instruments
            if inst["name"] == symbol
            and inst.get("expiry") == expiry
            and inst["instrument_type"] in ("CE", "PE")
        ]
        if not chain_instruments:
            return []

        inst_strings = [f"NFO:{inst['tradingsymbol']}" for inst in chain_instruments]
        ltp_data: dict[str, Any] = await loop.run_in_executor(
            None, lambda: kite.ltp(inst_strings)
        )
        entries = []
        for inst in chain_instruments:
            key = f"NFO:{inst['tradingsymbol']}"
            quote = ltp_data.get(key, {})
            entries.append(
                OptionChainEntry(
                    symbol=inst["name"],
                    exchange="NFO",
                    expiry=expiry,
                    strike=Decimal(str(inst["strike"])),
                    option_type=inst["instrument_type"],
                    last_price=Decimal(str(quote.get("last_price", 0))),
                    open_interest=int(quote.get("oi", 0)),
                    change_in_oi=int(quote.get("oi_day_change", 0)),
                    volume=int(quote.get("volume", 0)),
                    instrument_token=int(inst["instrument_token"]),
                )
            )
        return entries

    # ------------------------------------------------------------------
    # Phase 16 additions
    # ------------------------------------------------------------------

    async def connect(self, session: BrokerSession) -> None:
        """REST ping to verify the session is reachable."""
        await self.get_profile(session)
        logger.info("kite_broker.connect", session_id=str(session.session_id))

    async def disconnect(self, session: BrokerSession) -> None:
        """No persistent connection for REST; logs intent only."""
        logger.info("kite_broker.disconnect", session_id=str(session.session_id))

    async def get_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
    ) -> BrokerOrder | None:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        try:
            history: list[dict] = await loop.run_in_executor(
                None, lambda: kite.order_history(broker_order_id)
            )
        except Exception:
            return None
        if not history:
            return None
        return _map_kite_order(history[-1])

    async def get_position(
        self,
        session: BrokerSession,
        symbol: str,
        exchange: str,
    ) -> BrokerPosition | None:
        positions = await self.get_positions(session)
        for pos in positions:
            if pos.symbol == symbol and pos.exchange == exchange:
                return pos
        return None

    async def get_margin(self, session: BrokerSession) -> BrokerMargin:
        kite = await self._authenticated_kite(session)
        loop = asyncio.get_event_loop()
        try:
            data: dict = await loop.run_in_executor(None, kite.margins)
        except Exception as exc:
            msg = f"get_margin failed: {exc}"
            raise BrokerConnectionError(msg) from exc
        equity = data.get("equity", {})
        available = Decimal(str(equity.get("available", {}).get("cash", 0)))
        used = Decimal(str(equity.get("utilised", {}).get("debits", 0)))
        exposure = Decimal(str(equity.get("utilised", {}).get("exposure", 0)))
        span = Decimal(str(equity.get("utilised", {}).get("span", 0)))
        total = available + used
        return BrokerMargin(
            available_cash=available,
            used_margin=used,
            total_margin=total,
            segment="equity",
            exposure_margin=exposure,
            span_margin=span,
        )

    async def health_check(self) -> BrokerHealthReport:
        import time
        start = time.monotonic()
        try:
            kite = self._make_kite(self._config.kite_api_key)
            loop = asyncio.get_event_loop()
            # instruments endpoint requires no auth — use as connectivity probe
            await loop.run_in_executor(None, lambda: kite.instruments("NSE"))
            latency_ms = (time.monotonic() - start) * 1000
            return BrokerHealthReport(
                broker_name="kite",
                status=BrokerHealthStatus.HEALTHY,
                latency_ms=round(latency_ms, 2),
                details={"probe": "instruments_nse"},
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.error("kite_broker.health_check.failed", error=str(exc))
            raise BrokerHealthCheckError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_kite(self, api_key: str) -> Any:
        try:
            from kiteconnect import KiteConnect  # type: ignore[import-untyped]
        except ImportError as exc:
            msg = "kiteconnect package is required for KiteBroker."
            raise ImportError(msg) from exc
        return KiteConnect(api_key=api_key)

    async def _authenticated_kite(self, session: BrokerSession) -> Any:
        if session.is_expired():
            msg = f"Kite session {session.session_id} has expired."
            raise BrokerSessionExpiredError(msg)
        try:
            access_token = await self._encryptor.decrypt(session.encrypted_access_token)
        except Exception as exc:
            msg = f"Failed to decrypt access token: {exc}"
            raise BrokerConnectionError(msg) from exc
        kite = self._make_kite(session.api_key)
        kite.set_access_token(access_token)
        return kite


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _parse_kite_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_IST).astimezone(UTC)
        return value.astimezone(UTC)
    return datetime.now(UTC)


def _map_kite_order(row: dict[str, Any]) -> BrokerOrder:
    limit_price_raw = row.get("price")
    avg_price_raw = row.get("average_price")
    return BrokerOrder(
        broker_order_id=str(row["order_id"]),
        symbol=row["tradingsymbol"],
        exchange=row["exchange"],
        direction=row["transaction_type"],
        quantity=int(row["quantity"]),
        filled_quantity=int(row.get("filled_quantity", 0)),
        status=row.get("status", ""),
        order_type=row.get("order_type", ""),
        product=row.get("product", ""),
        limit_price=Decimal(str(limit_price_raw)) if limit_price_raw else None,
        average_price=Decimal(str(avg_price_raw)) if avg_price_raw else None,
        placed_at=_parse_kite_dt(row.get("order_timestamp")),
    )
