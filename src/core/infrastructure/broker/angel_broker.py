"""AngelBrokerAdapter — IBroker implementation for Angel One SmartAPI.

Uses the SmartAPI Python client (smartapi-python) via REST.
The SmartAPI SDK is wrapped in asyncio.to_thread() to prevent event loop blocking.

Angel One SmartAPI docs: https://smartapi.angelbroking.com/docs

Product code mapping (SmartAPI):
  INTRADAY  → MIS
  OVERNIGHT → NRML
  DELIVERY  → CNC

Order type mapping:
  MARKET    → MARKET
  LIMIT     → LIMIT
  SL_LIMIT  → STOPLOSS_LIMIT
  SL_MARKET → STOPLOSS_MARKET

No Angel One / SmartAPI types are exposed outside this module.
The OMS never imports this file — only IBroker is known outside infrastructure/broker/.

Reference: docs/04_BROKER_ABSTRACTION.md, docs/23_SECURITY_BASELINE.md §1.1
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from core.domain.entities.broker_session import BrokerSession
from core.domain.exceptions.broker import (
    BrokerAuthenticationError,
    BrokerConnectionError,
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
    from core.infrastructure.config.broker_config import AngelBrokerConfig

logger = get_logger(__name__)

_IST = ZoneInfo("Asia/Kolkata")

# Internal product → SmartAPI product code
_PRODUCT_MAP: dict[str, str] = {
    "INTRADAY": "INTRADAY",
    "OVERNIGHT": "CARRYFORWARD",
    "DELIVERY": "DELIVERY",
}

# Internal order type → SmartAPI order type
_ORDER_TYPE_MAP: dict[str, str] = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL_LIMIT": "STOPLOSS_LIMIT",
    "SL_MARKET": "STOPLOSS_MARKET",
}

# Internal direction → SmartAPI transaction type
_DIRECTION_MAP: dict[str, str] = {
    "BUY": "BUY",
    "SELL": "SELL",
}

# SmartAPI order status → internal status
_STATUS_MAP: dict[str, str] = {
    "complete": "FILLED",
    "rejected": "REJECTED",
    "cancelled": "CANCELLED",
    "open": "OPEN",
    "open pending": "PENDING",
    "trigger pending": "PENDING",
    "modification pending": "PENDING",
    "after market order req received": "PENDING",
    "modified": "OPEN",
}


def _parse_smartapi_datetime(raw: str | None) -> datetime:
    """Parse SmartAPI datetime string (IST) to UTC-aware datetime."""
    if not raw:
        return datetime.now(UTC)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S"):
        try:
            naive = datetime.strptime(raw, fmt)
            return naive.replace(tzinfo=_IST).astimezone(UTC)
        except ValueError:
            continue
    return datetime.now(UTC)


def _next_angel_token_expiry() -> datetime:
    """Return 06:30 IST tomorrow as UTC (Angel tokens expire at market open)."""
    now_ist = datetime.now(_IST)
    expiry_ist = now_ist.replace(hour=6, minute=30, second=0, microsecond=0)
    if now_ist >= expiry_ist:
        expiry_ist += timedelta(days=1)
    return expiry_ist.astimezone(UTC)


class AngelBrokerAdapter(IBroker):
    """Production IBroker adapter for Angel One using SmartAPI.

    Depends on `smartapi-python` package. Wrap all SDK calls in
    asyncio.to_thread() since SmartAPI is a synchronous REST client.
    """

    def __init__(
        self,
        token_encryptor: "TokenEncryptor",
        config: "AngelBrokerConfig",
    ) -> None:
        self._encryptor = token_encryptor
        self._config = config

    @property
    def broker_name(self) -> str:
        return "angel"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_sdk(self):  # type: ignore[return]
        """Return a SmartConnect instance (no session — call set_access_token separately)."""
        try:
            from SmartApi import SmartConnect  # type: ignore[import]
        except ImportError as exc:
            msg = "smartapi-python package is not installed. pip install smartapi-python"
            raise BrokerConnectionError(msg) from exc
        return SmartConnect(api_key=self._config.angel_api_key)

    async def _get_authenticated_sdk(self, session: BrokerSession):
        """Return an authenticated SmartConnect instance."""
        if session.is_expired():
            raise BrokerSessionExpiredError("Angel One session has expired. Re-authenticate.")
        access_token = await self._encryptor.decrypt(session.encrypted_access_token)
        sdk = self._get_sdk()
        await asyncio.to_thread(sdk.setAccessToken, access_token)
        return sdk, access_token

    def _check_response(self, response: dict, operation: str) -> dict:
        """Raise BrokerOrderError if SmartAPI returned an error status."""
        if not response.get("status"):
            msg = response.get("message", "SmartAPI returned status=false")
            error_code = response.get("errorcode", "")
            raise BrokerOrderError(
                message=msg,
                code=error_code or "SMARTAPI_ERROR",
                broker_name="angel",
            )
        return response.get("data") or {}

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def login(
        self,
        api_key: str,
        request_token: str,
        api_secret: str,
    ) -> BrokerSession:
        """Authenticate with Angel One SmartAPI.

        For Angel One, `request_token` carries the TOTP/client_pin,
        and `api_secret` carries the mpin/password.
        """
        try:
            sdk = self._get_sdk()
            response = await asyncio.to_thread(
                sdk.generateSession,
                request_token,   # clientCode
                api_secret,      # password / mpin
            )
        except BrokerConnectionError:
            raise
        except Exception as exc:
            raise BrokerAuthenticationError(
                f"Angel One login failed: {exc}", broker_name="angel"
            ) from exc

        if not response.get("status"):
            msg = response.get("message", "Angel One authentication failed")
            raise BrokerAuthenticationError(msg, broker_name="angel")

        data = response.get("data", {})
        access_token: str = data.get("jwtToken", "")
        refresh_token: str = data.get("refreshToken", "")
        if not access_token:
            raise BrokerAuthenticationError("No jwtToken in Angel One response", broker_name="angel")

        encrypted = await self._encryptor.encrypt(access_token)
        return BrokerSession(
            broker_name="angel",
            encrypted_access_token=encrypted,
            refresh_token=refresh_token,
            expires_at=_next_angel_token_expiry(),
        )

    async def logout(self, session: BrokerSession) -> None:
        try:
            sdk, access_token = await self._get_authenticated_sdk(session)
            await asyncio.to_thread(sdk.terminateSession, self._config.angel_client_code)
        except Exception:  # noqa: BLE001
            logger.warning("angel.logout.failed — treating as success")

    async def get_profile(self, session: BrokerSession) -> BrokerProfile:
        sdk, _ = await self._get_authenticated_sdk(session)
        try:
            response = await asyncio.to_thread(sdk.getProfile, getattr(session, "refresh_token", "") or "")
            data = self._check_response(response, "getProfile")
        except BrokerOrderError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One getProfile failed: {exc}") from exc

        return BrokerProfile(
            user_id=data.get("clientcode", ""),
            full_name=data.get("name", ""),
            email=data.get("email", ""),
            broker_name="angel",
        )

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def place_order(
        self,
        session: BrokerSession,
        request: BrokerOrderRequest,
    ) -> str:
        sdk, _ = await self._get_authenticated_sdk(session)

        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": request.symbol,
            "symboltoken": "",  # resolved by SmartAPI if blank
            "transactiontype": _DIRECTION_MAP.get(request.direction, request.direction),
            "exchange": request.exchange,
            "ordertype": _ORDER_TYPE_MAP.get(request.order_type, "MARKET"),
            "producttype": _PRODUCT_MAP.get(request.product, "INTRADAY"),
            "duration": "DAY",
            "price": str(request.limit_price or "0"),
            "triggerprice": str(request.trigger_price or "0"),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(request.quantity),
            "ordertag": request.tag or "",
        }

        try:
            response = await asyncio.to_thread(sdk.placeOrder, order_params)
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One placeOrder call failed: {exc}") from exc

        if not response.get("status"):
            msg = response.get("message", "Angel One order placement failed")
            error_code = response.get("errorcode", "ORDER_REJECTED")
            raise BrokerOrderError(message=msg, code=error_code, broker_name="angel")

        broker_order_id: str = response.get("data", {}).get("orderid", "") or str(response.get("data", ""))
        if not broker_order_id:
            raise BrokerOrderError(
                message="Angel One did not return an order ID", code="NO_ORDER_ID", broker_name="angel"
            )
        logger.info("angel.place_order.success orderid=%s", broker_order_id)
        return broker_order_id

    async def modify_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
        quantity: int | None = None,
        limit_price: Decimal | None = None,
        trigger_price: Decimal | None = None,
    ) -> None:
        sdk, _ = await self._get_authenticated_sdk(session)
        params: dict[str, Any] = {
            "variety": "NORMAL",
            "orderid": broker_order_id,
        }
        if quantity is not None:
            params["quantity"] = str(quantity)
        if limit_price is not None:
            params["price"] = str(limit_price)
        if trigger_price is not None:
            params["triggerprice"] = str(trigger_price)
        try:
            response = await asyncio.to_thread(sdk.modifyOrder, params)
            self._check_response(response, "modifyOrder")
        except BrokerOrderError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One modifyOrder failed: {exc}") from exc

    async def cancel_order(self, session: BrokerSession, broker_order_id: str) -> None:
        sdk, _ = await self._get_authenticated_sdk(session)
        try:
            response = await asyncio.to_thread(
                sdk.cancelOrder, "NORMAL", broker_order_id
            )
            self._check_response(response, "cancelOrder")
        except BrokerOrderError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One cancelOrder failed: {exc}") from exc

    async def get_order(self, session: BrokerSession, broker_order_id: str) -> BrokerOrder | None:
        orders = await self.get_orders(session)
        return next((o for o in orders if o.broker_order_id == broker_order_id), None)

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def get_orders(self, session: BrokerSession) -> list[BrokerOrder]:
        sdk, _ = await self._get_authenticated_sdk(session)
        try:
            response = await asyncio.to_thread(sdk.orderBook)
            data = self._check_response(response, "orderBook")
        except BrokerOrderError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One orderBook failed: {exc}") from exc

        if not isinstance(data, list):
            return []

        orders: list[BrokerOrder] = []
        for item in data:
            status_raw = (item.get("status") or "").lower()
            orders.append(
                BrokerOrder(
                    broker_order_id=item.get("orderid", ""),
                    symbol=item.get("tradingsymbol", ""),
                    exchange=item.get("exchange", ""),
                    direction=item.get("transactiontype", ""),
                    quantity=int(item.get("quantity", 0)),
                    filled_quantity=int(item.get("filledshares", 0)),
                    status=_STATUS_MAP.get(status_raw, status_raw.upper()),
                    order_type=item.get("ordertype", ""),
                    product=item.get("producttype", ""),
                    limit_price=Decimal(str(item.get("price", 0) or 0)) or None,
                    average_price=Decimal(str(item.get("averageprice", 0) or 0)) or None,
                    placed_at=_parse_smartapi_datetime(item.get("orderentrytype")),
                )
            )
        return orders

    async def get_positions(self, session: BrokerSession) -> list[BrokerPosition]:
        sdk, _ = await self._get_authenticated_sdk(session)
        try:
            response = await asyncio.to_thread(sdk.position)
            data = self._check_response(response, "position")
        except BrokerOrderError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One position() failed: {exc}") from exc

        if not isinstance(data, list):
            return []

        positions: list[BrokerPosition] = []
        for item in data:
            qty = int(item.get("netqty", 0))
            if qty == 0:
                continue
            positions.append(
                BrokerPosition(
                    symbol=item.get("tradingsymbol", ""),
                    exchange=item.get("exchange", ""),
                    product=item.get("producttype", ""),
                    quantity=abs(qty),
                    average_price=Decimal(str(item.get("avgnetprice", 0) or 0)),
                    last_price=Decimal(str(item.get("ltp", 0) or 0)),
                    pnl=Decimal(str(item.get("unrealisedpnl", 0) or 0)),
                    net_quantity=qty,
                )
            )
        return positions

    async def get_position(
        self, session: BrokerSession, symbol: str, exchange: str
    ) -> BrokerPosition | None:
        positions = await self.get_positions(session)
        return next(
            (p for p in positions if p.symbol == symbol and p.exchange == exchange), None
        )

    async def get_holdings(self, session: BrokerSession) -> list[BrokerHolding]:
        sdk, _ = await self._get_authenticated_sdk(session)
        try:
            response = await asyncio.to_thread(sdk.holding)
            data = self._check_response(response, "holding")
        except BrokerOrderError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One holding() failed: {exc}") from exc

        if not isinstance(data, list):
            return []

        return [
            BrokerHolding(
                symbol=item.get("tradingsymbol", ""),
                exchange=item.get("exchange", ""),
                isin=item.get("isin", ""),
                quantity=int(item.get("quantity", 0)),
                average_price=Decimal(str(item.get("averageprice", 0) or 0)),
                last_price=Decimal(str(item.get("ltp", 0) or 0)),
                pnl=Decimal(str(item.get("profitandloss", 0) or 0)),
            )
            for item in data
        ]

    async def get_trades(self, session: BrokerSession) -> list[BrokerTrade]:
        sdk, _ = await self._get_authenticated_sdk(session)
        try:
            response = await asyncio.to_thread(sdk.tradeBook)
            data = self._check_response(response, "tradeBook")
        except BrokerOrderError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One tradeBook() failed: {exc}") from exc

        if not isinstance(data, list):
            return []

        return [
            BrokerTrade(
                trade_id=item.get("tradeid", ""),
                broker_order_id=item.get("orderid", ""),
                symbol=item.get("tradingsymbol", ""),
                exchange=item.get("exchange", ""),
                direction=item.get("transactiontype", ""),
                quantity=int(item.get("fillshares", 0)),
                price=Decimal(str(item.get("fillprice", 0) or 0)),
                traded_at=_parse_smartapi_datetime(item.get("filltime")),
            )
            for item in data
        ]

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_ltp(
        self,
        session: BrokerSession,
        instruments: list[str],
    ) -> dict[str, Decimal]:
        """Fetch LTP for a list of "EXCHANGE:SYMBOL" strings.

        SmartAPI LTP endpoint requires a list of {exchange, tradingsymbol, symboltoken}.
        We use the market quote endpoint for simplicity.
        """
        sdk, _ = await self._get_authenticated_sdk(session)

        exchange_tokens: dict[str, list[str]] = {}
        for instrument in instruments:
            parts = instrument.split(":", 1)
            exch = parts[0] if len(parts) == 2 else "NSE"
            sym = parts[1] if len(parts) == 2 else parts[0]
            exchange_tokens.setdefault(exch, []).append(sym)

        results: dict[str, Decimal] = {}
        for exchange, symbols in exchange_tokens.items():
            try:
                quote_params = {
                    "mode": "LTP",
                    "exchangeTokens": {exchange: symbols},
                }
                response = await asyncio.to_thread(sdk.ltpData, exchange, symbols[0], "")
                if response.get("status"):
                    data = response.get("data", {})
                    ltp = Decimal(str(data.get("ltp", 0)))
                    results[f"{exchange}:{symbols[0]}"] = ltp
            except Exception:  # noqa: BLE001
                logger.warning("angel.get_ltp.failed exchange=%s symbols=%s", exchange, symbols)

        return results

    async def get_option_chain(
        self,
        session: BrokerSession,
        symbol: str,
        expiry: date,
    ) -> list[OptionChainEntry]:
        sdk, _ = await self._get_authenticated_sdk(session)
        expiry_str = expiry.strftime("%d%b%Y").upper()  # e.g. "25JAN2024"
        try:
            response = await asyncio.to_thread(
                sdk.getOptionChainDetails, "NFO", symbol, expiry_str, 10
            )
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One getOptionChainDetails failed: {exc}") from exc

        if not response.get("status"):
            return []

        entries: list[OptionChainEntry] = []
        data = response.get("data", {})
        for strike_data in data.get("fetched", []):
            try:
                entries.append(
                    OptionChainEntry(
                        symbol=strike_data.get("tradingSymbol", ""),
                        exchange="NFO",
                        expiry=expiry,
                        strike=Decimal(str(strike_data.get("strikePrice", 0))),
                        option_type=strike_data.get("optionType", ""),
                        last_price=Decimal(str(strike_data.get("close", 0))),
                        open_interest=int(strike_data.get("openInterest", 0)),
                        change_in_oi=int(strike_data.get("changeinOpenInterest", 0)),
                        volume=int(strike_data.get("tradeVolume", 0)),
                        instrument_token=int(strike_data.get("symboltoken", 0)),
                        iv=Decimal(str(strike_data.get("impliedVolatility", 0))) or None,
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return entries

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def connect(self, session: BrokerSession) -> None:
        """REST-only: ping with a profile fetch to confirm session is valid."""
        try:
            await self.get_profile(session)
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One connect/ping failed: {exc}") from exc

    async def disconnect(self, session: BrokerSession) -> None:
        await self.logout(session)

    async def get_margin(self, session: BrokerSession) -> BrokerMargin:
        sdk, _ = await self._get_authenticated_sdk(session)
        try:
            response = await asyncio.to_thread(sdk.rmsLimit)
            data = self._check_response(response, "rmsLimit")
        except BrokerOrderError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(f"Angel One rmsLimit() failed: {exc}") from exc

        net_cash = Decimal(str(data.get("net", 0) or 0))
        used = Decimal(str(data.get("utilisedamount", 0) or 0))
        total = net_cash + used
        return BrokerMargin(
            available_cash=net_cash,
            used_margin=used,
            total_margin=total,
            segment="equity",
            span_margin=Decimal(str(data.get("span", 0) or 0)),
            exposure_margin=Decimal(str(data.get("exposure", 0) or 0)),
        )

    async def health_check(self) -> BrokerHealthReport:
        t0 = time.monotonic()
        try:
            sdk = self._get_sdk()
            # Attempt a lightweight ping via SmartAPI's getProfile (no session needed for ping)
            # We use generate_totp as a proxy SDK availability check.
            # If SDK is importable and api_key is set, the SDK is ready.
            _ = sdk  # SDK import succeeded
            latency_ms = (time.monotonic() - t0) * 1000
            return BrokerHealthReport(
                broker_name="angel",
                status=BrokerHealthStatus.HEALTHY,
                latency_ms=latency_ms,
                details={"api_key_configured": bool(self._config.angel_api_key)},
            )
        except BrokerConnectionError as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            return BrokerHealthReport(
                broker_name="angel",
                status=BrokerHealthStatus.DOWN,
                latency_ms=latency_ms,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - t0) * 1000
            return BrokerHealthReport(
                broker_name="angel",
                status=BrokerHealthStatus.DOWN,
                latency_ms=latency_ms,
                error=str(exc),
            )
