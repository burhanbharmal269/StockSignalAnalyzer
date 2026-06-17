"""Unit tests for ConnectionState enum."""

from __future__ import annotations

from core.domain.enums.connection_state import ConnectionState


class TestConnectionState:
    def test_all_states_defined(self) -> None:
        expected = {
            "DISCONNECTED",
            "CONNECTING",
            "AUTHENTICATING",
            "CONNECTED",
            "SUBSCRIBING",
            "STREAMING",
            "RECONNECTING",
            "FAILED",
        }
        assert {s.value for s in ConnectionState} == expected

    def test_is_str_enum(self) -> None:
        assert isinstance(ConnectionState.STREAMING, str)
        assert ConnectionState.STREAMING == "STREAMING"

    def test_membership(self) -> None:
        assert "DISCONNECTED" in ConnectionState._value2member_map_
        assert "UNKNOWN" not in ConnectionState._value2member_map_

    def test_count(self) -> None:
        assert len(ConnectionState) == 8
