"""BrokerHealthMonitorService — Phase 23 §9.

Monitors Kite API/WS health and computes a BrokerHealthScore (0-100).

Health score components:
  - API latency:     fast (<200ms) = full points; slow (>2s) = 0
  - WS connectivity: connected = full; disconnected = 0
  - Failure rate:    0% = full; >5% = 0
  - Reconnect count: 0 = full; many = penalty

No dependency on broker SDK — uses Redis counters incremented by
existing broker adapter code. Reads are non-invasive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Redis key naming convention (written by broker adapter)
_REDIS_KEY_WS_LATENCY   = "broker:kite:ws_latency_ms"
_REDIS_KEY_API_LATENCY  = "broker:kite:api_latency_ms"
_REDIS_KEY_ORDER_LAT    = "broker:kite:order_latency_ms"
_REDIS_KEY_FAIL_COUNT   = "broker:kite:fail_count"
_REDIS_KEY_TOTAL_COUNT  = "broker:kite:total_count"
_REDIS_KEY_RECONNECTS   = "broker:kite:reconnect_count"
_REDIS_KEY_CONNECTED    = "broker:kite:ws_connected"

_SNAPSHOT_INTERVAL_S = 60   # persist health snapshot every 60 seconds


class BrokerHealthMonitorService:
    """Computes broker health score and persists snapshots. Fail-open."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client=None,
        broker: str = "kite",
    ) -> None:
        self._sf = session_factory
        self._redis = redis_client
        self._broker = broker
        self._last_snapshot: float = 0.0
        self._current_score: float = 100.0

    # ── Health update (called by background task) ─────────────────────────────

    async def update(self) -> dict[str, Any]:
        """Read current metrics, compute score, optionally persist snapshot."""
        metrics = await self._read_metrics()
        score = _compute_score(metrics)
        self._current_score = score

        now = time.monotonic()
        if now - self._last_snapshot >= _SNAPSHOT_INTERVAL_S:
            await self._persist_snapshot(score, metrics)
            self._last_snapshot = now

        if score < 60:
            _log.warning(
                "broker_health.%s score=%.1f api_ms=%.0f ws_connected=%s fail_rate=%.1f%%",
                "DEGRADED" if score >= 40 else "CRITICAL",
                score,
                metrics.get("api_latency_ms") or 0,
                metrics.get("is_connected"),
                metrics.get("failure_rate_pct") or 0,
            )
        return {"broker": self._broker, "health_score": score, **metrics}

    def current_score(self) -> float:
        """Return last computed health score without hitting Redis/DB."""
        return self._current_score

    # ── Read API ──────────────────────────────────────────────────────────────

    async def get_current(self) -> dict[str, Any]:
        """Return freshly computed health status."""
        return await self.update()

    async def get_history(self, hours: int = 24) -> list[dict[str, Any]]:
        """Return health score history."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT broker, health_score, api_latency_ms, ws_latency_ms,
                           order_latency_ms, failure_rate_pct, reconnect_count,
                           is_connected, downtime_seconds, recorded_at
                    FROM broker_health_history
                    WHERE broker = :broker
                      AND recorded_at > NOW() - :hrs * INTERVAL '1 hour'
                    ORDER BY recorded_at DESC
                """), {"broker": self._broker, "hrs": hours})
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.debug("broker_health.get_history_failed: %s", exc)
            return []

    async def get_summary(self, hours: int = 24) -> dict[str, Any]:
        """Aggregate health stats over a window."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        AVG(health_score) AS avg_score,
                        MIN(health_score) AS min_score,
                        AVG(api_latency_ms) AS avg_api_ms,
                        AVG(failure_rate_pct) AS avg_fail_pct,
                        SUM(downtime_seconds) AS total_downtime_s,
                        SUM(reconnect_count) AS total_reconnects
                    FROM broker_health_history
                    WHERE broker = :broker
                      AND recorded_at > NOW() - :hrs * INTERVAL '1 hour'
                """), {"broker": self._broker, "hrs": hours})
                row = r.mappings().fetchone()
                return {"broker": self._broker, "hours": hours, **(dict(row) if row else {})}
        except Exception as exc:
            _log.debug("broker_health.get_summary_failed: %s", exc)
            return {"error": str(exc)}

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _read_metrics(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "api_latency_ms": None,
            "ws_latency_ms": None,
            "order_latency_ms": None,
            "failure_rate_pct": None,
            "reconnect_count": 0,
            "is_connected": None,
        }
        if self._redis is None:
            return metrics
        try:
            keys = [
                _REDIS_KEY_API_LATENCY, _REDIS_KEY_WS_LATENCY,
                _REDIS_KEY_ORDER_LAT, _REDIS_KEY_FAIL_COUNT,
                _REDIS_KEY_TOTAL_COUNT, _REDIS_KEY_RECONNECTS,
                _REDIS_KEY_CONNECTED,
            ]
            vals = await self._redis.mget(*keys)
            api_lat, ws_lat, ord_lat, fail_cnt, total_cnt, reconnects, connected = vals

            metrics["api_latency_ms"]   = float(api_lat) if api_lat else None
            metrics["ws_latency_ms"]    = float(ws_lat) if ws_lat else None
            metrics["order_latency_ms"] = float(ord_lat) if ord_lat else None
            metrics["reconnect_count"]  = int(reconnects) if reconnects else 0
            metrics["is_connected"]     = (connected == b"1" or connected == "1") if connected else None

            if fail_cnt and total_cnt:
                f, t = int(fail_cnt), int(total_cnt)
                metrics["failure_rate_pct"] = round(f / t * 100, 2) if t else 0.0
        except Exception as exc:
            _log.debug("broker_health.read_metrics_failed: %s", exc)
        return metrics

    async def _persist_snapshot(self, score: float, metrics: dict[str, Any]) -> None:
        try:
            async with self._sf() as db:
                await db.execute(text("""
                    INSERT INTO broker_health_history
                        (broker, health_score, api_latency_ms, ws_latency_ms,
                         order_latency_ms, failure_rate_pct, reconnect_count,
                         is_connected, recorded_at)
                    VALUES
                        (:broker, :score, :api_ms, :ws_ms,
                         :ord_ms, :fail_pct, :reconnects,
                         :connected, NOW())
                """), {
                    "broker": self._broker, "score": score,
                    "api_ms": metrics.get("api_latency_ms"),
                    "ws_ms":  metrics.get("ws_latency_ms"),
                    "ord_ms": metrics.get("order_latency_ms"),
                    "fail_pct": metrics.get("failure_rate_pct"),
                    "reconnects": metrics.get("reconnect_count", 0),
                    "connected": metrics.get("is_connected"),
                })
                await db.commit()
        except Exception as exc:
            _log.debug("broker_health.persist_failed: %s", exc)


# ── Pure score computation ────────────────────────────────────────────────────

def _compute_score(metrics: dict[str, Any]) -> float:
    """Compute broker health score 0-100."""
    score = 100.0

    # API latency: <200ms=0 penalty; 200ms–2s scales from 0→-35; >2s=-35
    api_ms = metrics.get("api_latency_ms")
    if api_ms is not None:
        if api_ms > 2000:
            score -= 35.0
        elif api_ms > 200:
            score -= ((api_ms - 200) / 1800) * 35.0

    # WS connectivity: disconnected = -30
    connected = metrics.get("is_connected")
    if connected is False:
        score -= 30.0

    # Failure rate: 0%=0 penalty; 5%+=−25
    fail_pct = metrics.get("failure_rate_pct")
    if fail_pct is not None:
        score -= min(fail_pct * 5.0, 25.0)

    # Reconnects: each -2 up to -10
    reconnects = metrics.get("reconnect_count") or 0
    score -= min(reconnects * 2.0, 10.0)

    return round(max(0.0, min(100.0, score)), 2)
