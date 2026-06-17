"""Unit tests — Order entity Phase 15 extensions.

Tests the new fields, lifecycle methods (submitted_at, filled_at, cancelled_at),
is_terminal property, is_stop_loss_order property, and backward compatibility
with the existing Order.create() factory.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.domain.entities.order import Order
from core.domain.enums.order_state import OrderState
from core.domain.enums.order_type import OrderType
from core.domain.enums.product_type import ProductType
from core.domain.enums.trading_mode import TradingMode
from core.domain.enums.transaction_type import TransactionType
from core.domain.enums.validity import Validity
from core.domain.exceptions.order import OrderStateError
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol


def _make_order(**overrides) -> Order:
    defaults = {
        "signal_id": uuid.uuid4(),
        "symbol": Symbol("NIFTY", "NFO"),
        "quantity": 50,
        "limit_price": None,
        "instrument_token": 12345,
        "tradingsymbol": "NIFTY24JAN18000CE",
        "transaction_type": TransactionType.BUY,
        "order_type": OrderType.MARKET,
        "product": ProductType.MIS,
        "lots": 1,
        "validity": Validity.DAY,
        "trading_mode": TradingMode.LIVE,
        "risk_decision_id": 42,
    }
    defaults.update(overrides)
    return Order.create(**defaults)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_create_with_only_required_args(self):
        order = Order.create(
            signal_id=uuid.uuid4(),
            symbol=Symbol("NIFTY", "NFO"),
            quantity=50,
        )
        assert order.state == OrderState.PENDING
        assert order.order_type == OrderType.MARKET
        assert order.trading_mode == TradingMode.LIVE

    def test_all_phase15_fields_have_defaults(self):
        order = Order.create(
            signal_id=uuid.uuid4(),
            symbol=Symbol("NIFTY", "NFO"),
            quantity=50,
        )
        assert order.risk_decision_id is None
        assert order.instrument_token == 0
        assert order.tradingsymbol == ""
        assert order.transaction_type == TransactionType.BUY
        assert order.lots == 0
        assert order.trigger_price is None
        assert order.validity == Validity.DAY
        assert order.parent_position_id is None


# ---------------------------------------------------------------------------
# Phase 15 fields
# ---------------------------------------------------------------------------

class TestPhase15Fields:
    def test_fields_persisted_in_factory(self):
        order = _make_order()
        assert order.instrument_token == 12345
        assert order.tradingsymbol == "NIFTY24JAN18000CE"
        assert order.transaction_type == TransactionType.BUY
        assert order.order_type == OrderType.MARKET
        assert order.product == ProductType.MIS
        assert order.lots == 1
        assert order.validity == Validity.DAY
        assert order.trading_mode == TradingMode.LIVE
        assert order.risk_decision_id == 42

    def test_limit_price_stored(self):
        order = _make_order(
            order_type=OrderType.LIMIT,
            limit_price=Price(Decimal("210")),
        )
        assert order.limit_price.value == Decimal("210")

    def test_trigger_price_stored(self):
        order = _make_order(
            order_type=OrderType.SL_MARKET,
            trigger_price=Price(Decimal("195")),
        )
        assert order.trigger_price.value == Decimal("195")

    def test_parent_position_id_stored(self):
        pid = uuid.uuid4()
        order = _make_order(parent_position_id=pid)
        assert order.parent_position_id == pid


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

class TestTimestamps:
    def test_submitted_at_set_on_confirm_submitted(self):
        order = _make_order()
        order.start_submission()
        before = datetime.now(UTC)
        order.confirm_submitted("BROKER-001")
        after = datetime.now(UTC)
        assert before <= order.submitted_at <= after

    def test_filled_at_set_on_record_fill(self):
        order = _make_order()
        order.start_submission()
        order.confirm_submitted("BROKER-001")
        order.open_at_exchange()
        before = datetime.now(UTC)
        order.record_fill(50, Price(Decimal("200")))
        after = datetime.now(UTC)
        assert before <= order.filled_at <= after

    def test_cancelled_at_set_on_cancel(self):
        order = _make_order()
        before = datetime.now(UTC)
        order.cancel("test cancel")
        after = datetime.now(UTC)
        assert before <= order.cancelled_at <= after

    def test_submitted_at_none_before_submission(self):
        order = _make_order()
        assert order.submitted_at is None

    def test_filled_at_none_before_fill(self):
        order = _make_order()
        assert order.filled_at is None


# ---------------------------------------------------------------------------
# is_terminal
# ---------------------------------------------------------------------------

class TestIsTerminal:
    @pytest.mark.parametrize("terminal_state", [
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.REJECTED_PRE_SUBMIT,
        OrderState.EXPIRED,
    ])
    def test_terminal_states(self, terminal_state):
        order = _make_order()
        object.__setattr__(order, "state", terminal_state)
        assert order.is_terminal is True

    @pytest.mark.parametrize("non_terminal_state", [
        OrderState.PENDING,
        OrderState.SUBMITTING,
        OrderState.SUBMITTED,
        OrderState.OPEN,
        OrderState.PARTIALLY_FILLED,
    ])
    def test_non_terminal_states(self, non_terminal_state):
        order = _make_order()
        object.__setattr__(order, "state", non_terminal_state)
        assert order.is_terminal is False


# ---------------------------------------------------------------------------
# is_stop_loss_order
# ---------------------------------------------------------------------------

class TestIsStopLossOrder:
    def test_sl_market_is_stop_loss(self):
        order = _make_order(order_type=OrderType.SL_MARKET)
        assert order.is_stop_loss_order is True

    def test_sl_is_stop_loss(self):
        order = _make_order(
            order_type=OrderType.SL,
            trigger_price=Price(Decimal("195")),
            limit_price=Price(Decimal("193")),
        )
        assert order.is_stop_loss_order is True

    def test_market_is_not_stop_loss(self):
        order = _make_order(order_type=OrderType.MARKET)
        assert order.is_stop_loss_order is False

    def test_limit_is_not_stop_loss(self):
        order = _make_order(
            order_type=OrderType.LIMIT,
            limit_price=Price(Decimal("210")),
        )
        assert order.is_stop_loss_order is False


# ---------------------------------------------------------------------------
# State machine (regression from Phase 15 additions)
# ---------------------------------------------------------------------------

class TestStateMachine:
    def test_invalid_transition_raises(self):
        order = _make_order()
        with pytest.raises(OrderStateError):
            order.record_fill(50, Price(Decimal("200")))  # PENDING → FILLED invalid

    def test_full_lifecycle(self):
        order = _make_order()
        order.start_submission()
        order.confirm_submitted("BROKER-001")
        order.open_at_exchange()
        order.record_fill(50, Price(Decimal("200")))
        assert order.state == OrderState.FILLED
        assert order.filled_quantity == 50
        assert order.average_fill_price.value == Decimal("200")

    def test_reject_pre_submit_from_submitting(self):
        order = _make_order()
        order.start_submission()
        order.reject_pre_submit("broker_unavailable")
        assert order.state == OrderState.REJECTED_PRE_SUBMIT
        assert order.rejection_reason == "broker_unavailable"

    def test_expire_from_open(self):
        order = _make_order()
        order.start_submission()
        order.confirm_submitted("B-001")
        order.open_at_exchange()
        order.expire()
        assert order.state == OrderState.EXPIRED

    def test_remaining_quantity(self):
        order = _make_order(quantity=50)
        order.start_submission()
        order.confirm_submitted("B-001")
        order.open_at_exchange()
        order.record_partial_fill(25, Price(Decimal("200")))
        assert order.remaining_quantity == 25
