"""ExecutionLatencyService — Phase 23 §2, §13.

Records per-stage latency and computes aggregations:
  - Average, Median, P95, P99, Maximum per stage/broker/symbol/regime
  - Rolling windows: 1D / 7D / 30D / 90D / Lifetime

Latency records are written to execution_latency table.
Redis is used for sub-minute rolling averages (avoid hammering DB on every order).
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Thresholds for alerts (§12)
_LATENCY_WARN_MS = 1_000   # 1 second — warn if total execution exceeds
_LATENCY_CRIT_MS = 5_000   # 5 seconds — critical


class ExecutionLatencyService:
    """Records and aggregates execution stage latencies. Fail-open."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client=None,
    ) -> None:
        self._sf = session_factory
        self._redis = redis_client
        # In-process buffer for batch writes (§18 batching)
        self._buffer: list[dict[str, Any]] = []
        self._last_flush = time.monotonic()
        self._flush_interval = 30.0  # flush every 30 seconds

    async def record_stage(
        self,
        *,
        stage: str,
        duration_ms: float,
        signal_id: str | None = None,
        order_id: str | None = None,
        symbol: str | None = None,
        broker: str = "kite",
        regime: str | None = None,
    ) -> None:
        """Record one latency measurement. Non-blocking via buffer."""
        try:
            now = datetime.now(UTC)
            self._buffer.append({
                "stage": stage,
                "duration_ms": round(duration_ms, 2),
                "signal_id": str(signal_id) if signal_id else None,
                "order_id": str(order_id) if order_id else None,
                "symbol": symbol,
                "broker": broker,
                "regime": regime,
                "time_of_day": now.time().isoformat(),
                "recorded_at": now.isoformat(),
            })
            # Alert if total latency exceeds threshold
            if stage == "total_execution" and duration_ms > _LATENCY_WARN_MS:
                lvl = "CRITICAL" if duration_ms > _LATENCY_CRIT_MS else "WARNING"
                _log.warning(
                    "execution_latency.%s stage=%s symbol=%s duration_ms=%.0f threshold_ms=%d",
                    lvl.lower(), stage, symbol or "?", duration_ms,
                    _LATENCY_CRIT_MS if lvl == "CRITICAL" else _LATENCY_WARN_MS,
                )
            # Flush if buffer is large or stale
            if len(self._buffer) >= 50 or (time.monotonic() - self._last_flush) > self._flush_interval:
                await self._flush()
        except Exception as exc:
            _log.debug("execution_latency.record_failed stage=%s: %s", stage, exc)

    async def flush(self) -> None:
        """Manually flush buffer (called at shutdown or test teardown)."""
        await self._flush()

    async def get_stats(
        self,
        *,
        stage: str | None = None,
        broker: str | None = None,
        symbol: str | None = None,
        hours: int = 24,
    ) -> dict[str, Any]:
        """Return latency statistics for the given filters."""
        try:
            conditions = ["recorded_at > NOW() - :hrs * INTERVAL '1 hour'"]
            params: dict[str, Any] = {"hrs": hours}
            if stage:
                conditions.append("stage = :stage")
                params["stage"] = stage
            if broker:
                conditions.append("broker = :broker")
                params["broker"] = broker
            if symbol:
                conditions.append("symbol = :symbol")
                params["symbol"] = symbol

            where = " AND ".join(conditions)
            async with self._sf() as db:
                r = await db.execute(text(f"""
                    SELECT stage, COUNT(*) AS n,
                           AVG(duration_ms) AS avg_ms,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
                           PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
                           PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_ms,
                           MAX(duration_ms) AS max_ms,
                           MIN(duration_ms) AS min_ms
                    FROM execution_latency
                    WHERE {where}
                    GROUP BY stage
                    ORDER BY AVG(duration_ms) DESC
                """), params)  # noqa: S608
                rows = r.mappings().fetchall()
            return {
                "filters": {"stage": stage, "broker": broker, "symbol": symbol, "hours": hours},
                "stages": [
                    {
                        "stage": row["stage"],
                        "count": int(row["n"]),
                        "avg_ms":  _round(row["avg_ms"]),
                        "p50_ms":  _round(row["p50_ms"]),
                        "p95_ms":  _round(row["p95_ms"]),
                        "p99_ms":  _round(row["p99_ms"]),
                        "max_ms":  _round(row["max_ms"]),
                        "min_ms":  _round(row["min_ms"]),
                    }
                    for row in rows
                ],
            }
        except Exception as exc:
            _log.debug("execution_latency.get_stats_failed: %s", exc)
            return {"error": str(exc)}

    async def get_rolling_windows(self, stage: str = "total_execution") -> dict[str, Any]:
        """Return avg latency for 1D/7D/30D/90D windows."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        AVG(CASE WHEN recorded_at > NOW() - INTERVAL '1 day'   THEN duration_ms END) AS d1,
                        AVG(CASE WHEN recorded_at > NOW() - INTERVAL '7 days'  THEN duration_ms END) AS d7,
                        AVG(CASE WHEN recorded_at > NOW() - INTERVAL '30 days' THEN duration_ms END) AS d30,
                        AVG(CASE WHEN recorded_at > NOW() - INTERVAL '90 days' THEN duration_ms END) AS d90,
                        AVG(duration_ms) AS lifetime
                    FROM execution_latency
                    WHERE stage = :stage
                """), {"stage": stage})
                row = r.mappings().fetchone()
                return {
                    "stage": stage,
                    "1d_avg_ms":       _round(row["d1"]),
                    "7d_avg_ms":       _round(row["d7"]),
                    "30d_avg_ms":      _round(row["d30"]),
                    "90d_avg_ms":      _round(row["d90"]),
                    "lifetime_avg_ms": _round(row["lifetime"]),
                } if row else {}
        except Exception as exc:
            _log.debug("execution_latency.rolling_windows_failed: %s", exc)
            return {"error": str(exc)}

    async def get_by_broker(self, hours: int = 24) -> dict[str, Any]:
        """Latency comparison across brokers (§14)."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT broker,
                           COUNT(*) AS n,
                           AVG(duration_ms) AS avg_ms,
                           PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
                           MAX(duration_ms) AS max_ms
                    FROM execution_latency
                    WHERE stage = 'total_execution'
                      AND recorded_at > NOW() - :hrs * INTERVAL '1 hour'
                    GROUP BY broker
                    ORDER BY avg_ms
                """), {"hrs": hours})
                rows = r.mappings().fetchall()
            return {"brokers": [dict(r) for r in rows], "hours": hours}
        except Exception as exc:
            _log.debug("execution_latency.get_by_broker_failed: %s", exc)
            return {"error": str(exc)}

    # ── Flush buffer to DB ────────────────────────────────────────────────────

    async def _flush(self) -> None:
        if not self._buffer:
            return
        records = self._buffer[:]
        self._buffer.clear()
        self._last_flush = time.monotonic()
        try:
            async with self._sf() as db:
                await db.execute(text("""
                    INSERT INTO execution_latency
                        (signal_id, order_id, symbol, broker, stage, duration_ms,
                         time_of_day, regime, recorded_at)
                    SELECT
                        r->>'signal_id', r->>'order_id', r->>'symbol', r->>'broker',
                        r->>'stage', (r->>'duration_ms')::float,
                        (r->>'time_of_day')::time, r->>'regime',
                        (r->>'recorded_at')::timestamptz
                    FROM jsonb_array_elements(:rows::jsonb) AS r
                """), {"rows": json.dumps(records)})
                await db.commit()
        except Exception as exc:
            _log.warning("execution_latency.flush_failed count=%d: %s", len(records), exc)


def _round(val: Any, decimals: int = 2) -> float | None:
    if val is None:
        return None
    return round(float(val), decimals)
