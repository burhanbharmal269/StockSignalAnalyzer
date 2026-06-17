"""Unit tests for SubscriptionManager."""

from __future__ import annotations

import pytest

from core.domain.enums.subscription_mode import SubscriptionMode
from core.infrastructure.websocket.subscription_manager import (
    CapacityError,
    SubscriptionManager,
)


class TestSubscriptionManager:
    def test_add_and_get_mode(self) -> None:
        sm = SubscriptionManager(max_per_connection=10)
        sm.add(256265, SubscriptionMode.FULL)
        sm.commit({256265: SubscriptionMode.FULL}, set())
        assert sm.get_mode(256265) == SubscriptionMode.FULL

    def test_get_mode_missing_returns_none(self) -> None:
        sm = SubscriptionManager(max_per_connection=10)
        assert sm.get_mode(99999) is None

    def test_remove_clears_active(self) -> None:
        sm = SubscriptionManager(max_per_connection=10)
        sm.add(100, SubscriptionMode.LTP)
        sm.commit({100: SubscriptionMode.LTP}, set())
        sm.remove(100)
        sm.commit({}, {100})
        assert sm.get_mode(100) is None

    def test_count_reflects_active(self) -> None:
        sm = SubscriptionManager(max_per_connection=10)
        sm.add(1, SubscriptionMode.LTP)
        sm.add(2, SubscriptionMode.QUOTE)
        sm.commit({1: SubscriptionMode.LTP, 2: SubscriptionMode.QUOTE}, set())
        assert sm.count() == 2

    def test_capacity_error_when_limit_exceeded(self) -> None:
        sm = SubscriptionManager(max_per_connection=2)
        sm.add(1, SubscriptionMode.LTP)
        sm.add(2, SubscriptionMode.LTP)
        sm.commit({1: SubscriptionMode.LTP, 2: SubscriptionMode.LTP}, set())
        with pytest.raises(CapacityError) as exc_info:
            sm.add(3, SubscriptionMode.LTP)
        assert exc_info.value.limit == 2

    def test_get_batch_returns_pending_and_clears(self) -> None:
        sm = SubscriptionManager(max_per_connection=10)
        sm.add(1, SubscriptionMode.FULL)
        sm.add(2, SubscriptionMode.LTP)
        adds, removes = sm.get_batch()
        assert adds == {1: SubscriptionMode.FULL, 2: SubscriptionMode.LTP}
        assert removes == set()
        # Buffer is now cleared.
        adds2, removes2 = sm.get_batch()
        assert adds2 == {}
        assert removes2 == set()

    def test_get_batch_includes_removes(self) -> None:
        sm = SubscriptionManager(max_per_connection=10)
        sm.add(1, SubscriptionMode.LTP)
        sm.commit({1: SubscriptionMode.LTP}, set())
        sm.remove(1)
        _, removes = sm.get_batch()
        assert 1 in removes

    def test_re_add_after_remove_cancels_remove(self) -> None:
        sm = SubscriptionManager(max_per_connection=10)
        sm.add(1, SubscriptionMode.LTP)
        sm.commit({1: SubscriptionMode.LTP}, set())
        sm.remove(1)
        sm.add(1, SubscriptionMode.QUOTE)
        adds, removes = sm.get_batch()
        assert 1 in adds
        assert adds[1] == SubscriptionMode.QUOTE
        assert 1 not in removes

    def test_get_all_returns_snapshot(self) -> None:
        sm = SubscriptionManager(max_per_connection=10)
        sm.add(1, SubscriptionMode.LTP)
        sm.commit({1: SubscriptionMode.LTP}, set())
        snapshot = sm.get_all()
        assert snapshot == {1: SubscriptionMode.LTP}

    def test_invalid_max_raises(self) -> None:
        with pytest.raises(ValueError, match="max_per_connection"):
            SubscriptionManager(max_per_connection=0)
