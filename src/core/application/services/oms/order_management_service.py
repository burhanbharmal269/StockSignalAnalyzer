"""OrderManagementService — receives SignalRiskApproved and creates orders.

Responsibilities:
  1. Consume SignalRiskApproved event
  2. Idempotency check (Redis SET NX)
  3. Signal TTL check
  4. Kill switch check
  5. Rate limit check
  6. Create Order entity (PENDING)
  7. Persist Order (persistence-first — must succeed before routing)
  8. Publish OrderCreated event
  9. Route via OrderRouterService

Mandatory invariants:
  - Persistence-first: Order saved before broker call
  - Fail-closed: Broker unavailable → no order placed
  - Idempotent: same signal_id → single order only
  - Signal expiration respected: expired signals create no order
"""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.entities.order import Order
from core.domain.enums.order_type import OrderType
from core.domain.enums.product_type import ProductType
from core.domain.enums.trading_mode import TradingMode
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.events.order_events import (
    OrderCreated,
    OrderIdempotencyBlocked,
    OrderKillSwitchBlocked,
    OrderTtlExpired,
)
from core.domain.events.signal_events import SignalRiskApproved
from core.domain.exceptions.order import (
    KillSwitchActiveError,
    OrderPersistenceError,
    OrderRateLimitError,
    SignalExpiredError,
)
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_kill_switch_repository import IKillSwitchRepository
from core.domain.interfaces.i_order_cache_repository import IOrderCacheRepository
from core.domain.interfaces.i_order_repository import IOrderRepository
from core.domain.value_objects.order_request import OrderRequest
from core.domain.value_objects.order_result import OrderResult
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.config.oms_config import OmsConfig

_log = logging.getLogger(__name__)

_RATE_LIMIT_WINDOW_SECONDS = 60


class OrderManagementService:
    """Entry point for OMS order creation.

    Processes one SignalRiskApproved event per call.
    All pre-submission checks are synchronous and fail-closed.
    """

    def __init__(
        self,
        order_repository: IOrderRepository,
        order_cache: IOrderCacheRepository,
        kill_switch_repository: IKillSwitchRepository,
        event_bus: IEventBus,
        config: OmsConfig,
    ) -> None:
        self._repo = order_repository
        self._cache = order_cache
        self._kill_switch = kill_switch_repository
        self._bus = event_bus
        self._config = config
        # In-memory rate limiter — timestamps of recent orders this process
        self._recent_order_times: list[datetime] = []

    async def process(self, request: OrderRequest) -> OrderResult:
        """Process one SignalRiskApproved event into an order.

        Returns OrderResult. Never raises except OrderPersistenceError (hard fail).
        """
        try:
            return await self._process_internal(request)
        except OrderPersistenceError:
            raise  # Hard infrastructure failure — caller must handle
        except (KillSwitchActiveError, SignalExpiredError, OrderRateLimitError):
            raise  # Domain rejections propagate to caller for logging
        except Exception:
            _log.exception(
                "Unexpected error in OrderManagementService.process for signal_id=%s",
                request.signal_id,
            )
            raise

    async def process_signal_risk_approved(
        self, event: SignalRiskApproved
    ) -> OrderResult:
        """Convenience entry point from event handler."""
        request = _event_to_request(event)
        return await self.process(request)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _process_internal(self, request: OrderRequest) -> OrderResult:
        # ── 1. Signal TTL check ────────────────────────────────────────
        if request.is_expired:
            _log.warning(
                "Signal %s expired (valid_until=%s) — no order created",
                request.signal_id,
                request.valid_until,
            )
            await self._publish_safe(
                OrderTtlExpired(
                    signal_id=request.signal_id,
                    signal_valid_until=request.valid_until,
                    correlation_id=request.correlation_id,
                )
            )
            raise SignalExpiredError(
                f"Signal {request.signal_id} expired at {request.valid_until}"
            )

        # ── 2. Idempotency check ───────────────────────────────────────
        is_new = await self._cache.set_idempotency_key(
            signal_id=request.signal_id,
            order_id=_sentinel_uuid(),  # placeholder; replaced if new order is created
            ttl_seconds=self._config.idempotency_ttl_seconds,
        )
        if not is_new:
            existing_order_id = await self._cache.get_idempotency_order_id(
                request.signal_id
            )
            _log.info(
                "Duplicate signal_id=%s — existing order_id=%s (idempotency block)",
                request.signal_id,
                existing_order_id,
            )
            await self._publish_safe(
                OrderIdempotencyBlocked(
                    signal_id=request.signal_id,
                    original_order_id=existing_order_id or _sentinel_uuid(),
                    correlation_id=request.correlation_id,
                )
            )
            return OrderResult(
                accepted=False,
                order_id=existing_order_id,
                signal_id=request.signal_id,
                state=_DUPLICATE_STATE,
                is_duplicate=True,
                rejection_reason="duplicate_signal_id",
            )

        # ── 3. Kill switch check ───────────────────────────────────────
        ks_state = await self._kill_switch.get_state()
        if ks_state.is_active:
            _log.warning(
                "Kill switch active — blocking order for signal_id=%s (activated_at=%s)",
                request.signal_id,
                ks_state.activated_at,
            )
            await self._publish_safe(
                OrderKillSwitchBlocked(
                    signal_id=request.signal_id,
                    kill_switch_activated_at=ks_state.activated_at,
                    correlation_id=request.correlation_id,
                )
            )
            raise KillSwitchActiveError(
                f"Kill switch is active (since {ks_state.activated_at}) — "
                f"order for signal {request.signal_id} rejected"
            )

        # ── 4. Rate limit check ────────────────────────────────────────
        self._check_rate_limit()

        # ── 5. Create Order entity ─────────────────────────────────────
        order = self._build_order(request)

        # ── 6. Persistence-first ───────────────────────────────────────
        await self._persist(order)

        # ── 7. Publish OrderCreated ────────────────────────────────────
        await self._publish_safe(
            OrderCreated(
                order_id=order.order_id,
                signal_id=order.signal_id,
                instrument_token=order.instrument_token,
                underlying=request.underlying,
                tradingsymbol=order.tradingsymbol,
                direction=request.direction,
                quantity=order.quantity,
                lots=order.lots,
                order_type=order.order_type.value,
                transaction_type=order.transaction_type.value,
                product=order.product.value,
                trading_mode=order.trading_mode.value,
                correlation_id=request.correlation_id,
            )
        )

        # Update idempotency key with real order_id
        await self._cache.set_idempotency_key(
            signal_id=request.signal_id,
            order_id=order.order_id,
            ttl_seconds=self._config.idempotency_ttl_seconds,
        )

        # Record for rate limiting
        self._recent_order_times.append(datetime.now(UTC))

        return OrderResult(
            accepted=True,
            order_id=order.order_id,
            signal_id=request.signal_id,
            state=order.state,
        )

    def _build_order(self, request: OrderRequest) -> Order:
        """Translate OrderRequest into an Order entity."""
        order_type = self._select_order_type(request)
        transaction_type = (
            TransactionType.BUY if request.is_long else TransactionType.SELL
        )
        validity = Validity.IOC if order_type == OrderType.LIMIT else Validity.DAY
        limit_price: Price | None = None
        if order_type == OrderType.LIMIT:
            buffer = self._config.order_type.limit_buffer_pct
            if request.is_long:
                lp = request.entry_price * Decimal(str(1 + buffer))
            else:
                lp = request.entry_price * Decimal(str(1 - buffer))
            limit_price = Price(lp)

        return Order.create(
            signal_id=request.signal_id,
            symbol=Symbol(request.underlying, request.exchange),
            quantity=request.quantity,
            limit_price=limit_price,
            risk_decision_id=request.risk_decision_id,
            instrument_token=request.instrument_token,
            tradingsymbol=request.tradingsymbol,
            transaction_type=transaction_type,
            order_type=order_type,
            product=ProductType.MIS,  # FnO intraday only
            lots=request.position_size_lots,
            validity=validity,
            trading_mode=TradingMode(request.trading_mode),
        )

    def _select_order_type(self, request: OrderRequest) -> OrderType:
        """Choose MARKET vs LIMIT based on option premium and config."""
        threshold = self._config.order_type.limit_threshold_premium
        if request.option_premium is not None and request.option_premium > threshold:
            return OrderType.LIMIT
        if self._config.order_type.default == "LIMIT":
            return OrderType.LIMIT
        return OrderType.MARKET

    def _check_rate_limit(self) -> None:
        now = datetime.now(UTC)
        cutoff = now.timestamp() - _RATE_LIMIT_WINDOW_SECONDS
        self._recent_order_times = [
            t for t in self._recent_order_times if t.timestamp() > cutoff
        ]
        if len(self._recent_order_times) >= self._config.max_orders_per_minute:
            raise OrderRateLimitError(
                f"Rate limit exceeded: {len(self._recent_order_times)} orders "
                f"in last {_RATE_LIMIT_WINDOW_SECONDS}s "
                f"(max={self._config.max_orders_per_minute})"
            )

    async def _persist(self, order: Order) -> None:
        try:
            await self._repo.save(order)
        except Exception as exc:
            raise OrderPersistenceError(
                f"Failed to persist order {order.order_id}: {exc}"
            ) from exc

    async def _publish_safe(self, event: object) -> None:
        try:
            await self._bus.publish(event)
        except Exception:
            _log.warning("Event publish failed for %s — continuing", type(event).__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

from core.domain.enums.order_state import OrderState as _OrderState  # noqa: E402

_DUPLICATE_STATE = _OrderState.PENDING


def _sentinel_uuid() -> _uuid.UUID:
    return _uuid.UUID("00000000-0000-0000-0000-000000000000")


def _event_to_request(event: SignalRiskApproved) -> OrderRequest:
    """Convert SignalRiskApproved into an OrderRequest."""
    return OrderRequest(
        signal_id=event.signal_id,
        instrument_token=event.instrument_token,
        underlying=event.underlying,
        # tradingsymbol resolved from InstrumentMaster at execution time
        tradingsymbol=event.underlying,
        exchange="NFO",
        direction=event.direction,
        strategy_type=event.strategy_type,
        regime=event.regime,
        position_size_lots=event.position_size_lots,
        lot_size=1,
        entry_price=Decimal("0"),
        stop_loss_price=Decimal("0"),
        target_1_price=Decimal("0"),
        target_2_price=None,
        option_premium=None,
        risk_decision_id=event.risk_decision_id,
        adjusted_score=event.adjusted_score,
        final_confidence=event.final_confidence,
        valid_until=event.valid_until,
        correlation_id=event.correlation_id,
    )
