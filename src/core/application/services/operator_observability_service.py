"""OperatorObservabilityService — Phase 20.6 Section 10.

Provides a live status panel for the operator dashboard.

Displays:
  Last Scan Time           — most recent signal_analytics record created_at
  Next Scan ETA            — computed: next 15-min candle close in IST
  Scanner Version          — from VERSION file or environment variable
  Symbols Processed Today  — distinct tickers scanned today (IST)
  Active Signals           — accepted signals with outcome IS NULL
  Candidates Today         — all signals generated today (regardless of acceptance)
  Signals Generated Today  — accepted today
  Signals Upgraded Today   — (not yet tracked; returns None if unavailable)
  Targets Hit Today        — target_hit=True today
  Stops Hit Today          — stop_hit=True today
  Current Regime Mix       — regime distribution of last 3-hour window
  Data Quality Score       — avg data_quality_score from last 50 signals
  Execution Quality Score  — avg from execution_lifecycle or None
  Portfolio Heat           — open accepted signals count as proxy

All reads are from signal_analytics and execution_lifecycle.
No writes. No production logic.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)
_IST = ZoneInfo("Asia/Kolkata")


def _ist_now() -> datetime:
    return datetime.now(_IST)


def _ist_today_start() -> datetime:
    """Midnight IST as UTC datetime."""
    ist = _ist_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return ist.astimezone(UTC)


def _next_scan_eta() -> str:
    """Next 15-minute candle close in IST (09:15, 09:30, … 15:30)."""
    now_ist = _ist_now()
    minute  = now_ist.minute
    next_q  = ((minute // 15) + 1) * 15
    if next_q >= 60:
        eta = now_ist.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        eta = now_ist.replace(minute=next_q, second=0, microsecond=0)
    # Market hours: 09:15 – 15:30 IST
    market_open  = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    if eta < market_open:
        eta = market_open
    if eta > market_close:
        return "MARKET_CLOSED"
    return eta.strftime("%H:%M IST")


def _scanner_version() -> str:
    """Read from VERSION file or SSA_VERSION env var."""
    env_ver = os.environ.get("SSA_VERSION")
    if env_ver:
        return env_ver
    for candidate in ["VERSION", "version.txt", "src/version.txt"]:
        p = Path(candidate)
        if p.exists():
            return p.read_text().strip()
    return "unknown"


class OperatorObservabilityService:
    """Live operator status panel — read-only, sub-second target response."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_status_panel(self) -> dict:
        """Full operator status panel — all sections."""
        today_start = _ist_today_start()
        try:
            today, regime_mix, dq, exec_qual, last_scan = await _gather(
                self._today_stats(today_start),
                self._regime_mix(today_start),
                self._data_quality(),
                self._execution_quality(today_start),
                self._last_scan_time(),
            )
        except Exception as exc:
            _log.warning("observability.panel_error: %s", exc)
            return {"error": str(exc)}

        return {
            "panel_type":             "OPERATOR_STATUS",
            "scanner_version":        _scanner_version(),
            "last_scan_time":         last_scan.get("last_scan_time"),
            "next_scan_eta":          _next_scan_eta(),
            "scanner_uptime_note":    "See container logs for exact uptime.",
            # Today's stats (IST day)
            "symbols_processed_today": today.get("symbols_today"),
            "candidates_today":        today.get("candidates_today"),
            "signals_generated_today": today.get("accepted_today"),
            "targets_hit_today":       today.get("wins_today"),
            "stops_hit_today":         today.get("losses_today"),
            "active_signals":          today.get("active_signals"),
            # Regime and quality
            "current_regime_mix":      regime_mix,
            "data_quality_score":      dq.get("avg_dq"),
            "execution_quality_score": exec_qual.get("avg_exec_quality"),
            "portfolio_heat":          today.get("portfolio_heat"),
            # Metadata
            "ist_time":                _ist_now().strftime("%Y-%m-%d %H:%M IST"),
            "evaluated_at":            datetime.now(UTC).isoformat(),
        }

    async def get_today_stats(self) -> dict:
        """Today's signal counts and outcomes (IST day)."""
        today_start = _ist_today_start()
        return await self._today_stats(today_start)

    async def get_regime_mix(self) -> dict:
        """Current regime distribution from the last 3 hours of signals."""
        today_start = _ist_today_start()
        return {"regime_mix": await self._regime_mix(today_start)}

    async def get_scanner_health(self) -> dict:
        """Scanner health: last scan time, active signal count, DQ."""
        dq, last = await _gather(self._data_quality(), self._last_scan_time())
        today_start = _ist_today_start()
        active = await self._today_stats(today_start)
        return {
            "scanner_version":    _scanner_version(),
            "last_scan_time":     last.get("last_scan_time"),
            "next_scan_eta":      _next_scan_eta(),
            "avg_data_quality":   dq.get("avg_dq"),
            "active_signals":     active.get("active_signals"),
            "health_status": (
                "HEALTHY"   if dq.get("avg_dq", 0) >= 80 else
                "DEGRADED"  if dq.get("avg_dq", 0) >= 60 else
                "POOR"
            ),
        }

    # ── Internal queries ──────────────────────────────────────────────────────

    async def _today_stats(self, today_start: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(DISTINCT ticker)                                          AS symbols_today,
                          COUNT(*)                                                        AS candidates_today,
                          COUNT(*) FILTER (WHERE was_accepted)                           AS accepted_today,
                          COUNT(*) FILTER (WHERE target_hit)                             AS wins_today,
                          COUNT(*) FILTER (WHERE stop_hit)                               AS losses_today,
                          COUNT(*) FILTER (WHERE was_accepted AND outcome IS NULL)       AS active_signals,
                          COUNT(*) FILTER (WHERE was_accepted AND outcome IS NULL)       AS portfolio_heat
                        FROM signal_analytics
                        WHERE created_at >= :today
                    """),
                    {"today": today_start},
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("observability.today_stats_error: %s", exc)
            return {}

        return {
            "symbols_today":    int(row[0] or 0),
            "candidates_today": int(row[1] or 0),
            "accepted_today":   int(row[2] or 0),
            "wins_today":       int(row[3] or 0),
            "losses_today":     int(row[4] or 0),
            "active_signals":   int(row[5] or 0),
            "portfolio_heat":   int(row[6] or 0),
        }

    async def _regime_mix(self, today_start: datetime) -> list[dict]:
        cutoff = datetime.now(UTC) - timedelta(hours=3)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT regime, COUNT(*) AS n
                        FROM signal_analytics
                        WHERE created_at >= :cutoff
                        GROUP BY regime
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("observability.regime_mix_error: %s", exc)
            return []

        total = sum(int(r[1] or 0) for r in rows)
        return [
            {
                "regime": row[0],
                "count":  int(row[1] or 0),
                "pct":    round(int(row[1] or 0) / max(total, 1) * 100, 1),
            }
            for row in rows
        ]

    async def _data_quality(self) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT ROUND(AVG(data_quality_score)::numeric, 1)
                        FROM signal_analytics
                        WHERE data_quality_score IS NOT NULL
                          AND created_at >= NOW() - INTERVAL '2 hours'
                    """),
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("observability.dq_error: %s", exc)
            return {}
        return {"avg_dq": float(row[0]) if row and row[0] else None}

    async def _execution_quality(self, today_start: datetime) -> dict:
        """Avg execution quality from execution_lifecycle slippage."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          ROUND((100 - AVG(ABS(total_slippage_pct)) * 20)::numeric, 1) AS exec_quality
                        FROM execution_lifecycle
                        WHERE created_at >= :today
                          AND total_slippage_pct IS NOT NULL
                    """),
                    {"today": today_start},
                )
                row = r.fetchone()
        except Exception:
            return {"avg_exec_quality": None}
        return {"avg_exec_quality": float(row[0]) if row and row[0] else None}

    async def _last_scan_time(self) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("SELECT MAX(created_at) FROM signal_analytics"),
                )
                row = r.fetchone()
        except Exception:
            return {"last_scan_time": None}
        ts = row[0] if row else None
        return {"last_scan_time": ts.isoformat() if ts else None}


# ── Minimal async gather ──────────────────────────────────────────────────────

async def _gather(*coros):
    import asyncio
    results = await asyncio.gather(*coros, return_exceptions=True)
    return [r if not isinstance(r, Exception) else {} for r in results]
