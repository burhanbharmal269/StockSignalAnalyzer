"""ConnectionState — WebSocket connection lifecycle states.

Reference: docs/12_WEBSOCKET_MANAGER.md §Connection State Machine
"""

from __future__ import annotations

from enum import StrEnum


class ConnectionState(StrEnum):
    """Ordered lifecycle states for a broker WebSocket connection."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    AUTHENTICATING = "AUTHENTICATING"
    CONNECTED = "CONNECTED"
    SUBSCRIBING = "SUBSCRIBING"
    STREAMING = "STREAMING"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"
