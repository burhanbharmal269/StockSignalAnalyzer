"""ExecutionLockService — controls whether order placement is allowed.

This is the single source of truth for order execution gating.

Two independent axes:

    locked          LOCKED   → no orders regardless of execution_mode
    execution_mode  MANUAL   → no orders (user reviews signals, places manually)
                    AUTOMATIC → orders routed to broker

Orders are blocked when: locked=True OR execution_mode="MANUAL"
Signals ALWAYS continue regardless of both axes.

This service REPLACES the paper-mode kill switch auto-deactivation that
previously tied order gating to broker trading_mode.

The kill switch remains available for true emergencies (full pipeline stop).
"""

from __future__ import annotations

import logging

from core.infrastructure.cache.execution_lock_repository import (
    ExecutionLockState,
    RedisExecutionLockRepository,
)

_log = logging.getLogger(__name__)


class ExecutionLockService:
    """Application-layer wrapper around RedisExecutionLockRepository."""

    def __init__(self, repo: RedisExecutionLockRepository) -> None:
        self._repo = repo

    async def get_state(self) -> ExecutionLockState:
        return await self._repo.get_state()

    async def is_order_execution_blocked(self) -> bool:
        """True when orders must NOT be placed.

        Called by PipelineEventHandler before routing any order.
        """
        try:
            state = await self._repo.get_state()
            return state.is_order_blocked
        except Exception:
            _log.exception("execution_lock.read_failed — defaulting to BLOCKED (safe)")
            return True

    async def lock(self, locked_by: str, note: str = "") -> ExecutionLockState:
        """LOCK — prevent order execution. Signals continue."""
        await self._repo.set_locked(locked=True, by=locked_by, note=note)
        state = await self._repo.get_state()
        _log.warning(
            "execution_lock.locked locked_by=%s note=%s",
            locked_by,
            note,
        )
        return state

    async def unlock(self, unlocked_by: str, note: str = "") -> ExecutionLockState:
        """UNLOCK — allow order execution (when mode=AUTOMATIC)."""
        await self._repo.set_locked(locked=False, by=unlocked_by, note=note)
        state = await self._repo.get_state()
        _log.info(
            "execution_lock.unlocked unlocked_by=%s note=%s",
            unlocked_by,
            note,
        )
        return state

    async def set_execution_mode(self, mode: str, changed_by: str) -> ExecutionLockState:
        """Change execution mode (MANUAL | AUTOMATIC).

        MANUAL   → orders never placed regardless of lock state
        AUTOMATIC → orders placed when lock is UNLOCKED
        """
        await self._repo.set_mode(mode=mode, by=changed_by)
        state = await self._repo.get_state()
        _log.info(
            "execution_lock.mode_changed mode=%s changed_by=%s",
            mode.upper(),
            changed_by,
        )
        return state

    async def seed_on_startup(self, default_mode: str = "MANUAL") -> None:
        """Seed execution lock at startup if the Redis key is absent.

        Only seeds if the key does not already exist — preserves operator
        settings across restarts.
        """
        try:
            seeded = await self._repo.seed_if_absent(default_mode=default_mode)
            if seeded:
                _log.info(
                    "execution_lock.seeded default_mode=%s locked=false",
                    default_mode.upper(),
                )
            else:
                state = await self._repo.get_state()
                _log.info(
                    "execution_lock.already_present mode=%s locked=%s",
                    state.execution_mode,
                    state.locked,
                )
        except Exception:
            _log.exception("execution_lock.seed_failed — signals unaffected, orders may be blocked")
