"""WebSocket domain exceptions.

Reference: docs/12_WEBSOCKET_MANAGER.md §Connection State Machine
"""

from __future__ import annotations

from core.domain.exceptions.base import DomainError


class WebSocketStateError(DomainError):
    """Raised when an illegal WebSocket state transition is attempted."""

    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(
            f"Invalid WebSocket transition: {from_state!r} → {to_state!r}"
        )
        self.from_state = from_state
        self.to_state = to_state


class BrokerSessionExpiredError(DomainError):
    """Raised when the broker access token has expired during reconnection.

    The manager enters FAILED state and will not retry. The operator must
    re-authenticate before reconnection is attempted.
    """
