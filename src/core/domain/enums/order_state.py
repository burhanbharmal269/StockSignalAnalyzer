"""OrderState — OMS order lifecycle state machine.

States and transitions from docs/22_OMS_DESIGN.md.
"""

from __future__ import annotations

from enum import StrEnum


class OrderState(StrEnum):
    # Active states (non-terminal)
    PENDING = "PENDING"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"

    # Terminal states
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    REJECTED_PRE_SUBMIT = "REJECTED_PRE_SUBMIT"
    EXPIRED = "EXPIRED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_ORDER_STATES


_TERMINAL_ORDER_STATES: frozenset[OrderState] = frozenset(
    {
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.REJECTED_PRE_SUBMIT,
        OrderState.EXPIRED,
    }
)

VALID_ORDER_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.PENDING: frozenset({OrderState.SUBMITTING, OrderState.CANCELLED}),
    OrderState.SUBMITTING: frozenset(
        {OrderState.SUBMITTED, OrderState.REJECTED_PRE_SUBMIT}
    ),
    OrderState.SUBMITTED: frozenset({OrderState.OPEN}),
    OrderState.OPEN: frozenset(
        {
            OrderState.FILLED,
            OrderState.PARTIALLY_FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset({OrderState.FILLED, OrderState.CANCELLED}),
    # Terminal states
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.REJECTED_PRE_SUBMIT: frozenset(),
    OrderState.EXPIRED: frozenset(),
}
