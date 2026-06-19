"""ShadowTradingService — Phase 18G model drift detection.

Shadow trading = current mode: signals generated, no real capital deployed.
Runs for minimum 2–4 weeks before live capital deployment.

Drift Detection:
  Compares reference period (older signals) vs live period (recent signals).
  Alerts MODEL_DRIFT when any key metric diverges > 20%.

Metrics compared:
  - Win rate (absolute difference > 20 pp)
  - Profit factor (relative change > 20%)
  - Expectancy direction change (sign flip always flags MODEL_DRIFT)
  - Data quality score (>20 pp drop flags MODEL_DRIFT)

Purpose:
  Validate that the scoring engine observed in backtesting/initial deployment
  continues to perform in live market conditions before capital scaling.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_DRIFT_THRESHOLD_PCT  = 20.0   # > 20% relative divergence → MODEL_DRIFT
_DRIFT_WIN_RATE_PP    = 20.0   # > 20 percentage point absolute difference
_MIN_TRADES_PER_PERIOD = 30    # need at least this many trades per period for valid comparison


class ShadowTradingService:
    """Validates that live shadow performance matches reference period performance."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_drift_report(
        self,
        reference_days: int = 60,    # how many days back for reference period
        live_days: int = 14,          # how many recent days constitute the "live" period
    ) -> dict:
        """Compare reference vs live periods. Returns MODEL_DRIFT alert if divergence > 20%.

        reference period: signals from [now - reference_days, now - live_days]
        live period:      signals from [now - live_days, now]
        """
        now       = datetime.now(UTC)
        live_start = now - timedelta(days=live_days)
        ref_start  = now - timedelta(days=reference_days)
        ref_end    = live_start

        async def _fetch_metrics(since: datetime, until: datetime) -> dict:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*)                                                      AS trades,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,2) AS win_rate,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit  THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          , 3)                                                          AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)       AS expectancy,
                          ROUND(AVG(data_quality_score),1)                             AS avg_dq_score
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :since AND created_at < :until
                    """),
                    {"since": since, "until": until},
                )
                row = r.fetchone()
            if not row or not row[0]:
                return {"trades": 0}
            return {
                "trades":       int(row[0] or 0),
                "win_rate":     float(row[1] or 0),
                "profit_factor": float(row[2] or 0),
                "expectancy":   float(row[3] or 0),
                "avg_dq_score": float(row[4] or 0) if row[4] else None,
            }

        try:
            ref  = await _fetch_metrics(ref_start, ref_end)
            live = await _fetch_metrics(live_start, now)
        except Exception as exc:
            _log.warning("shadow_trading.drift_error: %s", exc)
            return {"error": str(exc), "alert": None}

        insufficient = (
            ref.get("trades", 0)  < _MIN_TRADES_PER_PERIOD or
            live.get("trades", 0) < _MIN_TRADES_PER_PERIOD
        )
        if insufficient:
            return {
                "status":       "INSUFFICIENT_DATA",
                "reference":    ref,
                "live":         live,
                "min_required": _MIN_TRADES_PER_PERIOD,
                "alert":        None,
                "message": (
                    f"Need {_MIN_TRADES_PER_PERIOD}+ trades per period. "
                    f"Reference: {ref.get('trades',0)}, Live: {live.get('trades',0)}."
                ),
            }

        drifts = []

        # Win rate absolute difference
        wr_delta = abs(live["win_rate"] - ref["win_rate"])
        if wr_delta > _DRIFT_WIN_RATE_PP:
            drifts.append({
                "metric":    "win_rate",
                "reference": ref["win_rate"],
                "live":      live["win_rate"],
                "delta":     wr_delta,
                "threshold": _DRIFT_WIN_RATE_PP,
            })

        # Profit factor relative change
        ref_pf  = ref.get("profit_factor") or 0
        live_pf = live.get("profit_factor") or 0
        if ref_pf > 0:
            pf_rel_change = abs(live_pf - ref_pf) / ref_pf * 100
            if pf_rel_change > _DRIFT_THRESHOLD_PCT:
                drifts.append({
                    "metric":     "profit_factor",
                    "reference":  ref_pf,
                    "live":       live_pf,
                    "rel_pct":    round(pf_rel_change, 2),
                    "threshold":  _DRIFT_THRESHOLD_PCT,
                })

        # Expectancy sign flip
        ref_ex  = ref.get("expectancy") or 0
        live_ex = live.get("expectancy") or 0
        if ref_ex > 0 and live_ex <= 0:
            drifts.append({
                "metric":    "expectancy_sign_flip",
                "reference": ref_ex,
                "live":      live_ex,
                "note":      "Expectancy turned negative — immediate review required",
            })
        elif ref_ex != 0:
            ex_rel = abs(live_ex - ref_ex) / abs(ref_ex) * 100
            if ex_rel > _DRIFT_THRESHOLD_PCT:
                drifts.append({
                    "metric":    "expectancy",
                    "reference": ref_ex,
                    "live":      live_ex,
                    "rel_pct":   round(ex_rel, 2),
                })

        # Data quality drop
        ref_dq  = ref.get("avg_dq_score")
        live_dq = live.get("avg_dq_score")
        if ref_dq and live_dq and ref_dq > 0:
            dq_delta = ref_dq - live_dq
            if dq_delta > _DRIFT_WIN_RATE_PP:  # > 20 pt drop in DQ
                drifts.append({
                    "metric":    "data_quality_score",
                    "reference": ref_dq,
                    "live":      live_dq,
                    "delta":     dq_delta,
                })

        alert = "MODEL_DRIFT" if drifts else None
        if alert:
            _log.warning("shadow_trading.MODEL_DRIFT drifts=%s", drifts)

        return {
            "status":           "DRIFT_DETECTED" if alert else "STABLE",
            "reference_period": f"{reference_days - live_days} days (days {live_days}–{reference_days} ago)",
            "live_period":      f"Last {live_days} days",
            "reference":        ref,
            "live":             live,
            "drifts":           drifts,
            "alert":            alert,
            "deployment_gate":  "BLOCKED" if alert else "CLEAR",
            "recommendation": (
                "MODEL_DRIFT detected. Do NOT deploy capital until drift is investigated. "
                "Review: market regime shift, data quality degradation, scoring component change."
                if alert else
                "No significant drift detected. Shadow trading consistent with reference period. "
                f"Proceed to small capital deployment (Section H) when {_MIN_TRADES_PER_PERIOD}+ live trades validated."
            ),
        }

    async def get_shadow_summary(self, days: int = 30) -> dict:
        """Current shadow trading performance summary for dashboard."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*)                                                      AS total_signals,
                          SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END)               AS accepted,
                          SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END)         AS completed,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,2) AS win_rate,
                          ROUND(AVG(adjusted_score),2)                                AS avg_score,
                          ROUND(AVG(confidence),2)                                    AS avg_confidence,
                          ROUND(AVG(data_quality_score),1)                            AS avg_dq
                        FROM signal_analytics
                        WHERE created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
            return {
                "period_days":    days,
                "total_signals":  int(row[0] or 0),
                "accepted":       int(row[1] or 0),
                "completed":      int(row[2] or 0),
                "win_rate_pct":   float(row[3] or 0),
                "avg_score":      float(row[4] or 0),
                "avg_confidence": float(row[5] or 0),
                "avg_dq_score":   float(row[6] or 0) if row[6] else None,
                "deployment_ready": (
                    int(row[2] or 0) >= 30 and
                    float(row[3] or 0) > 45.0 and
                    float(row[5] or 0) >= 65.0
                ),
            }
        except Exception as exc:
            _log.warning("shadow_trading.summary_error: %s", exc)
            return {"error": str(exc)}
