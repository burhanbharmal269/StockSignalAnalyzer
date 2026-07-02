"""ExecutionTimelineService — Phase 23 §1, §5.

Records precise timestamps for every execution stage and computes
inter-stage durations. Uses UPSERT so repeated events update the
same row rather than duplicating it.

Timeline stages:
  signal_generated → risk_approved → strike_selected →
  order_submitted → broker_received → broker_accepted →
  exchange_accepted → order_filled → position_opened → position_closed
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Ordered stage sequence for duration calculation
_STAGE_COLUMNS = [
    "signal_generated_at",
    "risk_approved_at",
    "strike_selected_at",
    "order_submitted_at",
    "broker_received_at",
    "broker_accepted_at",
    "exchange_accepted_at",
    "order_filled_at",
    "position_opened_at",
    "position_closed_at",
]

_DURATION_MAP = {
    # (from_stage, to_stage): duration_column
    ("signal_generated_at", "risk_approved_at"):     "signal_to_risk_ms",
    ("risk_approved_at",    "strike_selected_at"):    "risk_to_strike_ms",
    ("strike_selected_at",  "order_submitted_at"):    "strike_to_order_ms",
    ("order_submitted_at",  "broker_received_at"):    "order_to_broker_ms",
    ("broker_received_at",  "broker_accepted_at"):    "broker_to_exchange_ms",
    ("broker_accepted_at",  "exchange_accepted_at"):  "broker_to_exchange_ms",
    ("exchange_accepted_at", "order_filled_at"):      "exchange_to_fill_ms",
    ("order_filled_at",     "position_opened_at"):    "fill_to_position_ms",
}


class ExecutionTimelineService:
    """Records execution stage timestamps and computes durations. Fail-open."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Public write API ──────────────────────────────────────────────────────

    async def record_signal_generated(
        self,
        signal_id: str | UUID,
        *,
        symbol: str | None = None,
        direction: str | None = None,
        regime: str | None = None,
        is_index: bool = False,
        ts: datetime | None = None,
    ) -> None:
        await self._upsert(str(signal_id), {
            "signal_generated_at": (ts or datetime.now(UTC)).isoformat(),
            "symbol": symbol,
            "direction": direction,
            "regime": regime,
            "is_index": is_index,
        })

    async def record_risk_approved(
        self, signal_id: str | UUID, ts: datetime | None = None
    ) -> None:
        await self._upsert(str(signal_id), {
            "risk_approved_at": (ts or datetime.now(UTC)).isoformat(),
        })

    async def record_order_created(
        self,
        signal_id: str | UUID,
        order_id: str | UUID,
        *,
        ts: datetime | None = None,
    ) -> None:
        await self._upsert(str(signal_id), {
            "order_id": str(order_id),
            "order_submitted_at": (ts or datetime.now(UTC)).isoformat(),
        })

    async def record_order_filled(
        self,
        signal_id: str | UUID,
        order_id: str | UUID,
        *,
        ts: datetime | None = None,
    ) -> None:
        now = (ts or datetime.now(UTC)).isoformat()
        await self._upsert(str(signal_id), {
            "order_id": str(order_id),
            "broker_received_at": now,
            "broker_accepted_at": now,
            "exchange_accepted_at": now,
            "order_filled_at": now,
        })

    async def record_position_opened(
        self,
        signal_id: str | UUID,
        position_id: str | UUID,
        *,
        ts: datetime | None = None,
    ) -> None:
        await self._upsert(str(signal_id), {
            "position_id": str(position_id),
            "position_opened_at": (ts or datetime.now(UTC)).isoformat(),
        })

    async def record_position_closed(
        self, signal_id: str | UUID, *, ts: datetime | None = None
    ) -> None:
        await self._upsert(str(signal_id), {
            "position_closed_at": (ts or datetime.now(UTC)).isoformat(),
        })

    # ── Read API ──────────────────────────────────────────────────────────────

    async def get_timeline(self, signal_id: str) -> dict[str, Any] | None:
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT signal_id, order_id, position_id, symbol, broker,
                           direction, regime, is_index,
                           signal_generated_at, risk_approved_at, strike_selected_at,
                           order_submitted_at, broker_received_at, broker_accepted_at,
                           exchange_accepted_at, order_filled_at, position_opened_at,
                           position_closed_at,
                           signal_to_risk_ms, risk_to_strike_ms, strike_to_order_ms,
                           order_to_broker_ms, broker_to_exchange_ms, exchange_to_fill_ms,
                           fill_to_position_ms, total_execution_ms, created_at
                    FROM execution_events
                    WHERE signal_id = :sid
                """), {"sid": signal_id})
                row = r.mappings().fetchone()
                return dict(row) if row else None
        except Exception as exc:
            _log.debug("execution_timeline.get_failed signal_id=%s: %s", signal_id, exc)
            return None

    async def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT signal_id, order_id, symbol, direction, total_execution_ms,
                           signal_generated_at, order_filled_at, position_closed_at,
                           created_at
                    FROM execution_events
                    ORDER BY created_at DESC LIMIT :lim
                """), {"lim": limit})
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.debug("execution_timeline.get_recent_failed: %s", exc)
            return []

    async def get_slowest(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return orders with highest total_execution_ms."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT signal_id, order_id, symbol, total_execution_ms,
                           order_submitted_at, order_filled_at
                    FROM execution_events
                    WHERE total_execution_ms IS NOT NULL
                    ORDER BY total_execution_ms DESC LIMIT :lim
                """), {"lim": limit})
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.debug("execution_timeline.get_slowest_failed: %s", exc)
            return []

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _upsert(self, signal_id: str, updates: dict[str, Any]) -> None:
        """UPSERT execution_events row for signal_id. Compute durations after update."""
        try:
            async with self._sf() as db:
                # Ensure row exists
                await db.execute(text("""
                    INSERT INTO execution_events (signal_id)
                    VALUES (:sid)
                    ON CONFLICT DO NOTHING
                """), {"sid": signal_id})

                # Update provided fields
                set_parts = []
                params: dict[str, Any] = {"sid": signal_id}
                for col, val in updates.items():
                    if val is not None:
                        set_parts.append(f"{col} = :{col}")
                        params[col] = val

                if set_parts:
                    await db.execute(
                        text(f"UPDATE execution_events SET {', '.join(set_parts)}, updated_at = NOW() WHERE signal_id = :sid"),  # noqa: S608
                        params,
                    )

                # Recompute durations
                row = await db.execute(
                    text("SELECT * FROM execution_events WHERE signal_id = :sid"),
                    {"sid": signal_id},
                )
                record = row.mappings().fetchone()
                if record:
                    durations = _compute_durations(dict(record))
                    if durations:
                        dur_parts = [f"{k} = :{k}" for k in durations]
                        await db.execute(
                            text(f"UPDATE execution_events SET {', '.join(dur_parts)} WHERE signal_id = :sid"),  # noqa: S608
                            {**durations, "sid": signal_id},
                        )

                await db.commit()
        except Exception as exc:
            _log.warning("execution_timeline.upsert_failed signal_id=%s: %s", signal_id, exc)


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _ts_to_dt(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        return None


def _ms_between(a: Any, b: Any) -> float | None:
    da, db = _ts_to_dt(a), _ts_to_dt(b)
    if da is None or db is None:
        return None
    diff = (db - da).total_seconds() * 1000
    return round(max(diff, 0.0), 2)


def _compute_durations(record: dict) -> dict[str, float]:
    """Compute all inter-stage durations and total_execution_ms from a record dict."""
    out: dict[str, float] = {}

    dur = _ms_between(record.get("signal_generated_at"), record.get("risk_approved_at"))
    if dur is not None:
        out["signal_to_risk_ms"] = dur

    dur = _ms_between(record.get("risk_approved_at"), record.get("strike_selected_at"))
    if dur is not None:
        out["risk_to_strike_ms"] = dur

    dur = _ms_between(record.get("strike_selected_at"), record.get("order_submitted_at"))
    if dur is not None:
        out["strike_to_order_ms"] = dur

    dur = _ms_between(record.get("order_submitted_at"), record.get("broker_received_at"))
    if dur is not None:
        out["order_to_broker_ms"] = dur

    dur = _ms_between(record.get("broker_received_at"), record.get("exchange_accepted_at"))
    if dur is not None:
        out["broker_to_exchange_ms"] = dur

    dur = _ms_between(record.get("exchange_accepted_at"), record.get("order_filled_at"))
    if dur is not None:
        out["exchange_to_fill_ms"] = dur

    dur = _ms_between(record.get("order_filled_at"), record.get("position_opened_at"))
    if dur is not None:
        out["fill_to_position_ms"] = dur

    # Total: signal_generated → order_filled (trading path)
    total = _ms_between(record.get("signal_generated_at"), record.get("order_filled_at"))
    if total is not None:
        out["total_execution_ms"] = total

    return out
