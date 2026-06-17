"""Domain exceptions for OMS order lifecycle."""

from __future__ import annotations

from core.domain.exceptions.base import DomainError


class OrderStateError(DomainError):
    """Raised when an illegal order state transition is attempted."""

    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(
            f"Invalid order transition: {from_state!r} → {to_state!r}"
        )
        self.from_state = from_state
        self.to_state = to_state


class KillSwitchActiveError(DomainError):
    """Raised when an order placement is attempted while the kill switch is active."""


class SignalExpiredError(DomainError):
    """Raised when the OMS receives a signal past its valid_until timestamp."""


class OrderRateLimitError(DomainError):
    """Raised when orders per minute exceeds the configured limit."""


class InstrumentNotActiveError(DomainError):
    """Raised when the target instrument is not in the active InstrumentMaster."""


class OrderPersistenceError(Exception):
    """Raised when an order cannot be persisted to the database.

    This is NOT a DomainError — it is a hard infrastructure failure.
    Callers must NOT silently swallow this. Fail-closed.
    """


class PositionPersistenceError(Exception):
    """Raised when a position cannot be persisted to the database.

    Hard infrastructure failure. Never fail-open.
    """


class BrokerUnavailableError(Exception):
    """Raised when the broker API is unreachable or returns a non-retryable error.

    OMS fails closed on this: no order is placed, no position opened.
    """


class ReconciliationError(Exception):
    """Raised when reconciliation detects a critical state inconsistency."""


class RogueOrderDetectedError(Exception):
    """Raised when an order at the broker does not match any OMS record.

    Triggers an immediate kill switch activation.
    """
