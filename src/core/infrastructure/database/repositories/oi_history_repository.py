"""OI History Repository — Phase 21.1 Part 2.

Read/write access to the oi_history_snapshots table.
All methods are fail-open: errors are logged, never raised.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


class OIHistoryRepository:
    """Persists and queries OI historical snapshots."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Write ─────────────────────────────────────────────────────────────────

    async def add(self, row: dict) -> None:
        """Persist one OI snapshot row. Fail-open."""
        try:
            async with self._sf() as db:
                await db.execute(
                    text("""
                        INSERT INTO oi_history_snapshots (
                            snapshot_at, symbol, tradingsymbol, expiry,
                            futures_price, oi, previous_oi, oi_change, oi_change_pct,
                            oi_direction, oi_regime,
                            rolling_avg_5, rolling_avg_15, rolling_avg_60,
                            price_change_pct, quality_tier, quality_score,
                            cache_age_seconds, is_anomaly, anomaly_type, is_contract_roll
                        ) VALUES (
                            :snapshot_at, :symbol, :tradingsymbol, :expiry,
                            :futures_price, :oi, :previous_oi, :oi_change, :oi_change_pct,
                            :oi_direction, :oi_regime,
                            :rolling_avg_5, :rolling_avg_15, :rolling_avg_60,
                            :price_change_pct, :quality_tier, :quality_score,
                            :cache_age_seconds, :is_anomaly, :anomaly_type, :is_contract_roll
                        )
                    """),
                    row,
                )
                await db.commit()
        except Exception as exc:
            _log.warning("oi_history.add_failed symbol=%s: %s", row.get("symbol"), exc)

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_history(self, symbol: str, hours: int = 24) -> list[dict]:
        """OI history for one symbol over the last N hours, oldest-first."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT snapshot_at, symbol, tradingsymbol, expiry,
                               futures_price, oi, oi_change, oi_change_pct,
                               oi_direction, oi_regime,
                               rolling_avg_5, rolling_avg_15, rolling_avg_60,
                               price_change_pct, quality_tier, quality_score,
                               cache_age_seconds, is_anomaly, anomaly_type, is_contract_roll
                        FROM oi_history_snapshots
                        WHERE symbol = :symbol AND snapshot_at >= :cutoff
                        ORDER BY snapshot_at
                    """),
                    {"symbol": symbol, "cutoff": cutoff},
                )
                return [dict(row._mapping) for row in r.fetchall()]
        except Exception as exc:
            _log.warning("oi_history.get_history_failed symbol=%s: %s", symbol, exc)
            return []

    async def get_latest(self, symbol: str) -> dict | None:
        """Most recent snapshot for a symbol."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT snapshot_at, symbol, tradingsymbol, expiry,
                               futures_price, oi, oi_change, oi_change_pct,
                               oi_direction, oi_regime, quality_tier, quality_score,
                               is_anomaly, anomaly_type
                        FROM oi_history_snapshots
                        WHERE symbol = :symbol
                        ORDER BY snapshot_at DESC
                        LIMIT 1
                    """),
                    {"symbol": symbol},
                )
                row = r.fetchone()
                return dict(row._mapping) if row else None
        except Exception as exc:
            _log.warning("oi_history.get_latest_failed symbol=%s: %s", symbol, exc)
            return None

    async def get_regime_distribution(self, symbol: str, days: int = 30) -> dict:
        """Count and percentage of each OI regime over the last N days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT oi_regime, COUNT(*) AS n
                        FROM oi_history_snapshots
                        WHERE symbol = :symbol
                          AND snapshot_at >= :cutoff
                          AND oi_regime IS NOT NULL
                        GROUP BY oi_regime
                        ORDER BY n DESC
                    """),
                    {"symbol": symbol, "cutoff": cutoff},
                )
                rows = r.fetchall()
            total = sum(int(row[1]) for row in rows)
            return {
                row[0]: {
                    "count": int(row[1]),
                    "pct":   round(int(row[1]) / total * 100, 1) if total else 0.0,
                }
                for row in rows
            }
        except Exception as exc:
            _log.warning("oi_history.regime_dist_failed symbol=%s: %s", symbol, exc)
            return {}

    async def get_market_breadth_latest(self, hours: int = 1) -> list[dict]:
        """Most-recent snapshot per symbol (for live OI breadth computation)."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT DISTINCT ON (symbol)
                            symbol, oi_change_pct, oi_direction, oi_regime,
                            quality_tier, snapshot_at
                        FROM oi_history_snapshots
                        WHERE snapshot_at >= :cutoff
                        ORDER BY symbol, snapshot_at DESC
                    """),
                    {"cutoff": cutoff},
                )
                return [dict(row._mapping) for row in r.fetchall()]
        except Exception as exc:
            _log.warning("oi_history.breadth_latest_failed: %s", exc)
            return []

    async def get_top_oi_movers(
        self,
        limit: int = 10,
        hours: int = 1,
    ) -> tuple[list[dict], list[dict]]:
        """Return (top_increases, top_decreases) based on most-recent snapshots."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT DISTINCT ON (symbol)
                            symbol, oi_change_pct, oi_direction, oi_regime,
                            futures_price, snapshot_at
                        FROM oi_history_snapshots
                        WHERE snapshot_at >= :cutoff AND oi_change_pct IS NOT NULL
                        ORDER BY symbol, snapshot_at DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = [dict(row._mapping) for row in r.fetchall()]
        except Exception as exc:
            _log.warning("oi_history.top_movers_failed: %s", exc)
            return [], []

        rows_with_pct = [r for r in rows if r.get("oi_change_pct") is not None]
        increases = sorted(rows_with_pct, key=lambda x: float(x["oi_change_pct"]), reverse=True)[:limit]
        decreases = sorted(rows_with_pct, key=lambda x: float(x["oi_change_pct"]))[:limit]
        return increases, decreases

    async def get_win_rate_by_regime(self, days: int = 90) -> list[dict]:
        """Win rate, MFE, capture ratio split by OI regime at signal time.

        Joins oi_history_snapshots (nearest snapshot) with signal_analytics.
        Uses oi_regime stored directly in signal_analytics (Phase 21.1).
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                            COALESCE(oi_regime, 'Unknown') AS regime,
                            COUNT(*) AS n,
                            ROUND(AVG(CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END)*100, 1)
                                AS win_rate_pct,
                            ROUND(AVG(mfe_pct)::numeric, 2) AS avg_mfe,
                            ROUND(AVG(capture_ratio)::numeric, 4) AS avg_capture,
                            ROUND(AVG(pnl_pct)::numeric, 4) AS avg_pnl,
                            ROUND(AVG(mae_pct)::numeric, 2) AS avg_mae
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND created_at >= :cutoff
                          AND outcome IN ('WIN','LOSS','EXPIRED','PARTIAL')
                        GROUP BY oi_regime
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("oi_history.win_rate_by_regime_failed: %s", exc)
            return []

        return [
            {
                "regime":       row[0],
                "n":            int(row[1] or 0),
                "win_rate_pct": float(row[2] or 0),
                "avg_mfe":      float(row[3] or 0),
                "avg_capture":  float(row[4] or 0),
                "avg_pnl":      float(row[5] or 0),
                "avg_mae":      float(row[6] or 0),
            }
            for row in rows
        ]

    # ── Maintenance ───────────────────────────────────────────────────────────

    async def cleanup_old(self, retention_days: int) -> int:
        """Delete snapshots older than retention_days. Returns rows deleted."""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("DELETE FROM oi_history_snapshots WHERE snapshot_at < :cutoff"),
                    {"cutoff": cutoff},
                )
                await db.commit()
                deleted = r.rowcount
            _log.info("oi_history.cleanup deleted=%d cutoff=%s", deleted, cutoff.date())
            return deleted
        except Exception as exc:
            _log.warning("oi_history.cleanup_failed: %s", exc)
            return 0
