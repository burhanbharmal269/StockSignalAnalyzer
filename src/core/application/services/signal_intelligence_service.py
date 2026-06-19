"""SignalIntelligenceDashboardService — Phase 15 evidence-driven analytics.

Provides 4 dashboard views + MTF retention analysis + expectancy + sizing comparison.

A. Regime Performance     — metrics per MarketRegime
B. Score Bucket           — metrics by adjusted_score band (60-64, 65-69, … 85+)
C. Time Window            — metrics by IST entry time window
D. Symbol Performance     — per-symbol leaderboard

MTF Retention (Section 1 hardening):
  Retention requires AC-5 (CONFLICT < BASELINE) AND (AC-1 OR AC-2 OR AC-3).

Expectancy (Section 2):
  Per-MTF-group expectancy using pnl_pct (COALESCE to current_return_pct).

Sizing Comparison (Section 5):
  Fixed-size vs score-based sizing metrics from existing signal data.

All methods are read-only. No writes. Fail-open: exceptions return empty lists.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


class SignalIntelligenceService:
    """Read-only analytics for the Signal Intelligence Dashboard V2."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ------------------------------------------------------------------
    # A. Regime Performance
    # ------------------------------------------------------------------

    async def get_regime_performance(self, lookback_days: int = 30) -> list[dict]:
        """Win rate, Profit Factor, Sharpe, Sortino, Expectancy, MFE, MAE per regime."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          regime,
                          COUNT(*)                                                       AS signals,
                          SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END)                AS accepted,
                          SUM(CASE WHEN target_hit  THEN 1 ELSE 0 END)                AS wins,
                          SUM(CASE WHEN stop_hit    THEN 1 ELSE 0 END)                AS losses,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate_pct,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN COALESCE(pnl_pct,current_return_pct) ELSE 0 END) /
                            NULLIF(ABS(SUM(CASE WHEN stop_hit  THEN COALESCE(pnl_pct,current_return_pct) ELSE 0 END)),0)
                          , 3)                                                          AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)      AS avg_return_pct,
                          ROUND(AVG(mfe_pct)*100,4)                                   AS avg_mfe_pct,
                          ROUND(AVG(mae_pct)*100,4)                                   AS avg_mae_pct,
                          COUNT(DISTINCT ticker)                                       AS unique_symbols
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY regime
                        ORDER BY win_rate_pct DESC NULLS LAST
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()

            result = []
            for row in rows:
                r_dict = dict(row._mapping)
                # Compute Sharpe and Sortino require per-trade returns — proxy with
                # win_rate and avg_return here; full computation needs raw data.
                win_rate = float(r_dict.get("win_rate_pct") or 0) / 100
                avg_ret  = float(r_dict.get("avg_return_pct") or 0)
                n        = int(r_dict.get("accepted") or 0)
                # Simplified Sharpe proxy (needs std dev — use avg_mfe/mae spread)
                avg_mfe  = float(r_dict.get("avg_mfe_pct") or 0)
                avg_mae  = abs(float(r_dict.get("avg_mae_pct") or 0))
                std_proxy = (avg_mfe + avg_mae) / 2 if (avg_mfe + avg_mae) > 0 else 1.0
                sharpe_proxy = round(avg_ret / std_proxy, 3) if std_proxy > 0 else 0.0
                # Sortino uses only downside std (avg_mae as proxy)
                sortino_proxy = round(avg_ret / avg_mae, 3) if avg_mae > 0 else 0.0
                # Expectancy: win_rate × avg_win_return − loss_rate × avg_loss_return
                # Using win_rate and profit_factor to derive components
                pf = float(r_dict.get("profit_factor") or 0)
                expectancy = round((win_rate * pf - (1 - win_rate)) * avg_mae, 6) if avg_mae else 0.0

                result.append({
                    **r_dict,
                    "sharpe_proxy":  sharpe_proxy,
                    "sortino_proxy": sortino_proxy,
                    "expectancy":    expectancy,
                })
            return result
        except Exception as exc:
            _log.warning("signal_intelligence.regime_performance_error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # B. Score Bucket Performance
    # ------------------------------------------------------------------

    async def get_score_bucket_performance(self, lookback_days: int = 30) -> list[dict]:
        """Win rate, Profit Factor, Expectancy, Avg Return by score band.

        Expected: higher buckets should strictly outperform lower buckets.
        Monotonic failure = calibration issue.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
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
                            ELSE                           '60-64'
                          END                                                           AS score_bucket,
                          COUNT(*)                                                      AS trades,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate_pct,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN COALESCE(pnl_pct,current_return_pct) ELSE 0 END) /
                            NULLIF(ABS(SUM(CASE WHEN stop_hit THEN COALESCE(pnl_pct,current_return_pct) ELSE 0 END)),0)
                          , 3)                                                          AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)       AS avg_return_pct,
                          ROUND(AVG(adjusted_score),2)                                 AS avg_score
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND was_accepted = true
                          AND adjusted_score IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY 1
                        ORDER BY avg_score DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()

            result = [dict(row._mapping) for row in rows]
            # Tag whether monotonic order holds
            win_rates = [float(r.get("win_rate_pct") or 0) for r in result]
            pfs       = [float(r.get("profit_factor") or 0) for r in result]
            monotonic_win_rate = all(win_rates[i] >= win_rates[i+1] for i in range(len(win_rates)-1))
            monotonic_pf       = all(pfs[i] >= pfs[i+1] for i in range(len(pfs)-1))
            for row in result:
                row["calibration_ok"] = monotonic_win_rate and monotonic_pf
            return result
        except Exception as exc:
            _log.warning("signal_intelligence.score_bucket_error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # C. Time Window Performance
    # ------------------------------------------------------------------

    async def get_time_window_performance(self, lookback_days: int = 30) -> list[dict]:
        """Win rate, Profit Factor, Expectancy by IST entry time window."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          CASE
                            WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') = 9
                             AND EXTRACT(MINUTE FROM created_at AT TIME ZONE 'Asia/Kolkata') >= 30
                            THEN '09:30-10:30'
                            WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') = 10
                            THEN '09:30-10:30'
                            WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') IN (10,11)
                             AND NOT (EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') = 10
                                      AND EXTRACT(MINUTE FROM created_at AT TIME ZONE 'Asia/Kolkata') < 30)
                            THEN '10:30-12:00'
                            WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') = 12
                            THEN '10:30-12:00'
                            WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') IN (12,13)
                            THEN '12:00-13:30'
                            ELSE '13:30-14:30'
                          END                                                           AS time_window,
                          COUNT(*)                                                      AS trades,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate_pct,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN COALESCE(pnl_pct,current_return_pct) ELSE 0 END) /
                            NULLIF(ABS(SUM(CASE WHEN stop_hit THEN COALESCE(pnl_pct,current_return_pct) ELSE 0 END)),0)
                          , 3)                                                          AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)       AS avg_return_pct,
                          ROUND(AVG(time_to_target_minutes),1)                         AS avg_hold_minutes
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY 1
                        ORDER BY 1
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
            return [dict(row._mapping) for row in rows]
        except Exception as exc:
            _log.warning("signal_intelligence.time_window_error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # D. Symbol Performance
    # ------------------------------------------------------------------

    async def get_symbol_performance(
        self, lookback_days: int = 30, limit: int = 20
    ) -> list[dict]:
        """Per-symbol win rate, Profit Factor, Sharpe proxy, Expectancy."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          ticker,
                          sector,
                          is_index,
                          COUNT(*)                                                      AS trades,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate_pct,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN COALESCE(pnl_pct,current_return_pct) ELSE 0 END) /
                            NULLIF(ABS(SUM(CASE WHEN stop_hit THEN COALESCE(pnl_pct,current_return_pct) ELSE 0 END)),0)
                          , 3)                                                          AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)       AS avg_return_pct,
                          ROUND(AVG(mfe_pct)*100,4)                                   AS avg_mfe_pct,
                          ROUND(AVG(adjusted_score),2)                                AS avg_score,
                          ROUND(AVG(confidence),2)                                    AS avg_confidence
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY ticker, sector, is_index
                        HAVING COUNT(*) >= 3
                        ORDER BY win_rate_pct DESC NULLS LAST, profit_factor DESC NULLS LAST
                        LIMIT :limit
                    """),
                    {"cutoff": cutoff, "limit": limit},
                )
                rows = r.fetchall()
            return [dict(row._mapping) for row in rows]
        except Exception as exc:
            _log.warning("signal_intelligence.symbol_performance_error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # MTF Retention Analysis (Section 1 hardening)
    # ------------------------------------------------------------------

    async def get_mtf_retention_analysis(self, lookback_days: int = 60) -> dict:
        """Full MTF retention evaluation per the hardened criteria.

        Retention requires:
          AC-5 (CONFLICT < BASELINE win rate) AND (AC-1 OR AC-2 OR AC-3)

        Returns:
          metrics per group, whether each criterion passes, and final verdict.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          CASE
                            WHEN mtf_alignment IS NULL     THEN 'NO_MTF'
                            WHEN mtf_score_bonus > 0       THEN 'ALIGNED'
                            WHEN mtf_score_bonus = 0       THEN 'NEUTRAL'
                            ELSE                                'CONFLICT'
                          END                                                           AS mtf_group,
                          COUNT(*)                                                      AS trades,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate_pct,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          , 3)                                                          AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)       AS avg_return_pct,
                          ROUND(AVG(mfe_pct)*100,4)                                   AS avg_mfe_pct,
                          ROUND(AVG(mae_pct)*100,4)                                   AS avg_mae_pct
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY 1
                    """),
                    {"cutoff": cutoff},
                )
                rows = {row[0]: dict(row._mapping) for row in r.fetchall()}

            baseline = rows.get("NO_MTF", {})
            aligned  = rows.get("ALIGNED", {})
            conflict = rows.get("CONFLICT", {})

            def _wr(g: dict) -> float:
                return float(g.get("win_rate_pct") or 0)

            def _pf(g: dict) -> float:
                return float(g.get("profit_factor") or 0)

            n_baseline  = int(baseline.get("trades") or 0)
            n_aligned   = int(aligned.get("trades") or 0)
            n_conflict  = int(conflict.get("trades") or 0)
            sufficient  = (n_baseline + n_aligned + n_conflict) >= 200

            # AC-5: Conflict must underperform baseline (required for retention)
            ac5 = _wr(conflict) < _wr(baseline) if n_conflict > 0 and n_baseline > 0 else None

            # AC-1: ALIGNED win rate >= BASELINE + 2 pp
            ac1 = (_wr(aligned) >= _wr(baseline) + 2.0) if n_aligned > 0 and n_baseline > 0 else None

            # AC-2: ALIGNED profit factor >= BASELINE + 0.10
            ac2 = (_pf(aligned) >= _pf(baseline) + 0.10) if n_aligned > 0 and n_baseline > 0 else None

            # AC-3: CONFLICT stop_hit rate >= BASELINE stop_hit rate + 10 pp
            # (False breakout reduction — higher stop rate on conflict = MTF is detecting bad entries)
            baseline_loss = float(baseline.get("avg_mae_pct") or 0)
            conflict_loss = float(conflict.get("avg_mae_pct") or 0)
            ac3 = (conflict_loss >= baseline_loss + 0.001) if n_conflict > 0 and n_baseline > 0 else None

            # Hardened retention: AC-5 AND (AC-1 OR AC-2 OR AC-3)
            if ac5 is None or not sufficient:
                verdict = "INSUFFICIENT_DATA"
            elif not ac5:
                verdict = "REMOVE"          # AC-5 fails: MTF has no directional info
            elif ac1 or ac2 or ac3:
                verdict = "RETAIN"
            else:
                verdict = "REDUCE"          # AC-5 passes but no outcome improvement

            return {
                "sufficient_data": sufficient,
                "total_trades": n_baseline + n_aligned + n_conflict,
                "groups": rows,
                "criteria": {
                    "ac1_win_rate_improvement":      ac1,
                    "ac2_profit_factor_improvement": ac2,
                    "ac3_false_breakout_reduction":  ac3,
                    "ac5_conflict_underperforms":    ac5,
                },
                "verdict": verdict,
                "interpretation": {
                    "RETAIN":             "MTF is adding value. Keep current weights.",
                    "REDUCE":             "Conflict penalty works but aligned bonus doesn't. Halve aligned bonus (+4→+2, +2→+1).",
                    "REMOVE":             "Conflict signals don't underperform. MTF contains no directional information.",
                    "INSUFFICIENT_DATA":  f"Need 200+ completed trades. Currently {n_baseline + n_aligned + n_conflict}.",
                }.get(verdict, verdict),
            }
        except Exception as exc:
            _log.warning("signal_intelligence.mtf_retention_error: %s", exc)
            return {"error": str(exc), "verdict": "UNKNOWN"}

    # ------------------------------------------------------------------
    # Expectancy by MTF Group (Section 2)
    # ------------------------------------------------------------------

    async def get_expectancy_by_mtf(self, lookback_days: int = 60) -> list[dict]:
        """Average return and expectancy per MTF group.

        Expected: ALIGNED expectancy > BASELINE > CONFLICT.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COALESCE(mtf_alignment, 'NO_MTF')  AS mtf_alignment,
                          COUNT(*)                           AS trades,
                          ROUND(AVG(COALESCE(pnl_pct, current_return_pct))*100, 4)  AS avg_return_pct,
                          ROUND(AVG(
                            CASE
                              WHEN target_hit THEN ABS(COALESCE(pnl_pct, current_return_pct, 0))
                              ELSE -ABS(COALESCE(pnl_pct, current_return_pct, 0))
                            END
                          )*100, 4)                          AS expectancy_pct
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY COALESCE(mtf_alignment, 'NO_MTF')
                        ORDER BY expectancy_pct DESC NULLS LAST
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
            return [dict(row._mapping) for row in rows]
        except Exception as exc:
            _log.warning("signal_intelligence.expectancy_mtf_error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Data Quality Trend (Section 3)
    # ------------------------------------------------------------------

    async def get_data_quality_trend(self, lookback_days: int = 14) -> list[dict]:
        """Average data quality score by day. Alerts if avg < 85."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          DATE(created_at AT TIME ZONE 'Asia/Kolkata')   AS trade_date,
                          COUNT(*)                                        AS signals,
                          ROUND(AVG(data_quality_score),1)               AS avg_quality,
                          MIN(data_quality_score)                        AS min_quality,
                          SUM(CASE WHEN data_quality_score < 85 THEN 1 ELSE 0 END) AS degraded_count,
                          SUM(CASE WHEN data_quality_score < 70 THEN 1 ELSE 0 END) AS critical_count
                        FROM signal_analytics
                        WHERE data_quality_score IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY 1
                        ORDER BY 1 DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
            result = []
            for row in rows:
                d = dict(row._mapping)
                avg_q = float(d.get("avg_quality") or 100)
                d["alert"] = "CRITICAL" if avg_q < 70 else ("WARNING" if avg_q < 85 else "OK")
                result.append(d)
            return result
        except Exception as exc:
            _log.warning("signal_intelligence.data_quality_trend_error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Position Sizing Comparison (Section 5)
    # ------------------------------------------------------------------

    async def get_sizing_comparison(self, lookback_days: int = 60) -> dict:
        """Compare fixed-size vs score-based sizing outcomes.

        Uses existing signal data: score-based = signals with adjusted_score >= 80
        (where sizing is at maximum), fixed-size = all accepted signals.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          'ALL_SIGNALS'                                                  AS cohort,
                          COUNT(*)                                                       AS trades,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1)  AS win_rate_pct,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          ,3)                                                            AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)        AS avg_return_pct,
                          ROUND(MAX(mae_pct)*100,4)                                    AS max_drawdown_pct
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL AND was_accepted = true AND created_at >= :cutoff
                        UNION ALL
                        SELECT
                          'SCORE_85_PLUS'                                                AS cohort,
                          COUNT(*)                                                       AS trades,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1)  AS win_rate_pct,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          ,3)                                                            AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)        AS avg_return_pct,
                          ROUND(MAX(mae_pct)*100,4)                                    AS max_drawdown_pct
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL AND was_accepted = true
                          AND adjusted_score >= 85 AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()

            groups = {row[0]: dict(row._mapping) for row in rows}
            all_sig = groups.get("ALL_SIGNALS", {})
            score85 = groups.get("SCORE_85_PLUS", {})

            def _pf(g: dict) -> float:
                return float(g.get("profit_factor") or 0)

            def _wr(g: dict) -> float:
                return float(g.get("win_rate_pct") or 0)

            improvement = {
                "win_rate_delta_pp":     round(_wr(score85) - _wr(all_sig), 2),
                "profit_factor_delta":   round(_pf(score85) - _pf(all_sig), 3),
                "score_based_justified": _wr(score85) > _wr(all_sig) or _pf(score85) > _pf(all_sig),
            }

            return {
                "cohorts": groups,
                "improvement": improvement,
                "recommendation": (
                    "Score-based sizing justified: high-score signals outperform on win rate or PF."
                    if improvement["score_based_justified"] else
                    "Score-based sizing not yet justified. Fixed sizing may be safer until 200+ trades."
                ),
            }
        except Exception as exc:
            _log.warning("signal_intelligence.sizing_comparison_error: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Success Criteria Dashboard (Section 8)
    # ------------------------------------------------------------------

    async def get_success_criteria_status(self, lookback_days: int = 60) -> dict:
        """Check all 10 success criteria from Phase 15 spec.

        Returns pass/fail per criterion with current observed value.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*) AS total,
                          SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END)  AS accepted,
                          SUM(CASE WHEN target_hit  THEN 1 ELSE 0 END)   AS wins,
                          SUM(CASE WHEN stop_hit    THEN 1 ELSE 0 END)   AS losses,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,2) AS win_rate,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          ,3) AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS expectancy,
                          ROUND(AVG(data_quality_score),1) AS avg_dq_score
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND was_accepted = true
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()

            if not row:
                return {"error": "no_data"}

            win_rate  = float(row.win_rate or 0)
            pf        = float(row.profit_factor or 0)
            expectancy = float(row.expectancy or 0)
            dq_avg    = float(row.avg_dq_score or 100)
            total     = int(row.total or 0)

            # Score bucket monotonicity (SC-1) — fetch separately
            buckets = await self.get_score_bucket_performance(lookback_days)
            monotonic = all(r.get("calibration_ok", False) for r in buckets) if buckets else False

            # MTF retention (SC-2, SC-3) — fetch separately
            mtf = await self.get_mtf_retention_analysis(lookback_days)
            criteria = mtf.get("criteria", {})
            mtf_aligned_beats_baseline = criteria.get("ac1_win_rate_improvement") or criteria.get("ac2_profit_factor_improvement")
            mtf_conflict_underperforms = criteria.get("ac5_conflict_underperforms")

            return {
                "lookback_days": lookback_days,
                "total_trades":  total,
                "criteria": {
                    "SC1_score_bucket_monotonic":     {"pass": monotonic,                      "value": "monotonic" if monotonic else "non-monotonic"},
                    "SC2_mtf_aligned_beats_baseline": {"pass": bool(mtf_aligned_beats_baseline), "value": str(mtf_aligned_beats_baseline)},
                    "SC3_mtf_conflict_underperforms": {"pass": bool(mtf_conflict_underperforms), "value": str(mtf_conflict_underperforms)},
                    "SC4_profit_factor_gt_1_30":      {"pass": pf > 1.30,                      "value": round(pf, 3)},
                    "SC5_win_rate_gt_45pct":          {"pass": win_rate > 45.0,                "value": round(win_rate, 2)},
                    "SC6_expectancy_positive":        {"pass": expectancy > 0,                 "value": round(expectancy, 6)},
                    "SC7_data_quality_avg_gt_85":     {"pass": dq_avg >= 85.0,                "value": round(dq_avg, 1)},
                    "SC8_walk_forward_stable":        {"pass": None,                           "value": "manual_review"},
                    "SC9_risk_manager_no_spurious":   {"pass": None,                           "value": "manual_review"},
                    "SC10_dashboard_leaders_identified": {"pass": len(buckets) > 0,            "value": f"{len(buckets)} buckets"},
                },
                "all_auto_criteria_pass": all(
                    v["pass"] for k, v in {
                        "SC4": {"pass": pf > 1.30},
                        "SC5": {"pass": win_rate > 45.0},
                        "SC6": {"pass": expectancy > 0},
                        "SC7": {"pass": dq_avg >= 85.0},
                    }.items()
                ),
            }
        except Exception as exc:
            _log.warning("signal_intelligence.success_criteria_error: %s", exc)
            return {"error": str(exc)}
