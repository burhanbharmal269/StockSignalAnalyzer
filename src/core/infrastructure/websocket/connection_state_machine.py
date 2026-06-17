"""ConnectionStateMachine — enforces legal WebSocket connection state transitions.

Illegal transitions raise WebSocketStateError and are logged at ERROR level.
Every legal transition is logged at INFO level as a structured event.

Reference: docs/12_WEBSOCKET_MANAGER.md §Connection State Machine
"""

from __future__ import annotations

import logging

from core.domain.enums.connection_state import ConnectionState
from core.domain.exceptions.websocket_exceptions import WebSocketStateError

logger = logging.getLogger(__name__)

# Every legal (from → to) pair. Any transition not in this set is illegal.
_LEGAL_TRANSITIONS: frozenset[tuple[ConnectionState, ConnectionState]] = frozenset(
    {
        (ConnectionState.DISCONNECTED, ConnectionState.CONNECTING),
        (ConnectionState.CONNECTING, ConnectionState.AUTHENTICATING),
        (ConnectionState.CONNECTING, ConnectionState.FAILED),
        (ConnectionState.AUTHENTICATING, ConnectionState.CONNECTED),
        (ConnectionState.AUTHENTICATING, ConnectionState.FAILED),
        (ConnectionState.CONNECTED, ConnectionState.SUBSCRIBING),
        (ConnectionState.CONNECTED, ConnectionState.DISCONNECTED),
        (ConnectionState.SUBSCRIBING, ConnectionState.STREAMING),
        (ConnectionState.SUBSCRIBING, ConnectionState.FAILED),
        (ConnectionState.STREAMING, ConnectionState.RECONNECTING),
        (ConnectionState.STREAMING, ConnectionState.DISCONNECTED),
        (ConnectionState.RECONNECTING, ConnectionState.CONNECTING),
        (ConnectionState.RECONNECTING, ConnectionState.FAILED),
        (ConnectionState.RECONNECTING, ConnectionState.DISCONNECTED),
        (ConnectionState.FAILED, ConnectionState.DISCONNECTED),
    }
)


class ConnectionStateMachine:
    """Tracks and enforces the WebSocket connection lifecycle.

    Usage:
        sm = ConnectionStateMachine()
        sm.transition(ConnectionState.CONNECTING)   # ok
        sm.transition(ConnectionState.STREAMING)    # raises WebSocketStateError
    """

    def __init__(self) -> None:
        self._state: ConnectionState = ConnectionState.DISCONNECTED

    @property
    def state(self) -> ConnectionState:
        """Current connection state (non-blocking read)."""
        return self._state

    def transition(self, new_state: ConnectionState, reason: str = "") -> None:
        """Move to new_state if the transition is legal.

        Args:
            new_state: The target state.
            reason:    Optional human-readable reason included in the log.

        Raises:
            WebSocketStateError: If the transition is not defined in the state machine.
        """
        if (self._state, new_state) not in _LEGAL_TRANSITIONS:
            logger.error(
                "websocket_state_change_illegal",
                extra={
                    "from_state": self._state,
                    "to_state": new_state,
                    "reason": reason,
                },
            )
            raise WebSocketStateError(self._state, new_state)

        logger.info(
            "websocket_state_change",
            extra={
                "from_state": self._state,
                "to_state": new_state,
                "reason": reason,
            },
        )
        self._state = new_state

    def reset(self) -> None:
        """Force-reset to DISCONNECTED without transition validation.

        Use only during emergency shutdown or test teardown.
        """
        self._state = ConnectionState.DISCONNECTED
