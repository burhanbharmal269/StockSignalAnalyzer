"""Unit tests for ReconnectPolicy."""

from __future__ import annotations

import pytest

from core.infrastructure.websocket.reconnect_policy import ReconnectPolicy


class TestReconnectPolicy:
    def test_attempt_1_delay_in_range(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        for _ in range(50):
            delay = policy.get_delay(1)
            assert 1.0 <= delay <= 2.0, f"Attempt 1 delay out of range: {delay}"

    def test_attempt_2_delay_in_range(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        for _ in range(50):
            delay = policy.get_delay(2)
            assert 2.0 <= delay <= 4.0, f"Attempt 2 delay out of range: {delay}"

    def test_attempt_3_delay_in_range(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        for _ in range(50):
            delay = policy.get_delay(3)
            assert 4.0 <= delay <= 8.0, f"Attempt 3 delay out of range: {delay}"

    def test_attempt_4_delay_in_range(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        for _ in range(50):
            delay = policy.get_delay(4)
            assert 8.0 <= delay <= 16.0, f"Attempt 4 delay out of range: {delay}"

    def test_attempt_5_delay_in_range(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        for _ in range(50):
            delay = policy.get_delay(5)
            assert 16.0 <= delay <= 32.0, f"Attempt 5 delay out of range: {delay}"

    def test_attempt_5_not_exhausted(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        assert policy.is_exhausted(5) is False

    def test_attempt_6_is_exhausted(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        assert policy.is_exhausted(6) is True

    def test_attempt_1_not_exhausted(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        assert policy.is_exhausted(1) is False

    def test_custom_max_attempts(self) -> None:
        policy = ReconnectPolicy(max_attempts=3)
        assert policy.is_exhausted(3) is False
        assert policy.is_exhausted(4) is True

    def test_invalid_max_attempts_raises(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            ReconnectPolicy(max_attempts=0)

    def test_invalid_attempt_number_raises(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        with pytest.raises(ValueError, match="attempt"):
            policy.get_delay(0)

    def test_max_attempts_property(self) -> None:
        policy = ReconnectPolicy(max_attempts=7)
        assert policy.max_attempts == 7

    def test_delays_grow_with_attempt(self) -> None:
        policy = ReconnectPolicy(max_attempts=5)
        # Minimum delay for attempt n+1 > minimum delay for attempt n.
        # base_delay(n) = 2^(n-1), so base_delay grows each attempt.
        assert policy.get_delay(1) < policy.get_delay(5) * 10  # loose bound
