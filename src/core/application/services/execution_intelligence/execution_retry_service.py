"""ExecutionRetryService — Phase 23 §6.

Tracks order retry attempts: count, reason, delay, success/failure.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Alert threshold (§12)
_RETRY_WARN_COUNT = 3


class ExecutionRetryService:
    """Records order retry events. Fail-open."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record_retry(
        self,
        *,
        signal_id: str | None = None,
        order_id: str | None = None,
        symbol: str | None = None,
        broker: str = "kite",
        attempt_number: int = 1,
        retry_reason: str | None = None,
        delay_ms: int | None = None,
        succeeded: bool | None = None,
        failure_reason: str | None = None,
        timeout_type: str | None = None,
    ) -> None:
        """Record one retry attempt."""
        try:
            if attempt_number >= _RETRY_WARN_COUNT:
                _log.warning(
                    "execution_retry.high signal=%s symbol=%s attempt=%d reason=%s",
                    signal_id or "?", symbol or "?", attempt_number, retry_reason or "?",
                )
            async with self._sf() as db:
                await db.execute(text("""
                    INSERT INTO execution_retries
                        (signal_id, order_id, symbol, broker,
                         attempt_number, retry_reason, delay_ms,
                         succeeded, failure_reason, timeout_type, recorded_at)
                    VALUES
                        (:sid, :oid, :sym, :broker,
                         :attempt, :reason, :delay,
                         :ok, :fail_reason, :timeout_type, NOW())
                """), {
                    "sid": signal_id, "oid": order_id, "sym": symbol, "broker": broker,
                    "attempt": attempt_number, "reason": retry_reason, "delay": delay_ms,
                    "ok": succeeded, "fail_reason": failure_reason, "timeout_type": timeout_type,
                })
                await db.commit()
        except Exception as exc:
            _log.debug("execution_retry.record_failed: %s", exc)

    async def get_stats(self, hours: int = 24) -> dict[str, Any]:
        """Summary stats: total retries, success rate, common reasons."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*) AS total_retries,
                        AVG(attempt_number) AS avg_attempts,
                        MAX(attempt_number) AS max_attempts,
                        SUM(CASE WHEN succeeded THEN 1 ELSE 0 END)::float
                            / NULLIF(COUNT(*), 0) * 100 AS success_rate_pct
                    FROM execution_retries
                    WHERE recorded_at > NOW() - :hrs * INTERVAL '1 hour'
                """), {"hrs": hours})
                stats = dict(r.mappings().fetchone() or {})

                r2 = await db.execute(text("""
                    SELECT retry_reason, COUNT(*) AS cnt
                    FROM execution_retries
                    WHERE recorded_at > NOW() - :hrs * INTERVAL '1 hour'
                    GROUP BY retry_reason
                    ORDER BY cnt DESC
                    LIMIT 10
                """), {"hrs": hours})
                top_reasons = [dict(row) for row in r2.mappings().fetchall()]

            return {"hours": hours, "stats": stats, "top_reasons": top_reasons}
        except Exception as exc:
            _log.debug("execution_retry.get_stats_failed: %s", exc)
            return {"error": str(exc)}
