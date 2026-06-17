"""Order entity — OMS order lifecycle.

State machine from docs/22_OMS_DESIGN.md.
Every transition is strict — OrderStateError on invalid move.

Persistence-first invariant: Order must be saved to DB before routing to broker.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.order_state import VALID_ORDER_TRANSITIONS, OrderState
from core.domain.enums.order_type import OrderType
from core.domain.enums.product_type import ProductType
from core.domain.enums.trading_mode import TradingMode
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.exceptions.order import OrderStateError
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol


@dataclass
class Order:
    """OMS order from PENDING through terminal state.

    Idempotency key is signal_id — OMS checks Redis before creating an Order.
    `filled_quantity` reaches `quantity` only when state == FILLED.

    Persistence-first: save() must be called before place_order().
    """

    order_id: uuid.UUID
    signal_id: uuid.UUID
    symbol: Symbol
    quantity: int
    # Entry: MARKET orders set limit_price=None
    limit_price: Price | None

    # Phase 15 enrichment — all default-safe for backward compat with existing tests
    risk_decision_id: int | None = field(default=None)
    instrument_token: int = field(default=0)
    tradingsymbol: str = field(default="")
    transaction_type: TransactionType = field(default=TransactionType.BUY)
    order_type: OrderType = field(default=OrderType.MARKET)
    product: ProductType = field(default=ProductType.MIS)
    lots: int = field(default=0)
    trigger_price: Price | None = field(default=None)
    validity: Validity = field(default=Validity.DAY)
    trading_mode: TradingMode = field(default=TradingMode.LIVE)
    parent_position_id: uuid.UUID | None = field(default=None)

    # Mutable state
    state: OrderState = field(default=OrderState.PENDING)
    broker_order_id: str = field(default="")
    filled_quantity: int = field(default=0)
    average_fill_price: Price | None = field(default=None)
    rejection_reason: str = field(default="")

    # Phase 17 audit fields — nullable for backward compat
    risk_profile_id: uuid.UUID | None = field(default=None)
    allocation_id: uuid.UUID | None = field(default=None)
    portfolio_id: uuid.UUID | None = field(default=None)
    capital_source_mode: CapitalSourceMode | None = field(default=None)
    effective_capital: Decimal | None = field(default=None)
    effective_margin: Decimal | None = field(default=None)

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    submitted_at: datetime | None = field(default=None)
    filled_at: datetime | None = field(default=None)
    cancelled_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            msg = f"Order quantity must be > 0, got {self.quantity}"
            raise ValueError(msg)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _transition_to(self, new_state: OrderState) -> None:
        allowed = VALID_ORDER_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise OrderStateError(self.state, new_state)
        self.state = new_state
        self.updated_at = datetime.now(UTC)

    # ------------------------------------------------------------------
    # Lifecycle methods
    # ------------------------------------------------------------------

    def start_submission(self) -> None:
        """PENDING → SUBMITTING."""
        self._transition_to(OrderState.SUBMITTING)

    def confirm_submitted(self, broker_order_id: str) -> None:
        """SUBMITTING → SUBMITTED."""
        self.broker_order_id = broker_order_id
        self.submitted_at = datetime.now(UTC)
        self._transition_to(OrderState.SUBMITTED)

    def reject_pre_submit(self, reason: str) -> None:
        """SUBMITTING → REJECTED_PRE_SUBMIT (kill switch, TTL, rate limit)."""
        self.rejection_reason = reason
        self._transition_to(OrderState.REJECTED_PRE_SUBMIT)

    def open_at_exchange(self) -> None:
        """SUBMITTED → OPEN."""
        self._transition_to(OrderState.OPEN)

    def record_partial_fill(self, filled_qty: int, avg_price: Price) -> None:
        """OPEN → PARTIALLY_FILLED."""
        if filled_qty <= 0 or filled_qty >= self.quantity:
            msg = (
                f"Partial fill quantity must be in (0, {self.quantity}), "
                f"got {filled_qty}"
            )
            raise ValueError(msg)
        self.filled_quantity = filled_qty
        self.average_fill_price = avg_price
        self._transition_to(OrderState.PARTIALLY_FILLED)

    def record_fill(self, filled_qty: int, avg_price: Price) -> None:
        """OPEN | PARTIALLY_FILLED → FILLED."""
        self.filled_quantity = filled_qty
        self.average_fill_price = avg_price
        self.filled_at = datetime.now(UTC)
        self._transition_to(OrderState.FILLED)

    def cancel(self, reason: str = "") -> None:
        """PENDING | OPEN | PARTIALLY_FILLED → CANCELLED."""
        self.rejection_reason = reason
        self.cancelled_at = datetime.now(UTC)
        self._transition_to(OrderState.CANCELLED)

    def reject(self, reason: str) -> None:
        """OPEN → REJECTED (exchange rejection)."""
        self.rejection_reason = reason
        self._transition_to(OrderState.REJECTED)

    def expire(self) -> None:
        """OPEN → EXPIRED."""
        self._transition_to(OrderState.EXPIRED)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def is_fully_filled(self) -> bool:
        return self.state == OrderState.FILLED

    @property
    def is_terminal(self) -> bool:
        return self.state.is_terminal

    @property
    def is_stop_loss_order(self) -> bool:
        return self.order_type in (OrderType.SL, OrderType.SL_MARKET)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        signal_id: uuid.UUID,
        symbol: Symbol,
        quantity: int,
        limit_price: Price | None = None,
        *,
        risk_decision_id: int | None = None,
        instrument_token: int = 0,
        tradingsymbol: str = "",
        transaction_type: TransactionType = TransactionType.BUY,
        order_type: OrderType = OrderType.MARKET,
        product: ProductType = ProductType.MIS,
        lots: int = 0,
        trigger_price: Price | None = None,
        validity: Validity = Validity.DAY,
        trading_mode: TradingMode = TradingMode.LIVE,
        parent_position_id: uuid.UUID | None = None,
    ) -> Order:
        return cls(
            order_id=uuid.uuid4(),
            signal_id=signal_id,
            symbol=symbol,
            quantity=quantity,
            limit_price=limit_price,
            risk_decision_id=risk_decision_id,
            instrument_token=instrument_token,
            tradingsymbol=tradingsymbol,
            transaction_type=transaction_type,
            order_type=order_type,
            product=product,
            lots=lots,
            trigger_price=trigger_price,
            validity=validity,
            trading_mode=trading_mode,
            parent_position_id=parent_position_id,
        )
