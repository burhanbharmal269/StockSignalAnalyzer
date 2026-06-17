"""ReconnectPolicy — exponential backoff with full jitter for WebSocket reconnection.

Reference: docs/12_WEBSOCKET_MANAGER.md §Reconnection Policy

Delay table (attempt → delay range):
    1 → [1, 2]s    2 → [2, 4]s    3 → [4, 8]s
    4 → [8, 16]s   5 → [16, 32]s  >5 → exhausted
"""

from __future__ import annotations

import random


class ReconnectPolicy:
    """Stateless reconnect delay calculator.

    Each call to get_delay() is independent — no internal counter.
    The caller passes the current attempt number (1-based).
    """

    def __init__(self, max_attempts: int = 5) -> None:
        if max_attempts < 1:
            msg = f"max_attempts must be >= 1, got {max_attempts}"
            raise ValueError(msg)
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        """Maximum number of reconnection attempts before FAILED."""
        return self._max_attempts

    def get_delay(self, attempt: int) -> float:
        """Return a jittered backoff delay for the given attempt number.

        Formula: base_delay + uniform(0, base_delay)
                 where base_delay = 2^(attempt - 1)

        Args:
            attempt: 1-based reconnection attempt number.

        Returns:
            Seconds to wait before the next reconnection attempt.
        """
        if attempt < 1:
            msg = f"attempt must be >= 1, got {attempt}"
            raise ValueError(msg)
        base_delay = 2 ** (attempt - 1)
        jitter = random.uniform(0, base_delay)  # noqa: S311
        return base_delay + jitter

    def is_exhausted(self, attempt: int) -> bool:
        """Return True when the attempt count has exceeded the maximum.

        Args:
            attempt: The attempt that just failed (1-based).
        """
        return attempt > self._max_attempts
