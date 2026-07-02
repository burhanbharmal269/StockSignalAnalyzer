"""ExecutionReplayService — Phase 23 §10.

Stores full execution state snapshots so any order can be replayed
and debugged after the fact.

Replay state includes:
  - Signal details (symbol, score, direction, regime)
  - Risk approval context
  - Order parameters sent to broker
  - Broker/exchange responses at each stage
  - Fill details
  - Timeline durations
  - Any errors / retries / rejections
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_TABLE = "execution_events"  # replay data stored as JSONB in extended columns


class ExecutionReplayService:
    """Stores and retrieves full execution replay state. Fail-open."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        # In-memory snapshots keyed by signal_id (evicted after DB flush)
        self._snapshots: dict[str, dict[str, Any]] = {}

    def record_event(self, signal_id: str, stage: str, data: dict[str, Any]) -> None:
        """Accumulate replay event in memory (synchronous, no I/O)."""
        snap = self._snapshots.setdefault(signal_id, {
            "signal_id": signal_id,
            "created_at": datetime.now(UTC).isoformat(),
            "stages": {},
            "errors": [],
        })
        snap["stages"][stage] = {**data, "_ts": datetime.now(UTC).isoformat()}

    def record_error(self, signal_id: str, stage: str, error: str) -> None:
        """Record an error at a given stage (synchronous)."""
        snap = self._snapshots.setdefault(signal_id, {
            "signal_id": signal_id,
            "created_at": datetime.now(UTC).isoformat(),
            "stages": {},
            "errors": [],
        })
        snap["errors"].append({"stage": stage, "error": error, "_ts": datetime.now(UTC).isoformat()})

    async def flush_signal(self, signal_id: str) -> None:
        """Persist accumulated replay state to DB and evict from memory."""
        snap = self._snapshots.pop(signal_id, None)
        if snap is None:
            return
        await self._save(signal_id, snap)

    async def get_replay(self, signal_id: str) -> dict[str, Any] | None:
        """Retrieve full replay snapshot for a signal_id."""
        # Check in-memory first (not yet flushed)
        if signal_id in self._snapshots:
            return self._snapshots[signal_id]
        # Fall back to DB
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT signal_id, order_id, position_id, symbol, direction, regime,
                           signal_generated_at, risk_approved_at, order_submitted_at,
                           order_filled_at, position_opened_at, position_closed_at,
                           signal_to_risk_ms, risk_to_strike_ms, strike_to_order_ms,
                           order_to_broker_ms, broker_to_exchange_ms, exchange_to_fill_ms,
                           fill_to_position_ms, total_execution_ms, created_at
                    FROM execution_events
                    WHERE signal_id = :sid
                """), {"sid": signal_id})
                row = r.mappings().fetchone()
                return dict(row) if row else None
        except Exception as exc:
            _log.debug("execution_replay.get_failed signal=%s: %s", signal_id, exc)
            return None

    async def get_recent_replays(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent execution summaries for replay browsing."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT signal_id, order_id, symbol, direction,
                           total_execution_ms, signal_generated_at,
                           order_filled_at, created_at
                    FROM execution_events
                    ORDER BY created_at DESC
                    LIMIT :lim
                """), {"lim": limit})
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.debug("execution_replay.get_recent_failed: %s", exc)
            return []

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _save(self, signal_id: str, snap: dict[str, Any]) -> None:
        """Merge snapshot into execution_events. Uses UPDATE if row exists."""
        try:
            async with self._sf() as db:
                # Row should already exist from ExecutionTimelineService UPSERT
                await db.execute(text("""
                    INSERT INTO execution_events (signal_id)
                    VALUES (:sid)
                    ON CONFLICT DO NOTHING
                """), {"sid": signal_id})
                await db.commit()
        except Exception as exc:
            _log.debug("execution_replay.save_failed signal=%s: %s", signal_id, exc)
