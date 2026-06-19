"""ExecutionLifecycleService — Phase 17 execution tracking and quality scoring.

Tracks the full order lifecycle per signal:
  SIGNAL_GENERATED → ORDER_SUBMITTED → ORDER_FILLED
                                     → ORDER_REJECTED
                                     → ORDER_CANCELLED

Records slippage (entry + exit separately) and latency timestamps.
Computes Execution Quality Score (0-100) for dashboard and scaling gate.

Phase 17 Sections:
  D — Slippage Tracking (entry/exit/total, per symbol/regime/window)
  E — Fill Quality (fill rate, reject rate, avg fill delay, quality score)
  F — Broker Latency (signal_to_order_ms, order_to_fill_ms, signal_to_fill_ms)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Alert thresholds
_HIGH_SLIPPAGE_PCT       = 0.5     # alert when avg total slippage exceeds this
_LATENCY_DEGRADATION_MS  = 5000.0  # alert when avg signal_to_fill exceeds 5 seconds

# Execution Quality Score deduction table
_EQS_DEDUCTIONS = {
    "fill_rate_low":       20,   # fill_rate < 95%
    "reject_rate_high":    15,   # reject_rate > 5%
    "latency_high":        20,   # avg_signal_to_fill_ms > 5000
    "latency_medium":      10,   # avg_signal_to_fill_ms > 2000
    "slippage_critical":   40,   # avg_total_slippage_pct > 0.5%
    "slippage_high":       25,   # avg_total_slippage_pct > 0.3%
    "slippage_medium":     10,   # avg_total_slippage_pct > 0.2%
}

_LIFECYCLE_STATUSES = frozenset({
    "SIGNAL_GENERATED",
    "ORDER_SUBMITTED",
    "ORDER_FILLED",
    "ORDER_REJECTED",
    "ORDER_CANCELLED",
})


class ExecutionLifecycleService:
    """Records lifecycle events and computes execution quality metrics."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    async def record_signal_generated(
        self,
        *,
        signal_id: str,
        symbol: str,
        regime: str | None = None,
        direction: str | None = None,
        expected_entry_price: float | None = None,
        generated_at: datetime | None = None,
    ) -> int:
        """Create lifecycle row when signal is emitted. Returns row id."""
        ts = generated_at or datetime.now(UTC)
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    INSERT INTO execution_lifecycle
                      (signal_id, symbol, regime, direction,
                       expected_entry_price, signal_generated_at,
                       status, broker_name)
                    VALUES
                      (:sid, :sym, :reg, :dir, :entry_exp, :gen_at, 'SIGNAL_GENERATED', 'zerodha')
                    RETURNING id
                """),
                {
                    "sid": signal_id, "sym": symbol, "reg": regime, "dir": direction,
                    "entry_exp": expected_entry_price, "gen_at": ts,
                },
            )
            row_id = r.scalar()
            await db.commit()
        return row_id

    async def record_order_submitted(
        self,
        *,
        signal_id: str,
        order_id: str,
        submitted_at: datetime | None = None,
    ) -> None:
        ts = submitted_at or datetime.now(UTC)
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT id, signal_generated_at FROM execution_lifecycle
                    WHERE signal_id = :sid ORDER BY created_at DESC LIMIT 1
                """),
                {"sid": signal_id},
            )
            row = r.fetchone()
            if not row:
                return
            row_id = row[0]
            gen_at = row[1]
            s2o_ms = None
            if gen_at:
                g = gen_at if gen_at.tzinfo else gen_at.replace(tzinfo=UTC)
                s2o_ms = (ts - g).total_seconds() * 1000

            await db.execute(
                text("""
                    UPDATE execution_lifecycle SET
                        order_id = :oid,
                        order_submitted_at = :ts,
                        signal_to_order_ms = :s2o,
                        status = 'ORDER_SUBMITTED',
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {"oid": order_id, "ts": ts, "s2o": s2o_ms, "id": row_id},
            )
            await db.commit()

    async def record_order_filled(
        self,
        *,
        signal_id: str,
        actual_entry_price: float | None = None,
        filled_at: datetime | None = None,
    ) -> None:
        ts = filled_at or datetime.now(UTC)
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT id, signal_generated_at, order_submitted_at, expected_entry_price
                    FROM execution_lifecycle WHERE signal_id = :sid
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"sid": signal_id},
            )
            row = r.fetchone()
            if not row:
                return
            row_id, gen_at, sub_at, exp_entry = row

            # Latency
            o2f_ms = None
            if sub_at:
                s = sub_at if sub_at.tzinfo else sub_at.replace(tzinfo=UTC)
                o2f_ms = (ts - s).total_seconds() * 1000
            s2f_ms = None
            if gen_at:
                g = gen_at if gen_at.tzinfo else gen_at.replace(tzinfo=UTC)
                s2f_ms = (ts - g).total_seconds() * 1000

            # Entry slippage
            entry_slip = None
            if exp_entry and actual_entry_price and float(exp_entry) > 0:
                entry_slip = (actual_entry_price - float(exp_entry)) / float(exp_entry) * 100

            await db.execute(
                text("""
                    UPDATE execution_lifecycle SET
                        actual_entry_price = :act_entry,
                        entry_slippage_pct = :entry_slip,
                        total_slippage_pct = :entry_slip,
                        order_to_fill_ms   = :o2f,
                        signal_to_fill_ms  = :s2f,
                        order_filled_at    = :ts,
                        status             = 'ORDER_FILLED',
                        updated_at         = NOW()
                    WHERE id = :id
                """),
                {
                    "act_entry": actual_entry_price, "entry_slip": entry_slip,
                    "o2f": o2f_ms, "s2f": s2f_ms, "ts": ts, "id": row_id,
                },
            )
            await db.commit()

    async def record_exit_fill(
        self,
        *,
        signal_id: str,
        expected_exit_price: float | None = None,
        actual_exit_price: float | None = None,
    ) -> None:
        """Record exit price and compute exit + total slippage."""
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT id, entry_slippage_pct
                    FROM execution_lifecycle WHERE signal_id = :sid
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"sid": signal_id},
            )
            row = r.fetchone()
            if not row:
                return
            row_id, entry_slip = row

            exit_slip = None
            if expected_exit_price and actual_exit_price and float(expected_exit_price) > 0:
                # For exit: negative slippage = got less than expected
                exit_slip = (float(expected_exit_price) - actual_exit_price) / float(expected_exit_price) * 100

            total_slip = None
            if entry_slip is not None and exit_slip is not None:
                total_slip = float(entry_slip) + float(exit_slip)

            await db.execute(
                text("""
                    UPDATE execution_lifecycle SET
                        expected_exit_price = :exp_exit,
                        actual_exit_price   = :act_exit,
                        exit_slippage_pct   = :exit_slip,
                        total_slippage_pct  = :total_slip,
                        updated_at          = NOW()
                    WHERE id = :id
                """),
                {
                    "exp_exit": expected_exit_price, "act_exit": actual_exit_price,
                    "exit_slip": exit_slip, "total_slip": total_slip, "id": row_id,
                },
            )
            await db.commit()

    async def record_order_rejected(
        self,
        *,
        signal_id: str,
        reason: str | None = None,
    ) -> None:
        async with self._sf() as db:
            await db.execute(
                text("""
                    UPDATE execution_lifecycle SET
                        order_rejected_at = NOW(),
                        rejection_reason  = :reason,
                        status            = 'ORDER_REJECTED',
                        updated_at        = NOW()
                    WHERE signal_id = :sid
                """),
                {"reason": reason, "sid": signal_id},
            )
            await db.commit()

    async def record_order_cancelled(
        self,
        *,
        signal_id: str,
        reason: str | None = None,
    ) -> None:
        async with self._sf() as db:
            await db.execute(
                text("""
                    UPDATE execution_lifecycle SET
                        order_cancelled_at = NOW(),
                        rejection_reason   = :reason,
                        status             = 'ORDER_CANCELLED',
                        updated_at         = NOW()
                    WHERE signal_id = :sid
                """),
                {"reason": reason, "sid": signal_id},
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Section D — Slippage Report
    # ------------------------------------------------------------------

    async def get_slippage_report(
        self,
        lookback_days: int = 30,
        group_by: str = "symbol",     # "symbol" | "regime" | "time_window"
    ) -> dict:
        """Slippage metrics per grouping dimension with HIGH_SLIPPAGE alert."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        group_col = {
            "symbol":      "symbol",
            "regime":      "COALESCE(regime, 'UNKNOWN')",
            "time_window": (
                "CASE "
                "WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') = 9 "
                "  AND EXTRACT(MINUTE FROM created_at AT TIME ZONE 'Asia/Kolkata') >= 30 THEN '09:30-10:30' "
                "WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') = 10 THEN '09:30-10:30' "
                "WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') IN (11,12) THEN '10:30-12:00' "
                "WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') = 13 THEN '12:00-13:30' "
                "ELSE '13:30-14:30' END"
            ),
        }.get(group_by, "symbol")

        try:
            async with self._sf() as db:
                r = await db.execute(
                    text(f"""
                        SELECT
                          {group_col}                              AS group_key,
                          COUNT(*)                                 AS trades,
                          ROUND(AVG(entry_slippage_pct), 4)       AS avg_entry_slip_pct,
                          ROUND(AVG(exit_slippage_pct),  4)       AS avg_exit_slip_pct,
                          ROUND(AVG(total_slippage_pct), 4)       AS avg_total_slip_pct,
                          ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP
                            (ORDER BY total_slippage_pct), 4)     AS median_slip_pct,
                          ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP
                            (ORDER BY total_slippage_pct), 4)     AS p95_slip_pct
                        FROM execution_lifecycle
                        WHERE status = 'ORDER_FILLED'
                          AND total_slippage_pct IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY 1
                        ORDER BY avg_total_slip_pct DESC NULLS LAST
                    """),
                    {"cutoff": cutoff},
                )
                rows = [dict(r._mapping) for r in r.fetchall()]

            overall_avg = None
            if rows:
                slips = [float(r.get("avg_total_slip_pct") or 0) for r in rows]
                overall_avg = round(sum(slips) / len(slips), 4)

            alert = None
            if overall_avg is not None and overall_avg > _HIGH_SLIPPAGE_PCT:
                alert = "HIGH_SLIPPAGE"
                _log.warning(
                    "execution.HIGH_SLIPPAGE avg_total_slip=%.4f%% threshold=%.1f%%",
                    overall_avg, _HIGH_SLIPPAGE_PCT,
                )

            return {
                "group_by":       group_by,
                "lookback_days":  lookback_days,
                "overall_avg_slippage_pct": overall_avg,
                "alert":          alert,
                "rows":           rows,
            }
        except Exception as exc:
            _log.warning("execution.slippage_report_error: %s", exc)
            return {"group_by": group_by, "error": str(exc), "rows": []}

    # ------------------------------------------------------------------
    # Section E — Fill Quality Report
    # ------------------------------------------------------------------

    async def get_fill_quality_report(self, lookback_days: int = 30) -> dict:
        """Fill rate, reject rate, avg fill delay, Execution Quality Score."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*)                                                     AS total,
                          SUM(CASE WHEN status='ORDER_FILLED'    THEN 1 ELSE 0 END)   AS filled,
                          SUM(CASE WHEN status='ORDER_REJECTED'  THEN 1 ELSE 0 END)   AS rejected,
                          SUM(CASE WHEN status='ORDER_CANCELLED' THEN 1 ELSE 0 END)   AS cancelled,
                          ROUND(AVG(signal_to_fill_ms),  2)                           AS avg_s2f_ms,
                          ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP
                            (ORDER BY signal_to_fill_ms), 2)                          AS median_s2f_ms,
                          ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP
                            (ORDER BY signal_to_fill_ms), 2)                          AS p95_s2f_ms,
                          ROUND(AVG(total_slippage_pct), 4)                           AS avg_slip_pct
                        FROM execution_lifecycle
                        WHERE created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()

            if not row or not row[0]:
                return {
                    "status":                 "NO_DATA",
                    "execution_quality_score": None,
                    "message":                "No execution lifecycle records yet. System is in shadow/manual mode.",
                }

            total     = int(row[0] or 0)
            filled    = int(row[1] or 0)
            rejected  = int(row[2] or 0)
            cancelled = int(row[3] or 0)
            avg_s2f   = float(row[4] or 0)
            med_s2f   = float(row[5] or 0)
            p95_s2f   = float(row[6] or 0)
            avg_slip  = float(row[7] or 0)

            fill_rate   = filled / total if total > 0 else 0.0
            reject_rate = rejected / total if total > 0 else 0.0

            # Execution Quality Score
            score = 100
            if fill_rate < 0.95:
                score -= _EQS_DEDUCTIONS["fill_rate_low"]
            if reject_rate > 0.05:
                score -= _EQS_DEDUCTIONS["reject_rate_high"]
            if avg_s2f > _LATENCY_DEGRADATION_MS:
                score -= _EQS_DEDUCTIONS["latency_high"]
                _log.warning(
                    "execution.LATENCY_DEGRADATION avg_s2f_ms=%.0f threshold=%.0f",
                    avg_s2f, _LATENCY_DEGRADATION_MS,
                )
            elif avg_s2f > 2000:
                score -= _EQS_DEDUCTIONS["latency_medium"]
            if avg_slip > _HIGH_SLIPPAGE_PCT:
                score -= _EQS_DEDUCTIONS["slippage_critical"]
            elif avg_slip > 0.3:
                score -= _EQS_DEDUCTIONS["slippage_high"]
            elif avg_slip > 0.2:
                score -= _EQS_DEDUCTIONS["slippage_medium"]
            score = max(0, score)

            return {
                "lookback_days":          lookback_days,
                "total_orders":           total,
                "filled":                 filled,
                "rejected":               rejected,
                "cancelled":              cancelled,
                "fill_rate_pct":          round(fill_rate * 100, 2),
                "reject_rate_pct":        round(reject_rate * 100, 2),
                "avg_signal_to_fill_ms":  round(avg_s2f, 2),
                "median_signal_to_fill_ms": round(med_s2f, 2),
                "p95_signal_to_fill_ms":  round(p95_s2f, 2),
                "avg_total_slippage_pct": round(avg_slip, 4),
                "execution_quality_score": score,
                "alerts": [
                    a for a in [
                        "HIGH_SLIPPAGE"       if avg_slip  > _HIGH_SLIPPAGE_PCT      else None,
                        "LATENCY_DEGRADATION" if avg_s2f   > _LATENCY_DEGRADATION_MS else None,
                        "LOW_FILL_RATE"       if fill_rate < 0.95                    else None,
                    ] if a
                ],
            }
        except Exception as exc:
            _log.warning("execution.fill_quality_error: %s", exc)
            return {"error": str(exc), "execution_quality_score": None}

    # ------------------------------------------------------------------
    # Section F — Broker Latency Report
    # ------------------------------------------------------------------

    async def get_latency_report(self, lookback_days: int = 30) -> dict:
        """Signal-to-order, order-to-fill, signal-to-fill latency percentiles."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          ROUND(AVG(signal_to_order_ms),  2)  AS avg_s2o_ms,
                          ROUND(AVG(order_to_fill_ms),    2)  AS avg_o2f_ms,
                          ROUND(AVG(signal_to_fill_ms),   2)  AS avg_s2f_ms,
                          ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY signal_to_fill_ms), 2) AS med_s2f_ms,
                          ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY signal_to_fill_ms), 2) AS p95_s2f_ms,
                          COUNT(*) AS records
                        FROM execution_lifecycle
                        WHERE signal_to_fill_ms IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()

            if not row or not row[5]:
                return {"status": "NO_DATA", "records": 0}

            avg_s2f = float(row[2] or 0)
            alert   = "LATENCY_DEGRADATION" if avg_s2f > _LATENCY_DEGRADATION_MS else None

            return {
                "lookback_days":         lookback_days,
                "records":               int(row[5] or 0),
                "avg_signal_to_order_ms": float(row[0] or 0),
                "avg_order_to_fill_ms":  float(row[1] or 0),
                "avg_signal_to_fill_ms": avg_s2f,
                "median_signal_to_fill_ms": float(row[3] or 0),
                "p95_signal_to_fill_ms": float(row[4] or 0),
                "latency_threshold_ms":  _LATENCY_DEGRADATION_MS,
                "alert":                 alert,
            }
        except Exception as exc:
            _log.warning("execution.latency_report_error: %s", exc)
            return {"error": str(exc)}
