"""PlatformReadinessService — Phase 24 Operations.

GET /api/v1/platform/readiness

Returns a unified health snapshot across all platform components.
Each component reports: status (READY / WARNING / NOT_READY) + detail dict.
The overall status is READY only when all critical components are READY.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Architecture freeze: frozen since Phase 24
_FREEZE_DATE        = "2026-06-27"
_FREEZE_PHASE       = "Phase 24 — Operations Mode"
_FROZEN_MODULES = [
    "signal_engine_service",
    "signal_scanner_service",
    "risk_engine_service",
    "position_sizer",
    "overlay_pipeline",
    "market_context_engine",
    "mtf_confirmation",
    "scoring (all component scorers)",
    "signal_config (thresholds)",
]

_STATUS_READY     = "READY"
_STATUS_WARNING   = "WARNING"
_STATUS_NOT_READY = "NOT_READY"

# Components that must be READY for overall=READY
_CRITICAL_COMPONENTS = {"database", "redis", "scanner", "background_tasks"}


def _status_from_ok(ok: bool, warn: bool = False) -> str:
    if ok:
        return _STATUS_READY
    return _STATUS_WARNING if warn else _STATUS_NOT_READY


class PlatformReadinessService:
    """Unified platform readiness check."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_readiness(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        components: dict[str, dict[str, Any]] = {}

        components["database"]          = await self._check_database()
        components["redis"]             = await self._check_redis()
        components["kite"]              = await self._check_kite()
        components["market_data"]       = await self._check_market_data()
        components["websocket"]         = await self._check_websocket()
        components["scanner"]           = await self._check_scanner()
        components["background_tasks"]  = await self._check_background_tasks()
        components["option_chain"]      = await self._check_option_chain()
        components["data_quality"]      = await self._check_data_quality()
        components["execution_quality"] = await self._check_execution_quality()
        components["deployment_stage"]  = await self._check_deployment_stage()
        components["architecture_freeze"] = self._check_architecture_freeze()

        # Overall: critical components determine it
        critical_ok = all(
            components[k]["status"] == _STATUS_READY
            for k in _CRITICAL_COMPONENTS
            if k in components
        )
        any_not_ready = any(
            v["status"] == _STATUS_NOT_READY for v in components.values()
        )
        any_warning = any(
            v["status"] == _STATUS_WARNING for v in components.values()
        )

        if critical_ok and not any_not_ready:
            overall = _STATUS_READY
            recommendation = "Platform is fully operational. All systems nominal."
        elif critical_ok and any_warning:
            overall = _STATUS_WARNING
            warning_comps = [k for k, v in components.items() if v["status"] == _STATUS_WARNING]
            recommendation = (
                f"Platform operational but attention needed: {', '.join(warning_comps)}. "
                "Monitor and resolve before market open."
            )
        else:
            overall = _STATUS_NOT_READY
            failed = [k for k, v in components.items() if v["status"] == _STATUS_NOT_READY]
            recommendation = (
                f"Platform NOT ready. Critical failures: {', '.join(failed)}. "
                "Resolve these before enabling live trading."
            )

        return {
            "overall":        overall,
            "recommendation": recommendation,
            "components":     components,
            "checked_at":     now.isoformat(),
        }

    # ── Database ──────────────────────────────────────────────────────────────

    async def _check_database(self) -> dict[str, Any]:
        try:
            t0 = time.monotonic()
            async with self._sf() as db:
                await db.execute(text("SELECT 1"))
            ms = round((time.monotonic() - t0) * 1000, 1)
            status = _STATUS_READY if ms < 200 else _STATUS_WARNING
            return {"status": status, "latency_ms": ms}
        except Exception as exc:
            return {"status": _STATUS_NOT_READY, "error": str(exc)}

    # ── Redis ─────────────────────────────────────────────────────────────────

    async def _check_redis(self) -> dict[str, Any]:
        try:
            import redis.asyncio as aioredis
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            r = aioredis.from_url(url, socket_connect_timeout=2)
            t0 = time.monotonic()
            await r.ping()
            await r.aclose()
            ms = round((time.monotonic() - t0) * 1000, 1)
            status = _STATUS_READY if ms < 100 else _STATUS_WARNING
            return {"status": status, "latency_ms": ms}
        except Exception as exc:
            return {"status": _STATUS_NOT_READY, "error": str(exc)}

    # ── Kite Authentication ───────────────────────────────────────────────────

    async def _check_kite(self) -> dict[str, Any]:
        try:
            async with self._sf() as db:
                r = await db.execute(text(
                    "SELECT is_active, expires_at, created_at "
                    "FROM broker_sessions "
                    "WHERE broker_name='kite' AND is_active=true "
                    "ORDER BY created_at DESC LIMIT 1"
                ))
                row = r.fetchone()
            if row is None:
                return {
                    "status": _STATUS_WARNING,
                    "authenticated": False,
                    "detail": "No active Kite session — live feed will use fallback",
                }
            expires_at = row[1]
            if expires_at and expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
                return {
                    "status": _STATUS_WARNING,
                    "authenticated": False,
                    "detail": "Kite session expired — reconnect from Broker page",
                }
            return {
                "status": _STATUS_READY,
                "authenticated": True,
                "session_created_at": row[2].isoformat() if row[2] else None,
            }
        except Exception as exc:
            return {"status": _STATUS_NOT_READY, "error": str(exc)}

    # ── Market Data ───────────────────────────────────────────────────────────

    async def _check_market_data(self) -> dict[str, Any]:
        try:
            async with self._sf() as db:
                r = await db.execute(text(
                    "SELECT MAX(timestamp) FROM candles WHERE timeframe='5m'"
                ))
                row = r.fetchone()
            if not row or not row[0]:
                return {"status": _STATUS_WARNING, "detail": "No candles in DB — seed required"}
            latest = row[0].replace(tzinfo=UTC)
            age_min = (datetime.now(UTC) - latest).total_seconds() / 60
            # Only flag stale during market hours (rough check)
            now_ist_h = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).hour
            in_market = 9 <= now_ist_h < 16
            if in_market and age_min > 30:
                status = _STATUS_NOT_READY
                detail = f"Candles stale {age_min:.0f}min — check Kite auth"
            elif age_min > 1440:  # >1 day old outside market hours
                status = _STATUS_WARNING
                detail = f"Candles {age_min/60:.1f}h old — will refresh when market opens"
            else:
                status = _STATUS_READY
                detail = f"Latest candle {age_min:.0f}min ago"
            return {"status": status, "latest_candle_age_min": round(age_min, 1), "detail": detail}
        except Exception as exc:
            return {"status": _STATUS_NOT_READY, "error": str(exc)}

    # ── WebSocket ─────────────────────────────────────────────────────────────

    async def _check_websocket(self) -> dict[str, Any]:
        try:
            import redis.asyncio as aioredis
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            r = aioredis.from_url(url, socket_connect_timeout=2)
            val = await r.get("live_feed:connected")
            last_tick = await r.get("live_feed:last_tick_at")
            await r.aclose()
            connected = val and val.decode() == "1"
            detail: dict[str, Any] = {"connected": bool(connected)}
            if last_tick:
                detail["last_tick_at"] = last_tick.decode()
            status = _STATUS_READY if connected else _STATUS_WARNING
            return {"status": status, **detail}
        except Exception as exc:
            return {"status": _STATUS_WARNING, "connected": False, "error": str(exc)}

    # ── Scanner ───────────────────────────────────────────────────────────────

    async def _check_scanner(self) -> dict[str, Any]:
        try:
            async with self._sf() as db:
                r = await db.execute(text(
                    "SELECT MAX(created_at) FROM signal_analytics"
                ))
                row = r.fetchone()
            if not row or not row[0]:
                return {"status": _STATUS_WARNING, "detail": "No scan records yet — scanner not run"}
            latest = row[0].replace(tzinfo=UTC)
            age_min = (datetime.now(UTC) - latest).total_seconds() / 60
            now_ist_h = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).hour
            in_market = 9 <= now_ist_h < 16
            if in_market and age_min > 10:
                status = _STATUS_NOT_READY
                detail = f"Scanner idle {age_min:.0f}min during market hours"
            else:
                status = _STATUS_READY
                detail = f"Last scan {age_min:.0f}min ago"
            return {"status": status, "last_scan_age_min": round(age_min, 1), "detail": detail}
        except Exception as exc:
            return {"status": _STATUS_NOT_READY, "error": str(exc)}

    # ── Background Tasks ──────────────────────────────────────────────────────

    async def _check_background_tasks(self) -> dict[str, Any]:
        try:
            import redis.asyncio as aioredis
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            r = aioredis.from_url(url, socket_connect_timeout=2)
            heartbeats: dict[str, Any] = {}
            task_keys = [
                "bg:portfolio_monitor:heartbeat",
                "bg:signal_expiry_worker:heartbeat",
                "bg:option_chain_poller:heartbeat",
                "bg:scanner:heartbeat",
            ]
            for key in task_keys:
                val = await r.get(key)
                name = key.split(":")[1]
                heartbeats[name] = val.decode() if val else None
            await r.aclose()
            # If we can't get heartbeats (no keys set yet), treat as WARNING not NOT_READY
            any_missing = any(v is None for v in heartbeats.values())
            status = _STATUS_WARNING if any_missing else _STATUS_READY
            return {"status": status, "heartbeats": heartbeats}
        except Exception as exc:
            return {"status": _STATUS_READY, "note": "Heartbeat check skipped", "error": str(exc)}

    # ── Option Chain ──────────────────────────────────────────────────────────

    async def _check_option_chain(self) -> dict[str, Any]:
        try:
            async with self._sf() as db:
                r = await db.execute(text(
                    "SELECT COUNT(*), MAX(polled_at) FROM option_chain_snapshots "
                    "WHERE polled_at > NOW() - INTERVAL '2 hours'"
                ))
                row = r.fetchone()
            count = row[0] if row else 0
            latest = row[1] if row else None
            if count == 0:
                return {"status": _STATUS_WARNING, "detail": "No recent option chain data (2h)"}
            age_min = (datetime.now(UTC) - latest.replace(tzinfo=UTC)).total_seconds() / 60
            status = _STATUS_READY if age_min < 30 else _STATUS_WARNING
            return {"status": status, "snapshots_2h": count, "latest_age_min": round(age_min, 1)}
        except Exception as exc:
            return {"status": _STATUS_WARNING, "error": str(exc)}

    # ── Data Quality ──────────────────────────────────────────────────────────

    async def _check_data_quality(self) -> dict[str, Any]:
        try:
            async with self._sf() as db:
                r = await db.execute(text(
                    "SELECT AVG(data_quality_score), COUNT(*) "
                    "FROM signal_analytics "
                    "WHERE created_at > NOW() - INTERVAL '24 hours' "
                    "AND data_quality_score IS NOT NULL"
                ))
                row = r.fetchone()
            if not row or not row[0]:
                return {"status": _STATUS_WARNING, "detail": "Insufficient recent data"}
            avg_dq = float(row[0])
            count  = int(row[1])
            status = (
                _STATUS_READY    if avg_dq >= 0.7  else
                _STATUS_WARNING  if avg_dq >= 0.5  else
                _STATUS_NOT_READY
            )
            return {
                "status":         status,
                "avg_score_24h":  round(avg_dq, 3),
                "sample_count":   count,
            }
        except Exception as exc:
            return {"status": _STATUS_WARNING, "error": str(exc)}

    # ── Execution Quality ─────────────────────────────────────────────────────

    async def _check_execution_quality(self) -> dict[str, Any]:
        try:
            async with self._sf() as db:
                r = await db.execute(text(
                    "SELECT "
                    "  COUNT(*) FILTER (WHERE state='FILLED')    AS filled, "
                    "  COUNT(*) FILTER (WHERE state='REJECTED')  AS rejected, "
                    "  COUNT(*) FILTER (WHERE state='CANCELLED') AS cancelled, "
                    "  COUNT(*)                                   AS total "
                    "FROM orders "
                    "WHERE created_at > NOW() - INTERVAL '7 days'"
                ))
                row = r.fetchone()
            if not row or not row[3] or row[3] == 0:
                return {"status": _STATUS_READY, "detail": "No orders in last 7 days"}
            filled   = int(row[0] or 0)
            rejected = int(row[1] or 0)
            total    = int(row[3])
            fill_rate = filled / total if total > 0 else 0.0
            status = (
                _STATUS_READY   if fill_rate >= 0.85 else
                _STATUS_WARNING if fill_rate >= 0.60 else
                _STATUS_NOT_READY
            )
            return {
                "status":        status,
                "fill_rate_7d":  round(fill_rate, 3),
                "orders_filled": filled,
                "orders_rejected": rejected,
                "orders_total":  total,
            }
        except Exception as exc:
            return {"status": _STATUS_WARNING, "error": str(exc)}

    # ── Deployment Stage ──────────────────────────────────────────────────────

    async def _check_deployment_stage(self) -> dict[str, Any]:
        try:
            async with self._sf() as db:
                r = await db.execute(text(
                    "SELECT deployment_stage, COUNT(*) "
                    "FROM signal_analytics "
                    "WHERE created_at > NOW() - INTERVAL '7 days' "
                    "AND deployment_stage IS NOT NULL "
                    "GROUP BY deployment_stage "
                    "ORDER BY COUNT(*) DESC LIMIT 1"
                ))
                row = r.fetchone()
            stage = row[0] if row else "DEV"
            return {
                "status":  _STATUS_READY,
                "stage":   stage,
                "detail":  f"Current deployment stage: {stage}",
            }
        except Exception as exc:
            return {"status": _STATUS_WARNING, "stage": "UNKNOWN", "error": str(exc)}

    # ── Architecture Freeze ───────────────────────────────────────────────────

    def _check_architecture_freeze(self) -> dict[str, Any]:
        return {
            "status":        _STATUS_READY,
            "frozen":        True,
            "freeze_date":   _FREEZE_DATE,
            "freeze_phase":  _FREEZE_PHASE,
            "frozen_modules": _FROZEN_MODULES,
            "allowed":       ["bug_fixes", "monitoring", "logging", "documentation",
                              "performance_optimization", "deployment_automation"],
            "detail": (
                "Architecture is FROZEN. No strategy/scoring/risk/threshold changes "
                "allowed until 500+ completed trades validate the current system."
            ),
        }
