"""SubscriptionManager — tracks active subscriptions and batches changes.

Handles 100ms debounce coalescing and per-connection capacity enforcement.

Reference: docs/12_WEBSOCKET_MANAGER.md §Subscription Management
"""

from __future__ import annotations

from core.domain.enums.subscription_mode import SubscriptionMode
from core.domain.interfaces.i_websocket_manager import InstrumentToken


class CapacityError(Exception):
    """Raised when adding instruments would exceed the per-connection subscription limit."""

    def __init__(self, current: int, adding: int, limit: int) -> None:
        super().__init__(
            f"Subscription capacity exceeded: {current} active + {adding} new > {limit} limit"
        )
        self.current = current
        self.adding = adding
        self.limit = limit


class SubscriptionManager:
    """Manages the set of active instrument subscriptions for one connection.

    Maintains two layers:
    - Active subscriptions: what is confirmed on the broker.
    - Pending changes: what should be sent on the next batch flush.

    get_batch() returns the pending changes and clears the buffer, ready
    for the next debounce window.
    """

    def __init__(self, max_per_connection: int = 3000) -> None:
        if max_per_connection < 1:
            msg = f"max_per_connection must be >= 1, got {max_per_connection}"
            raise ValueError(msg)
        self._max = max_per_connection
        self._active: dict[InstrumentToken, SubscriptionMode] = {}
        self._pending_adds: dict[InstrumentToken, SubscriptionMode] = {}
        self._pending_removes: set[InstrumentToken] = set()

    def add(self, token: InstrumentToken, mode: SubscriptionMode) -> None:
        """Stage an instrument for subscription in the next batch.

        Raises:
            CapacityError: If adding this instrument would exceed the limit.
        """
        # Count instruments that will be active after pending changes apply.
        projected = (
            len(self._active)
            + sum(1 for t in self._pending_adds if t not in self._active)
            - sum(1 for t in self._pending_removes if t in self._active)
        )
        if token not in self._active and token not in self._pending_adds:
            if projected >= self._max:
                raise CapacityError(current=projected, adding=1, limit=self._max)
        self._pending_adds[token] = mode
        self._pending_removes.discard(token)

    def remove(self, token: InstrumentToken) -> None:
        """Stage an instrument for unsubscription in the next batch."""
        self._pending_removes.add(token)
        self._pending_adds.pop(token, None)

    def commit(
        self,
        adds: dict[InstrumentToken, SubscriptionMode],
        removes: set[InstrumentToken],
    ) -> None:
        """Apply a confirmed batch to the active subscription set.

        Called after the broker has acknowledged the batch.
        """
        for token, mode in adds.items():
            self._active[token] = mode
        for token in removes:
            self._active.pop(token, None)

    def get_mode(self, token: InstrumentToken) -> SubscriptionMode | None:
        """Return the active subscription mode for a token, or None."""
        return self._active.get(token)

    def get_all(self) -> dict[InstrumentToken, SubscriptionMode]:
        """Return a snapshot of all active subscriptions."""
        return dict(self._active)

    def get_batch(self) -> tuple[dict[InstrumentToken, SubscriptionMode], set[InstrumentToken]]:
        """Return pending adds and removes, then clear the pending buffer.

        Returns:
            (adds, removes) — dicts/sets to be sent to the broker.
        """
        adds = dict(self._pending_adds)
        removes = set(self._pending_removes)
        self._pending_adds.clear()
        self._pending_removes.clear()
        return adds, removes

    def count(self) -> int:
        """Return the number of confirmed active subscriptions."""
        return len(self._active)
