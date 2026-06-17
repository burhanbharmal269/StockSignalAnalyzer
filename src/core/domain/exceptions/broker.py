"""Broker domain exceptions.

Raised by IBroker implementations and caught at the application layer.
Never caught inside domain entities.
"""

from __future__ import annotations


class BrokerConnectionError(Exception):
    """Raised when a broker WebSocket or REST connection cannot be established."""


class BrokerSessionExpiredError(Exception):
    """Raised when an IBroker method is called with an expired BrokerSession.

    Operator must re-authenticate to obtain a fresh session.
    """


class BrokerAuthenticationError(Exception):
    """Raised when broker login fails (bad API key, invalid request token, etc.)."""

    def __init__(self, message: str = "", broker_name: str = "") -> None:
        super().__init__(message)
        self.broker_name = broker_name


class BrokerOrderError(Exception):
    """Raised when the broker rejects or fails to process an order.

    Attributes:
        code        — broker-specific rejection code (e.g. "MARGIN_INSUFFICIENT")
        broker_name — name of the broker adapter that raised this error
    """

    def __init__(
        self,
        message: str = "",
        code: str = "",
        broker_name: str = "",
    ) -> None:
        super().__init__(message)
        self.code = (code or "").upper()
        self.broker_name = broker_name


class TokenEncryptionError(Exception):
    """Raised when broker token encryption or decryption fails."""


class BrokerHealthCheckError(Exception):
    """Raised when a broker health probe fails unexpectedly."""


class ExecutionGuardError(Exception):
    """Raised when ExecutionGuardService blocks an order placement.

    Carries the specific guard that fired (e.g. 'kill_switch', 'market_closed').
    """

    def __init__(self, reason: str, guard: str = "") -> None:
        super().__init__(reason)
        self.guard = guard
