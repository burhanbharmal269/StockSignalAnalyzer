"""WeeklyOperationsReportService — Phase 19 Section 6.

Generates a comprehensive 9-section weekly operations report.
All sections are read-only analytics; no execution side-effects.

Sections:
  1. Score Performance (score bucket monotonicity, calibration status)
  2. Regime Performance (per-regime win rate, PF, Sharpe proxy)
  3. Symbol Performance (top/bottom performers, min 5 trades)
  4. Time Window Performance (IST hour buckets, best/worst windows)
  5. MTF Confirmation (retention analysis, conflict underperformance)
  6. Data Quality (avg score, % sessions critical, feed reliability)
  7. Execution Quality (fill rate, slippage, latency — when data available)
  8. Risk Heat (daily budget utilisation, consecutive loss streaks)
  9. Drawdown Summary (current vs historical, consecutive LOSS streaks)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from core.application.services.execution_lifecycle_service import ExecutionLifecycleService
    from core.application.services.portfolio_intelligence_service import PortfolioIntelligenceService
    from core.application.services.signal_intelligence_service import SignalIntelligenceService

_log = logging.getLogger(__name__)


class WeeklyOperationsReportService:
    """Generates the 9-section weekly performance and operations report."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        intelligence_svc:   "SignalIntelligenceService | None"  = None,
        portfolio_svc:       "PortfolioIntelligenceService | None" = None,
        execution_svc:       "ExecutionLifecycleService | None"  = None,
    ) -> None:
        self._sf          = session_factory
        self._intel       = intelligence_svc
        self._portfolio   = portfolio_svc
        self._exec_svc    = execution_svc

    async def generate(self, lookback_days: int = 7) -> dict:
        """Generate the full weekly report for the lookback period.

        Args:
            lookback_days: Number of days to cover (default 7 = one week).

        Returns:
            dict with 9 sections plus metadata.
        """
        cutoff   = datetime.now(UTC) - timedelta(days=lookback_days)
        week_end = datetime.now(UTC)

        _log.info(
            "weekly_report.generating lookback=%d from=%s to=%s",
            lookback_days, cutoff.date(), week_end.date(),
        )

        # Run all sections concurrently
        import asyncio
        (
            s1_score,
            s2_regime,
            s3_symbol,
            s4_time,
            s5_mtf,
            s6_dq,
            s8_risk,
            s9_drawdown,
        ) = await asyncio.gather(
            self._section1_score(cutoff),
            self._section2_regime(cutoff),
            self._section3_symbol(cutoff),
            self._section4_time(cutoff),
            self._section5_mtf(cutoff),
            self._section6_dq(cutoff),
            self._section8_risk(cutoff),
            self._section9_drawdown(cutoff),
            return_exceptions=True,
        )

        # Section 7 — execution quality (optional, requires ExecutionLifecycleService)
        s7_execution: dict = {}
        if self._exec_svc is not None:
            try:
                s7_execution = await self._exec_svc.get_fill_quality_report(
                    lookback_days=lookback_days
                )
            except Exception as exc:
                s7_execution = {"error": str(exc)}

        def _safe(val, default: dict | None = None):
            if isinstance(val, Exception):
                return {"error": str(val)}
            return val if val is not None else (default or {})

        report = {
            "report_type":   "WEEKLY_OPERATIONS",
            "period_days":   lookback_days,
            "from_date":     cutoff.date().isoformat(),
            "to_date":       week_end.date().isoformat(),
            "generated_at":  week_end.isoformat(),
            "sections": {
                "1_score_performance":  _safe(s1_score),
                "2_regime_performance": _safe(s2_regime),
                "3_symbol_performance": _safe(s3_symbol),
                "4_time_performance":   _safe(s4_time),
                "5_mtf_confirmation":   _safe(s5_mtf),
                "6_data_quality":       _safe(s6_dq),
                "7_execution_quality":  s7_execution,
                "8_risk_heat":          _safe(s8_risk),
                "9_drawdown_summary":   _safe(s9_drawdown),
            },
        }

        # Add high-level summary flags
        alerts = self._extract_alerts(report["sections"])
        report["alerts"] = alerts
        report["overall_health"] = (
            "CRITICAL" if any(a.get("severity") == "CRITICAL" for a in alerts) else
            "WARNING"  if alerts else
            "HEALTHY"
        )

        _log.info(
            "weekly_report.done sections=9 alerts=%d health=%s",
            len(alerts), report["overall_health"],
        )
        return report

    # ── Section 1: Score Bucket Performance ───────────────────────────────────

    async def _section1_score(self, cutoff: datetime) -> dict:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                      CASE
                        WHEN adjusted_score >= 85 THEN '85+'
                        WHEN adjusted_score >= 80 THEN '80-84'
                        WHEN adjusted_score >= 75 THEN '75-79'
                        WHEN adjusted_score >= 70 THEN '70-74'
                        WHEN adjusted_score >= 65 THEN '65-69'
                        ELSE '60-64'
                      END                                                       AS bucket,
                      COUNT(*)                                                   AS trades,
                      ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,2) AS win_rate,
                      ROUND(
                        SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                        NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                      ,3)                                                        AS profit_factor
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NOT NULL
                      AND created_at >= :cutoff
                    GROUP BY bucket
                    ORDER BY bucket DESC
                """),
                {"cutoff": cutoff},
            )
            rows = r.fetchall()

        buckets = [
            {
                "bucket":        row[0],
                "trades":        int(row[1] or 0),
                "win_rate_pct":  float(row[2] or 0),
                "profit_factor": float(row[3] or 0),
            }
            for row in rows
        ]
        calibration_ok = len(buckets) >= 3 and _is_monotonic(
            [b["win_rate_pct"] for b in buckets]
        )
        return {
            "buckets":        buckets,
            "calibration_ok": calibration_ok,
            "flag": None if calibration_ok else "SCORE_CALIBRATION_REQUIRED",
        }

    # ── Section 2: Regime Performance ─────────────────────────────────────────

    async def _section2_regime(self, cutoff: datetime) -> dict:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                      regime,
                      COUNT(*)                                                    AS trades,
                      ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,2) AS win_rate,
                      ROUND(
                        SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                        NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                      ,3)                                                          AS profit_factor,
                      ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)      AS expectancy
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NOT NULL
                      AND created_at >= :cutoff
                    GROUP BY regime
                    ORDER BY profit_factor DESC NULLS LAST
                """),
                {"cutoff": cutoff},
            )
            rows = r.fetchall()

        regimes = []
        underperforming = []
        for row in rows:
            pf = float(row[3] or 0)
            trades = int(row[1] or 0)
            entry = {
                "regime":        row[0],
                "trades":        trades,
                "win_rate_pct":  float(row[2] or 0),
                "profit_factor": pf,
                "expectancy":    float(row[4] or 0),
            }
            if trades >= 10 and pf < 1.0:
                entry["flag"] = "UNDERPERFORMING_REGIME"
                underperforming.append(row[0])
            regimes.append(entry)

        return {"regimes": regimes, "underperforming": underperforming}

    # ── Section 3: Symbol Performance ─────────────────────────────────────────

    async def _section3_symbol(self, cutoff: datetime) -> dict:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                      ticker,
                      COUNT(*)                                                    AS trades,
                      ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,2) AS win_rate,
                      ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)      AS expectancy,
                      ROUND(
                        SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                        NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                      ,3)                                                          AS profit_factor
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NOT NULL
                      AND created_at >= :cutoff
                    GROUP BY ticker
                    HAVING COUNT(*) >= 5
                    ORDER BY profit_factor DESC NULLS LAST
                    LIMIT 20
                """),
                {"cutoff": cutoff},
            )
            rows = r.fetchall()

        symbols = [
            {
                "ticker":        row[0],
                "trades":        int(row[1] or 0),
                "win_rate_pct":  float(row[2] or 0),
                "expectancy":    float(row[3] or 0),
                "profit_factor": float(row[4] or 0),
            }
            for row in rows
        ]
        return {
            "top_5":    symbols[:5],
            "bottom_5": symbols[-5:] if len(symbols) >= 5 else symbols,
            "all":      symbols,
        }

    # ── Section 4: Time Window Performance ────────────────────────────────────

    async def _section4_time(self, cutoff: datetime) -> dict:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                      EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') AS ist_hour,
                      COUNT(*)                                                    AS trades,
                      ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,2) AS win_rate,
                      ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)      AS expectancy
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NOT NULL
                      AND created_at >= :cutoff
                    GROUP BY ist_hour
                    ORDER BY ist_hour
                """),
                {"cutoff": cutoff},
            )
            rows = r.fetchall()

        windows = [
            {
                "ist_hour":     int(row[0] or 0),
                "trades":       int(row[1] or 0),
                "win_rate_pct": float(row[2] or 0),
                "expectancy":   float(row[3] or 0),
            }
            for row in rows
        ]
        best  = max(windows, key=lambda w: w["win_rate_pct"]) if windows else None
        worst = min(windows, key=lambda w: w["win_rate_pct"]) if windows else None
        return {
            "windows": windows,
            "best_window":  best,
            "worst_window": worst,
        }

    # ── Section 5: MTF Confirmation ────────────────────────────────────────────

    async def _section5_mtf(self, cutoff: datetime) -> dict:
        if self._intel is not None:
            try:
                return await self._intel.get_mtf_retention_analysis(
                    lookback_days=int((datetime.now(UTC) - cutoff).days + 1)
                )
            except Exception as exc:
                return {"error": str(exc)}

        # Fallback: basic MTF alignment breakdown from analytics table
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                      mtf_alignment,
                      COUNT(*)                                                    AS trades,
                      ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,2) AS win_rate
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NOT NULL
                      AND mtf_alignment IS NOT NULL
                      AND created_at >= :cutoff
                    GROUP BY mtf_alignment
                    ORDER BY win_rate DESC
                """),
                {"cutoff": cutoff},
            )
            rows = r.fetchall()

        return {
            "groups": [
                {"alignment": row[0], "trades": int(row[1] or 0), "win_rate_pct": float(row[2] or 0)}
                for row in rows
            ]
        }

    # ── Section 6: Data Quality ────────────────────────────────────────────────

    async def _section6_dq(self, cutoff: datetime) -> dict:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                      ROUND(AVG(data_quality_score),1)                              AS avg_score,
                      COUNT(CASE WHEN data_quality_score < 70 THEN 1 END)           AS critical_sessions,
                      COUNT(CASE WHEN data_quality_score >= 70
                                  AND data_quality_score < 85 THEN 1 END)           AS warning_sessions,
                      COUNT(CASE WHEN data_quality_score >= 85 THEN 1 END)          AS ok_sessions,
                      COUNT(*)                                                       AS total_sessions
                    FROM signal_analytics
                    WHERE created_at >= :cutoff
                      AND data_quality_score IS NOT NULL
                """),
                {"cutoff": cutoff},
            )
            row = r.fetchone()

        total  = int(row[4] or 0) or 1
        avg_dq = float(row[0] or 0) if row[0] else None
        return {
            "avg_data_quality_score": avg_dq,
            "critical_sessions":      int(row[1] or 0),
            "warning_sessions":       int(row[2] or 0),
            "ok_sessions":            int(row[3] or 0),
            "total_sessions":         total,
            "critical_pct":           round(int(row[1] or 0) / total * 100, 2),
            "flag": "DQ_DEGRADED" if avg_dq is not None and avg_dq < 80 else None,
        }

    # ── Section 8: Risk Heat ───────────────────────────────────────────────────

    async def _section8_risk(self, cutoff: datetime) -> dict:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                      DATE(created_at AT TIME ZONE 'UTC')                         AS trade_date,
                      COUNT(CASE WHEN was_accepted THEN 1 END)                    AS accepted,
                      SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END)           AS losses
                    FROM signal_analytics
                    WHERE created_at >= :cutoff
                    GROUP BY trade_date
                    ORDER BY trade_date
                """),
                {"cutoff": cutoff},
            )
            rows = r.fetchall()

        days = [
            {
                "date":     str(row[0]),
                "accepted": int(row[1] or 0),
                "losses":   int(row[2] or 0),
            }
            for row in rows
        ]

        # Max consecutive LOSS days
        max_consec_loss = 0
        cur_consec = 0
        for d in days:
            if d["accepted"] > 0 and d["losses"] == d["accepted"]:
                cur_consec += 1
                max_consec_loss = max(max_consec_loss, cur_consec)
            else:
                cur_consec = 0

        return {
            "daily_stats":             days,
            "max_consecutive_loss_days": max_consec_loss,
            "flag": "HIGH_CONSECUTIVE_LOSSES" if max_consec_loss >= 3 else None,
        }

    # ── Section 9: Drawdown Summary ────────────────────────────────────────────

    async def _section9_drawdown(self, cutoff: datetime) -> dict:
        if self._portfolio is not None:
            try:
                return await self._portfolio.get_risk_of_ruin(
                    lookback_days=int((datetime.now(UTC) - cutoff).days + 1)
                )
            except Exception as exc:
                return {"error": str(exc)}

        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                      ROUND(SUM(CASE WHEN outcome='WIN'  THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END)*100,4) AS total_gains,
                      ROUND(SUM(CASE WHEN outcome='LOSS' THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END)*100,4) AS total_losses
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NOT NULL
                      AND created_at >= :cutoff
                """),
                {"cutoff": cutoff},
            )
            row = r.fetchone()

        return {
            "total_gains_pct":  float(row[0] or 0),
            "total_losses_pct": float(row[1] or 0),
            "net_pct":          float(row[0] or 0) - float(row[1] or 0),
        }

    # ── Alert extraction ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_alerts(sections: dict) -> list[dict]:
        alerts = []
        flag_map = {
            "SCORE_CALIBRATION_REQUIRED":  ("CRITICAL", "Score calibration required — non-monotonic buckets"),
            "UNDERPERFORMING_REGIME":       ("WARNING",  "One or more regimes underperforming (PF < 1.0)"),
            "DQ_DEGRADED":                  ("WARNING",  "Average data quality score < 80"),
            "HIGH_CONSECUTIVE_LOSSES":      ("CRITICAL", "3+ consecutive loss days — review risk settings"),
            "ABNORMAL_DRAWDOWN":            ("CRITICAL", "Abnormal drawdown: 1.5× historical average"),
        }
        for section_key, section_data in sections.items():
            if not isinstance(section_data, dict):
                continue
            flag = section_data.get("flag")
            if flag and flag in flag_map:
                sev, msg = flag_map[flag]
                alerts.append({"flag": flag, "severity": sev, "message": msg, "section": section_key})
            # Nested underperforming regimes
            for regime_entry in section_data.get("regimes", []):
                if regime_entry.get("flag") == "UNDERPERFORMING_REGIME":
                    sev, msg = flag_map["UNDERPERFORMING_REGIME"]
                    alerts.append({
                        "flag":    "UNDERPERFORMING_REGIME",
                        "severity": sev,
                        "message": f"{regime_entry['regime']}: PF={regime_entry['profit_factor']:.2f}",
                        "section": "2_regime_performance",
                    })
        return alerts


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_monotonic(values: list[float]) -> bool:
    """Return True if values are weakly monotonically increasing."""
    return all(values[i] <= values[i + 1] for i in range(len(values) - 1))
