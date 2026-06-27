"""ScanMetricsService — Phase 24 Operations.

Records per-scan-cycle metrics and exposes aggregated views.
Called at the end of each signal scanner cycle.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


class ScanMetricsService:
    """Stores and retrieves scan cycle performance metrics."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record(
        self,
        *,
        scan_duration_seconds: float | None = None,
        symbols_scanned: int | None = None,
        symbols_failed: int | None = None,
        signals_generated: int | None = None,
        signals_rejected: int | None = None,
        signals_gated: int | None = None,
        avg_score: float | None = None,
        avg_confidence: float | None = None,
        avg_data_quality: float | None = None,
        india_vix: float | None = None,
        market_context: str | None = None,
        execution_mode: str | None = None,
        gate_failures: dict[str, int] | None = None,
    ) -> None:
        """Insert one scan cycle record. Fail-silent — never raises."""
        try:
            now = datetime.now(UTC)
            gate_failures_json = json.dumps(gate_failures) if gate_failures else None
            async with self._sf() as db:
                await db.execute(
                    text(
                        "INSERT INTO scan_cycle_metrics "
                        "(cycle_at, scan_duration_seconds, symbols_scanned, symbols_failed, "
                        " signals_generated, signals_rejected, signals_gated, "
                        " avg_score, avg_confidence, avg_data_quality, "
                        " india_vix, market_context, execution_mode, gate_failures) "
                        "VALUES (:at, :dur, :sc, :sf, :sg, :sr, :sgd, "
                        "        :as_, :ac, :adq, :vix, :mc, :em, :gf)"
                    ),
                    {
                        "at":  now,
                        "dur": scan_duration_seconds,
                        "sc":  symbols_scanned,
                        "sf":  symbols_failed,
                        "sg":  signals_generated,
                        "sr":  signals_rejected,
                        "sgd": signals_gated,
                        "as_": avg_score,
                        "ac":  avg_confidence,
                        "adq": avg_data_quality,
                        "vix": india_vix,
                        "mc":  market_context,
                        "em":  execution_mode,
                        "gf":  gate_failures_json,
                    },
                )
                await db.commit()
        except Exception:
            _log.exception("scan_metrics.record_failed — skipping")

    async def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._sf() as db:
            r = await db.execute(
                text(
                    "SELECT id, cycle_at, scan_duration_seconds, symbols_scanned, "
                    "       symbols_failed, signals_generated, signals_rejected, signals_gated, "
                    "       avg_score, avg_confidence, avg_data_quality, "
                    "       india_vix, market_context, execution_mode, gate_failures "
                    "FROM scan_cycle_metrics "
                    "ORDER BY cycle_at DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
            rows = r.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get_summary(self, hours: int = 24) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(
                text(
                    "SELECT "
                    "  COUNT(*)                              AS cycles, "
                    "  AVG(scan_duration_seconds)           AS avg_dur, "
                    "  AVG(symbols_scanned)                 AS avg_sym, "
                    "  SUM(signals_generated)               AS total_signals, "
                    "  SUM(signals_rejected)                AS total_rejected, "
                    "  AVG(avg_score)                       AS avg_score, "
                    "  AVG(avg_confidence)                  AS avg_conf, "
                    "  AVG(avg_data_quality)                AS avg_dq, "
                    "  MAX(cycle_at)                        AS last_cycle "
                    f"FROM scan_cycle_metrics "  # noqa: S608
                    f"WHERE cycle_at > NOW() - INTERVAL '{hours} hours'"
                )
            )
            row = r.fetchone()

        if not row or not row[0]:
            return {"cycles": 0, "hours": hours}

        last = row[8]
        return {
            "hours":            hours,
            "cycles":           int(row[0]),
            "avg_duration_sec": round(float(row[1]), 2) if row[1] else None,
            "avg_symbols":      round(float(row[2]), 1) if row[2] else None,
            "total_signals":    int(row[3] or 0),
            "total_rejected":   int(row[4] or 0),
            "avg_score":        round(float(row[5]), 2) if row[5] else None,
            "avg_confidence":   round(float(row[6]), 2) if row[6] else None,
            "avg_data_quality": round(float(row[7]), 3) if row[7] else None,
            "last_cycle_at":    last.isoformat() if last else None,
        }

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        (
            id_, at, dur, sc, sf, sg, sr, sgd, as_, ac, adq, vix, mc, em, gf
        ) = row
        gate_failures = None
        if gf:
            try:
                gate_failures = json.loads(gf)
            except Exception:
                gate_failures = gf
        return {
            "id":                     id_,
            "cycle_at":               at.isoformat() if at else None,
            "scan_duration_seconds":  float(dur) if dur else None,
            "symbols_scanned":        sc,
            "symbols_failed":         sf,
            "signals_generated":      sg,
            "signals_rejected":       sr,
            "signals_gated":          sgd,
            "avg_score":              float(as_) if as_ else None,
            "avg_confidence":         float(ac)  if ac  else None,
            "avg_data_quality":       float(adq) if adq else None,
            "india_vix":              float(vix) if vix else None,
            "market_context":         mc,
            "execution_mode":         em,
            "gate_failures":          gate_failures,
        }
