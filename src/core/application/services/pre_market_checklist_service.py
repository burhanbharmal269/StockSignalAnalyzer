"""PreMarketChecklistService — Phase 24 Operations.

Auto-executes a pre-market readiness checklist before market open (≈09:00 IST).
Stores results in `pre_market_checks` and logs a structured startup summary.

Run as a background coroutine that triggers once per trading day.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.platform_readiness_service import PlatformReadinessService

_log = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_PRE_MARKET_HOUR_IST = 9   # 09:00 IST trigger
_PRE_MARKET_MIN_IST  = 0


class PreMarketChecklistService:
    """Runs and stores a pre-market readiness checklist once per trading day."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        platform_readiness_svc: PlatformReadinessService,
    ) -> None:
        self._sf      = session_factory
        self._readiness = platform_readiness_svc

    async def run(self) -> None:
        """Background loop — waits for 09:00 IST each trading day and runs checklist."""
        while True:
            try:
                await self._wait_until_pre_market()
                await self.run_now()
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("pre_market_checklist.run_error — will retry next cycle")
            # Sleep 60 min after running to avoid double-triggering
            await asyncio.sleep(3600)

    async def run_now(self) -> dict:
        """Execute the checklist immediately and persist results."""
        _log.info("pre_market_checklist.starting")
        readiness = await self._readiness.get_readiness()
        comps = readiness.get("components", {})

        db_ok          = comps.get("database",         {}).get("status") == "READY"
        redis_ok       = comps.get("redis",            {}).get("status") == "READY"
        kite_ok        = comps.get("kite",             {}).get("status") == "READY"
        ws_ok          = comps.get("websocket",        {}).get("status") in ("READY", "WARNING")
        scanner_ok     = comps.get("scanner",          {}).get("status") in ("READY", "WARNING")
        option_ok      = comps.get("option_chain",     {}).get("status") in ("READY", "WARNING")
        candles_ok     = comps.get("market_data",      {}).get("status") in ("READY", "WARNING")

        # Get execution lock mode from Redis
        exec_mode: str | None = None
        try:
            import redis.asyncio as aioredis
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            r = aioredis.from_url(url, socket_connect_timeout=2)
            val = await r.get("execution_lock:mode")
            exec_mode = val.decode() if val else None
            await r.aclose()
        except Exception:
            pass

        failed_checks: list[str] = []
        if not db_ok:    failed_checks.append("database")
        if not redis_ok: failed_checks.append("redis")
        if not kite_ok:  failed_checks.append("kite")
        if not ws_ok:    failed_checks.append("websocket")
        if not scanner_ok: failed_checks.append("scanner")
        if not option_ok:  failed_checks.append("option_chain")
        if not candles_ok: failed_checks.append("candles")

        critical_ok = db_ok and redis_ok
        overall = "READY" if (critical_ok and not failed_checks) else (
            "WARNING" if critical_ok else "NOT_READY"
        )

        now   = datetime.now(UTC)
        today = date.today()

        failed_json = json.dumps(failed_checks) if failed_checks else None
        notes = readiness.get("recommendation")

        async with self._sf() as db:
            await db.execute(
                text(
                    "INSERT INTO pre_market_checks "
                    "(check_date, check_time, db_connected, redis_connected, kite_authenticated, "
                    " websocket_connected, scanner_healthy, option_chain_healthy, candles_available, "
                    " execution_lock_mode, overall_status, failed_checks, notes) "
                    "VALUES (:date, :now, :db, :redis, :kite, :ws, :scan, :opt, :can, "
                    "        :em, :overall, :fc, :notes)"
                ),
                {
                    "date":    today,
                    "now":     now,
                    "db":      db_ok,
                    "redis":   redis_ok,
                    "kite":    kite_ok,
                    "ws":      ws_ok,
                    "scan":    scanner_ok,
                    "opt":     option_ok,
                    "can":     candles_ok,
                    "em":      exec_mode,
                    "overall": overall,
                    "fc":      failed_json,
                    "notes":   notes,
                },
            )
            await db.commit()

        _log.info(
            "pre_market_checklist.complete overall=%s failed=%s exec_mode=%s",
            overall, failed_checks, exec_mode,
        )
        return {
            "overall":            overall,
            "failed_checks":      failed_checks,
            "execution_lock_mode": exec_mode,
            "checked_at":         now.isoformat(),
        }

    async def get_latest(self) -> dict | None:
        async with self._sf() as db:
            r = await db.execute(text(
                "SELECT check_date, check_time, db_connected, redis_connected, "
                "       kite_authenticated, websocket_connected, scanner_healthy, "
                "       option_chain_healthy, candles_available, execution_lock_mode, "
                "       overall_status, failed_checks, notes "
                "FROM pre_market_checks "
                "ORDER BY check_time DESC LIMIT 1"
            ))
            row = r.fetchone()
        if not row:
            return None
        return {
            "check_date":          str(row[0]),
            "check_time":          row[1].isoformat() if row[1] else None,
            "db_connected":        row[2],
            "redis_connected":     row[3],
            "kite_authenticated":  row[4],
            "websocket_connected": row[5],
            "scanner_healthy":     row[6],
            "option_chain_healthy": row[7],
            "candles_available":   row[8],
            "execution_lock_mode": row[9],
            "overall_status":      row[10],
            "failed_checks":       json.loads(row[11]) if row[11] else [],
            "notes":               row[12],
        }

    async def get_history(self, limit: int = 30) -> list[dict]:
        async with self._sf() as db:
            r = await db.execute(
                text(
                    "SELECT check_date, check_time, overall_status, failed_checks, "
                    "       kite_authenticated, execution_lock_mode, notes "
                    "FROM pre_market_checks ORDER BY check_time DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
            rows = r.fetchall()
        result = []
        for row in rows:
            result.append({
                "check_date":         str(row[0]),
                "check_time":         row[1].isoformat() if row[1] else None,
                "overall_status":     row[2],
                "failed_checks":      json.loads(row[3]) if row[3] else [],
                "kite_authenticated": row[4],
                "execution_lock_mode": row[5],
                "notes":              row[6],
            })
        return result

    # ── Scheduling ────────────────────────────────────────────────────────────

    async def _wait_until_pre_market(self) -> None:
        """Sleep until the next 09:00 IST weekday."""
        while True:
            now_ist = datetime.now(_IST)
            # Check if today already had a pre-market check
            already_ran = await self._ran_today()
            if not already_ran:
                target = now_ist.replace(
                    hour=_PRE_MARKET_HOUR_IST,
                    minute=_PRE_MARKET_MIN_IST,
                    second=0,
                    microsecond=0,
                )
                if now_ist >= target and now_ist.weekday() < 5:
                    return  # We're past 09:00 IST on a weekday and haven't run yet
                # Calculate sleep time to next 09:00 IST weekday
                if now_ist < target and now_ist.weekday() < 5:
                    sleep_sec = (target - now_ist).total_seconds()
                    _log.info("pre_market_checklist.waiting sleep_sec=%.0f", sleep_sec)
                    await asyncio.sleep(sleep_sec)
                    return
            # Sleep 30 min and re-check (handles weekends, already-ran days)
            await asyncio.sleep(1800)

    async def _ran_today(self) -> bool:
        today = date.today()
        async with self._sf() as db:
            r = await db.execute(
                text("SELECT 1 FROM pre_market_checks WHERE check_date=:d LIMIT 1"),
                {"d": today},
            )
            return r.fetchone() is not None
