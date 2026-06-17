"""PaperBrokerAdapter — in-memory IBroker implementation for paper trading.

Simulates broker behaviour without touching real money or a real exchange.
Fill price = LTP ± 0.05% slippage (BUY pays more, SELL receives less).
LTP is injected via set_ltp() for test control; defaults to 100 when unknown.

Reference: docs/08_DEVELOPMENT_ROADMAP.md Phase 8
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.entities.broker_session import BrokerSession
from core.domain.exceptions.broker import BrokerOrderError, BrokerSessionExpiredError
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
    pass

logger = get_logger(__name__)

_SLIPPAGE = Decimal("0.0005")
_DEFAULT_LTP = Decimal("100")
_PAPER_SESSION_EXPIRY = datetime(2099, 12, 31, tzinfo=UTC)


class PaperBrokerAdapter(IBroker):
    """In-memory broker for paper trading mode.

    State is kept in instance-level dicts. A fresh instance always starts
    with a clean slate (no persistence between restarts).

    Thread-safety: this adapter is not thread-safe; use asyncio single-event-
    loop access only.
    """

    def __init__(self, initial_capital: Decimal = Decimal("1000000")) -> None:
        self._orders: dict[str, dict] = {}
        self._positions: dict[str, dict] = {}
        self._ltp: dict[str, Decimal] = {}
        self._order_counter: int = 0
        self._trade_counter: int = 0
        self._initial_capital: Decimal = initial_capital
        self._used_margin: Decimal = Decimal("0")

    @property
    def broker_name(self) -> str:
        return "paper"

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def login(
        self,
        api_key: str,
        request_token: str,
        api_secret: str,
    ) -> BrokerSession:
        logger.info("paper_broker.login")
        return BrokerSession.create(
            broker_name="paper",
            api_key=api_key,
            encrypted_access_token="paper_mode_no_encryption_needed",  # noqa: S106
            expires_at=_PAPER_SESSION_EXPIRY,
        )

    async def logout(self, session: BrokerSession) -> None:
        logger.info("paper_broker.logout")
        session.deactivate()

    async def get_profile(self, session: BrokerSession) -> BrokerProfile:
        return BrokerProfile(
            user_id="PAPER_USER",
            full_name="Paper Trader",
            email="paper@localhost",
            broker_name="paper",
        )

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def place_order(
        self,
        session: BrokerSession,
        request: BrokerOrderRequest,
    ) -> str:
        self._check_session(session)
        self._order_counter += 1
        self._trade_counter += 1
        order_id = f"PAPER-{self._order_counter:08d}"
        trade_id = f"PAPERTRADE-{self._trade_counter:08d}"

        ltp = self._ltp.get(f"{request.exchange}:{request.symbol}", _DEFAULT_LTP)
        fill_price = self._compute_fill_price(request, ltp)

        now = datetime.now(UTC)
        self._orders[order_id] = {
            "broker_order_id": order_id,
            "trade_id": trade_id,
            "symbol": request.symbol,
            "exchange": request.exchange,
            "direction": request.direction,
            "quantity": request.quantity,
            "filled_quantity": request.quantity,
            "status": "COMPLETE",
            "order_type": request.order_type,
            "product": request.product,
            "limit_price": request.limit_price,
            "average_price": fill_price,
            "placed_at": now,
        }

        self._update_position(request, fill_price)
        # Track used margin: 20% of notional for INTRADAY, 100% for others
        notional = fill_price * request.quantity
        margin_factor = Decimal("0.2") if request.product == "INTRADAY" else Decimal("1.0")
        if request.direction == "BUY":
            self._used_margin += notional * margin_factor
        else:
            self._used_margin = max(Decimal("0"), self._used_margin - notional * margin_factor)
        logger.info(
            "paper_broker.place_order",
            order_id=order_id,
            symbol=request.symbol,
            direction=request.direction,
            quantity=request.quantity,
            fill_price=str(fill_price),
        )
        return order_id

    async def modify_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
        quantity: int | None = None,
        limit_price: Decimal | None = None,
        trigger_price: Decimal | None = None,
    ) -> None:
        self._check_session(session)
        if broker_order_id not in self._orders:
            msg = f"Order {broker_order_id} not found."
            raise BrokerOrderError(msg)
        order = self._orders[broker_order_id]
        if order["status"] != "OPEN":
            msg = f"Cannot modify order {broker_order_id} with status {order['status']}."
            raise BrokerOrderError(msg)
        if quantity is not None:
            order["quantity"] = quantity
        if limit_price is not None:
            order["limit_price"] = limit_price

    async def cancel_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
    ) -> None:
        self._check_session(session)
        if broker_order_id not in self._orders:
            msg = f"Order {broker_order_id} not found."
            raise BrokerOrderError(msg)
        self._orders[broker_order_id]["status"] = "CANCELLED"
        logger.info("paper_broker.cancel_order", order_id=broker_order_id)

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def get_positions(self, session: BrokerSession) -> list[BrokerPosition]:
        self._check_session(session)
        positions = []
        for key, pos in self._positions.items():
            if pos["quantity"] != 0:
                ltp = self._ltp.get(key, pos["average_price"])
                qty = pos["quantity"]
                avg = pos["average_price"]
                pnl = (ltp - avg) * qty if qty > 0 else (avg - ltp) * abs(qty)
                positions.append(
                    BrokerPosition(
                        symbol=pos["symbol"],
                        exchange=pos["exchange"],
                        product=pos["product"],
                        quantity=abs(qty),
                        average_price=avg,
                        last_price=ltp,
                        pnl=pnl,
                        net_quantity=qty,
                    )
                )
        return positions

    async def get_holdings(self, session: BrokerSession) -> list[BrokerHolding]:
        self._check_session(session)
        return []

    async def get_orders(self, session: BrokerSession) -> list[BrokerOrder]:
        self._check_session(session)
        return [
            BrokerOrder(
                broker_order_id=o["broker_order_id"],
                symbol=o["symbol"],
                exchange=o["exchange"],
                direction=o["direction"],
                quantity=o["quantity"],
                filled_quantity=o["filled_quantity"],
                status=o["status"],
                order_type=o["order_type"],
                product=o["product"],
                limit_price=o.get("limit_price"),
                average_price=o.get("average_price"),
                placed_at=o["placed_at"],
            )
            for o in self._orders.values()
        ]

    async def get_trades(self, session: BrokerSession) -> list[BrokerTrade]:
        self._check_session(session)
        return [
            BrokerTrade(
                trade_id=o["trade_id"],
                broker_order_id=o["broker_order_id"],
                symbol=o["symbol"],
                exchange=o["exchange"],
                direction=o["direction"],
                quantity=o["filled_quantity"],
                price=o["average_price"],
                traded_at=o["placed_at"],
            )
            for o in self._orders.values()
            if o["status"] == "COMPLETE"
        ]

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_ltp(
        self,
        session: BrokerSession,
        instruments: list[str],
    ) -> dict[str, Decimal]:
        self._check_session(session)
        return {inst: self._ltp.get(inst, _DEFAULT_LTP) for inst in instruments}

    async def get_option_chain(
        self,
        session: BrokerSession,
        symbol: str,
        expiry: date,
    ) -> list[OptionChainEntry]:
        self._check_session(session)
        return []

    # ------------------------------------------------------------------
    # Phase 16 additions
    # ------------------------------------------------------------------

    async def connect(self, session: BrokerSession) -> None:
        self._check_session(session)
        logger.info("paper_broker.connect")

    async def disconnect(self, session: BrokerSession) -> None:
        logger.info("paper_broker.disconnect")

    async def get_order(
        self,
        session: BrokerSession,
        broker_order_id: str,
    ) -> BrokerOrder | None:
        self._check_session(session)
        o = self._orders.get(broker_order_id)
        if o is None:
            return None
        return BrokerOrder(
            broker_order_id=o["broker_order_id"],
            symbol=o["symbol"],
            exchange=o["exchange"],
            direction=o["direction"],
            quantity=o["quantity"],
            filled_quantity=o["filled_quantity"],
            status=o["status"],
            order_type=o["order_type"],
            product=o["product"],
            limit_price=o.get("limit_price"),
            average_price=o.get("average_price"),
            placed_at=o["placed_at"],
        )

    async def get_position(
        self,
        session: BrokerSession,
        symbol: str,
        exchange: str,
    ) -> BrokerPosition | None:
        self._check_session(session)
        key = f"{exchange}:{symbol}"
        pos = self._positions.get(key)
        if pos is None or pos["quantity"] == 0:
            return None
        ltp = self._ltp.get(key, pos["average_price"])
        qty = pos["quantity"]
        avg = pos["average_price"]
        pnl = (ltp - avg) * qty if qty > 0 else (avg - ltp) * abs(qty)
        return BrokerPosition(
            symbol=pos["symbol"],
            exchange=pos["exchange"],
            product=pos["product"],
            quantity=abs(qty),
            average_price=avg,
            last_price=ltp,
            pnl=pnl,
            net_quantity=qty,
        )

    async def get_margin(self, session: BrokerSession) -> BrokerMargin:
        self._check_session(session)
        available = self._initial_capital - self._used_margin
        return BrokerMargin(
            available_cash=available,
            used_margin=self._used_margin,
            total_margin=self._initial_capital,
            segment="equity",
        )

    async def health_check(self) -> BrokerHealthReport:
        return BrokerHealthReport(
            broker_name="paper",
            status=BrokerHealthStatus.HEALTHY,
            latency_ms=0.0,
            details={"mode": "paper", "in_memory": True},
        )

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def set_ltp(self, exchange: str, symbol: str, price: Decimal) -> None:
        """Inject a simulated LTP for use in paper fills and get_ltp()."""
        self._ltp[f"{exchange}:{symbol}"] = price

    def simulate_partial_fill(
        self,
        broker_order_id: str,
        filled_qty: int,
    ) -> None:
        """Inject a partial fill for a pending order — test helper."""
        order = self._orders.get(broker_order_id)
        if order is None:
            msg = f"Order {broker_order_id} not found."
            raise BrokerOrderError(msg)
        order["filled_quantity"] = filled_qty
        remaining = order["quantity"] - filled_qty
        order["status"] = "OPEN" if remaining > 0 else "COMPLETE"

    def reset(self) -> None:
        """Clear all state — use between test cases."""
        self._orders.clear()
        self._positions.clear()
        self._ltp.clear()
        self._order_counter = 0
        self._trade_counter = 0
        self._used_margin = Decimal("0")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_session(self, session: BrokerSession) -> None:
        if session.is_expired():
            msg = f"Paper session {session.session_id} has expired."
            raise BrokerSessionExpiredError(msg)

    @staticmethod
    def _compute_fill_price(request: BrokerOrderRequest, ltp: Decimal) -> Decimal:
        if request.order_type in ("LIMIT", "SL_LIMIT") and request.limit_price:
            return request.limit_price
        slippage = ltp * _SLIPPAGE
        if request.direction == "BUY":
            return (ltp + slippage).quantize(Decimal("0.05"))
        return (ltp - slippage).quantize(Decimal("0.05"))

    def _update_position(self, request: BrokerOrderRequest, fill_price: Decimal) -> None:
        key = f"{request.exchange}:{request.symbol}"
        if key not in self._positions:
            self._positions[key] = {
                "symbol": request.symbol,
                "exchange": request.exchange,
                "product": request.product,
                "quantity": 0,
                "average_price": Decimal("0"),
            }
        pos = self._positions[key]
        qty = request.quantity if request.direction == "BUY" else -request.quantity
        new_qty = pos["quantity"] + qty

        if new_qty == 0:
            pos["quantity"] = 0
            pos["average_price"] = Decimal("0")
        elif (pos["quantity"] >= 0 and qty > 0) or (pos["quantity"] <= 0 and qty < 0):
            total_cost = pos["average_price"] * pos["quantity"] + fill_price * qty
            pos["quantity"] = new_qty
            pos["average_price"] = (total_cost / new_qty).quantize(Decimal("0.01"))
        else:
            pos["quantity"] = new_qty
            if new_qty != 0:
                pos["average_price"] = pos["average_price"]
