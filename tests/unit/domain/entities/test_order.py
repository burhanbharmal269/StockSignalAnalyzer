"""Unit tests for Order entity state machine — every valid and invalid transition tested."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.domain.entities.order import Order
from core.domain.enums.order_state import OrderState
from core.domain.exceptions.order import OrderStateError
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol


def _make_order(state: OrderState = OrderState.PENDING) -> Order:
    o = Order.create(
        signal_id=uuid.uuid4(),
        symbol=Symbol("NIFTY"),
        quantity=50,
        limit_price=Price(Decimal("19500")),
    )
    o.state = state
    return o


def _submitting_order() -> Order:
    o = _make_order()
    o.start_submission()
    return o


def _submitted_order() -> Order:
    o = _submitting_order()
    o.confirm_submitted("broker_123")
    return o


def _open_order() -> Order:
    o = _submitted_order()
    o.open_at_exchange()
    return o


class TestOrderFactory:
    def test_create_sets_pending_state(self) -> None:
        o = Order.create(signal_id=uuid.uuid4(), symbol=Symbol("NIFTY"), quantity=50)
        assert o.state == OrderState.PENDING

    def test_zero_quantity_raises(self) -> None:
        with pytest.raises(ValueError):
            Order.create(signal_id=uuid.uuid4(), symbol=Symbol("NIFTY"), quantity=0)

    def test_negative_quantity_raises(self) -> None:
        with pytest.raises(ValueError):
            Order.create(signal_id=uuid.uuid4(), symbol=Symbol("NIFTY"), quantity=-10)


class TestValidTransitions:
    def test_pending_to_submitting(self) -> None:
        o = _make_order()
        o.start_submission()
        assert o.state == OrderState.SUBMITTING

    def test_pending_to_cancelled(self) -> None:
        o = _make_order()
        o.cancel("user requested")
        assert o.state == OrderState.CANCELLED

    def test_submitting_to_submitted(self) -> None:
        o = _submitting_order()
        o.confirm_submitted("broker_abc")
        assert o.state == OrderState.SUBMITTED
        assert o.broker_order_id == "broker_abc"

    def test_submitting_to_rejected_pre_submit(self) -> None:
        o = _submitting_order()
        o.reject_pre_submit("kill switch active")
        assert o.state == OrderState.REJECTED_PRE_SUBMIT
        assert o.rejection_reason == "kill switch active"

    def test_submitted_to_open(self) -> None:
        o = _submitted_order()
        o.open_at_exchange()
        assert o.state == OrderState.OPEN

    def test_open_to_filled(self) -> None:
        o = _open_order()
        o.record_fill(50, Price(Decimal("19510")))
        assert o.state == OrderState.FILLED
        assert o.filled_quantity == 50

    def test_open_to_partially_filled(self) -> None:
        o = _open_order()
        o.record_partial_fill(25, Price(Decimal("19505")))
        assert o.state == OrderState.PARTIALLY_FILLED
        assert o.filled_quantity == 25

    def test_partially_filled_to_filled(self) -> None:
        o = _open_order()
        o.record_partial_fill(25, Price(Decimal("19505")))
        o.record_fill(50, Price(Decimal("19510")))
        assert o.state == OrderState.FILLED

    def test_partially_filled_to_cancelled(self) -> None:
        o = _open_order()
        o.record_partial_fill(25, Price(Decimal("19505")))
        o.cancel("kill switch")
        assert o.state == OrderState.CANCELLED

    def test_open_to_cancelled(self) -> None:
        o = _open_order()
        o.cancel("operator")
        assert o.state == OrderState.CANCELLED

    def test_open_to_rejected(self) -> None:
        o = _open_order()
        o.reject("insufficient funds")
        assert o.state == OrderState.REJECTED
        assert o.rejection_reason == "insufficient funds"

    def test_open_to_expired(self) -> None:
        o = _open_order()
        o.expire()
        assert o.state == OrderState.EXPIRED


class TestInvalidTransitions:
    def test_pending_cannot_jump_to_open(self) -> None:
        o = _make_order()
        with pytest.raises(OrderStateError):
            o.open_at_exchange()

    def test_pending_cannot_jump_to_filled(self) -> None:
        o = _make_order()
        with pytest.raises(OrderStateError):
            o.record_fill(50, Price(Decimal("19500")))

    def test_submitting_cannot_go_to_open(self) -> None:
        o = _submitting_order()
        with pytest.raises(OrderStateError):
            o.open_at_exchange()

    def test_submitted_cannot_go_to_filled(self) -> None:
        o = _submitted_order()
        with pytest.raises(OrderStateError):
            o.record_fill(50, Price(Decimal("19500")))

    def test_filled_is_terminal(self) -> None:
        o = _open_order()
        o.record_fill(50, Price(Decimal("19510")))
        with pytest.raises(OrderStateError):
            o.cancel()

    def test_cancelled_is_terminal(self) -> None:
        o = _make_order()
        o.cancel()
        with pytest.raises(OrderStateError):
            o.start_submission()

    def test_rejected_is_terminal(self) -> None:
        o = _open_order()
        o.reject("reason")
        with pytest.raises(OrderStateError):
            o.open_at_exchange()

    def test_rejected_pre_submit_is_terminal(self) -> None:
        o = _submitting_order()
        o.reject_pre_submit("kill switch")
        with pytest.raises(OrderStateError):
            o.confirm_submitted("broker_x")

    def test_expired_is_terminal(self) -> None:
        o = _open_order()
        o.expire()
        with pytest.raises(OrderStateError):
            o.record_fill(50, Price(Decimal("19500")))


class TestOrderQueries:
    def test_remaining_quantity(self) -> None:
        o = _open_order()
        o.record_partial_fill(20, Price(Decimal("19505")))
        assert o.remaining_quantity == 30

    def test_is_fully_filled_false(self) -> None:
        o = _open_order()
        assert o.is_fully_filled is False

    def test_is_fully_filled_true(self) -> None:
        o = _open_order()
        o.record_fill(50, Price(Decimal("19510")))
        assert o.is_fully_filled is True

    def test_partial_fill_quantity_must_be_less_than_total(self) -> None:
        o = _open_order()
        with pytest.raises(ValueError):
            o.record_partial_fill(50, Price(Decimal("19505")))  # equals quantity

    def test_partial_fill_zero_raises(self) -> None:
        o = _open_order()
        with pytest.raises(ValueError):
            o.record_partial_fill(0, Price(Decimal("19505")))
