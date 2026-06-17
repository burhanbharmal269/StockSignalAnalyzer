"""Unit tests for ConnectionStateMachine."""

from __future__ import annotations

import pytest

from core.domain.enums.connection_state import ConnectionState
from core.domain.exceptions.websocket_exceptions import WebSocketStateError
from core.infrastructure.websocket.connection_state_machine import ConnectionStateMachine

# All legal transitions derived from docs/12_WEBSOCKET_MANAGER.md
_LEGAL = [
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
]

_ILLEGAL = [
    (ConnectionState.DISCONNECTED, ConnectionState.STREAMING),
    (ConnectionState.DISCONNECTED, ConnectionState.FAILED),
    (ConnectionState.CONNECTING, ConnectionState.STREAMING),
    (ConnectionState.AUTHENTICATING, ConnectionState.STREAMING),
    (ConnectionState.CONNECTED, ConnectionState.STREAMING),
    (ConnectionState.STREAMING, ConnectionState.CONNECTED),
    (ConnectionState.STREAMING, ConnectionState.SUBSCRIBING),
    (ConnectionState.FAILED, ConnectionState.STREAMING),
    (ConnectionState.FAILED, ConnectionState.CONNECTING),
]


class TestConnectionStateMachine:
    def _machine_at(self, state: ConnectionState) -> ConnectionStateMachine:
        """Build a machine forcefully placed in the given state."""
        sm = ConnectionStateMachine()
        sm.reset()
        sm._state = state  # noqa: SLF001
        return sm

    @pytest.mark.parametrize("from_state,to_state", _LEGAL)
    def test_legal_transitions(
        self, from_state: ConnectionState, to_state: ConnectionState
    ) -> None:
        sm = self._machine_at(from_state)
        sm.transition(to_state)
        assert sm.state == to_state

    @pytest.mark.parametrize("from_state,to_state", _ILLEGAL)
    def test_illegal_transitions_raise(
        self, from_state: ConnectionState, to_state: ConnectionState
    ) -> None:
        sm = self._machine_at(from_state)
        with pytest.raises(WebSocketStateError) as exc_info:
            sm.transition(to_state)
        assert exc_info.value.from_state == from_state
        assert exc_info.value.to_state == to_state

    def test_initial_state_is_disconnected(self) -> None:
        sm = ConnectionStateMachine()
        assert sm.state == ConnectionState.DISCONNECTED

    def test_reset_returns_to_disconnected(self) -> None:
        sm = ConnectionStateMachine()
        sm.transition(ConnectionState.CONNECTING)
        sm.transition(ConnectionState.FAILED)
        sm.reset()
        assert sm.state == ConnectionState.DISCONNECTED

    def test_state_not_mutated_on_illegal_transition(self) -> None:
        sm = ConnectionStateMachine()
        with pytest.raises(WebSocketStateError):
            sm.transition(ConnectionState.STREAMING)
        assert sm.state == ConnectionState.DISCONNECTED

    def test_full_happy_path(self) -> None:
        sm = ConnectionStateMachine()
        sm.transition(ConnectionState.CONNECTING)
        sm.transition(ConnectionState.AUTHENTICATING)
        sm.transition(ConnectionState.CONNECTED)
        sm.transition(ConnectionState.SUBSCRIBING)
        sm.transition(ConnectionState.STREAMING)
        assert sm.state == ConnectionState.STREAMING

    def test_reconnect_path(self) -> None:
        sm = ConnectionStateMachine()
        sm._state = ConnectionState.STREAMING  # noqa: SLF001
        sm.transition(ConnectionState.RECONNECTING)
        sm.transition(ConnectionState.CONNECTING)
        sm.transition(ConnectionState.AUTHENTICATING)
        sm.transition(ConnectionState.CONNECTED)
        assert sm.state == ConnectionState.CONNECTED
