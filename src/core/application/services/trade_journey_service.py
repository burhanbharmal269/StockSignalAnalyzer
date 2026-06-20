"""TradeJourneyService — Phase 20.5 Sections 15, 16, 17.

Sections:
  15 — Trade Journey Engine (lifecycle timing and excursion analysis)
  16 — Stop Loss Intelligence (distribution by timing bucket)
  17 — Recovery Analysis (did price recover after stop?)

All methods are read-only analytics. No writes to production tables.

MFE/MAE, time_to_target_minutes, and time_to_stop_minutes are already
populated by SignalOutcomeTrackerService. Recovery analysis uses the
post_trade_intelligence columns written by PostTradeIntelligenceService.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


class TradeJourneyService:
    """Analytics for trade lifecycle timing, excursion profiles, and recovery."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Section 15 — Trade Journey ────────────────────────────────────────────

    async def get_journey_profile(self, lookback_days: int = 30) -> dict:
        """MFE, MAE, time-to-target, time-to-stop distributions for all outcomes.

        Answers:
          - On average, how far did winning trades go before the target?
          - On average, how much heat did we take before a win?
          - How quickly do losses materialise?
          - What is the typical MFE before a stop?
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          -- Winners
                          ROUND(AVG(mfe_pct) FILTER (WHERE target_hit)*100, 3)  AS win_avg_mfe,
                          ROUND(AVG(mae_pct) FILTER (WHERE target_hit)*100, 3)  AS win_avg_mae,
                          ROUND(percentile_cont(0.50) WITHIN GROUP (ORDER BY mfe_pct)
                                FILTER (WHERE target_hit)*100, 3)               AS win_med_mfe,
                          ROUND(percentile_cont(0.50) WITHIN GROUP (ORDER BY mae_pct)
                                FILTER (WHERE target_hit)*100, 3)               AS win_med_mae,
                          ROUND(AVG(time_to_target_minutes) FILTER (WHERE target_hit), 1)
                                                                                AS win_avg_time_to_target,
                          ROUND(percentile_cont(0.25) WITHIN GROUP
                                (ORDER BY time_to_target_minutes)
                                FILTER (WHERE target_hit), 1)                  AS win_p25_time_to_target,
                          ROUND(percentile_cont(0.75) WITHIN GROUP
                                (ORDER BY time_to_target_minutes)
                                FILTER (WHERE target_hit), 1)                  AS win_p75_time_to_target,

                          -- Losers
                          ROUND(AVG(mfe_pct) FILTER (WHERE stop_hit)*100, 3)   AS loss_avg_mfe,
                          ROUND(AVG(mae_pct) FILTER (WHERE stop_hit)*100, 3)   AS loss_avg_mae,
                          ROUND(percentile_cont(0.50) WITHIN GROUP (ORDER BY mfe_pct)
                                FILTER (WHERE stop_hit)*100, 3)                AS loss_med_mfe,
                          ROUND(percentile_cont(0.50) WITHIN GROUP (ORDER BY mae_pct)
                                FILTER (WHERE stop_hit)*100, 3)                AS loss_med_mae,
                          ROUND(AVG(time_to_stop_minutes) FILTER (WHERE stop_hit), 1)
                                                                                AS loss_avg_time_to_stop,
                          ROUND(percentile_cont(0.25) WITHIN GROUP
                                (ORDER BY time_to_stop_minutes)
                                FILTER (WHERE stop_hit), 1)                    AS loss_p25_time_to_stop,
                          ROUND(percentile_cont(0.75) WITHIN GROUP
                                (ORDER BY time_to_stop_minutes)
                                FILTER (WHERE stop_hit), 1)                    AS loss_p75_time_to_stop,

                          -- Counts
                          COUNT(*) FILTER (WHERE target_hit)                   AS win_count,
                          COUNT(*) FILTER (WHERE stop_hit)                     AS loss_count
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("journey.profile_error: %s", exc)
            return {"error": str(exc)}

        def _f(v) -> float | None:
            return float(v) if v is not None else None

        return {
            "lookback_days":  lookback_days,
            "evaluated_at":   datetime.now(UTC).isoformat(),
            "winners": {
                "count":              int(row[16] or 0),
                "avg_mfe_pct":        _f(row[0]),
                "avg_mae_pct":        _f(row[1]),
                "median_mfe_pct":     _f(row[2]),
                "median_mae_pct":     _f(row[3]),
                "avg_time_to_target": _f(row[4]),
                "p25_time_to_target": _f(row[5]),
                "p75_time_to_target": _f(row[6]),
                "interpretation": (
                    "Winners take on average {:.1f}% heat before hitting target in {:.0f} min.".format(
                        float(row[1] or 0) * 100, float(row[4] or 0)
                    ) if row[1] and row[4] else "Insufficient data."
                ),
            },
            "losers": {
                "count":              int(row[17] or 0),
                "avg_mfe_pct":        _f(row[7]),
                "avg_mae_pct":        _f(row[8]),
                "median_mfe_pct":     _f(row[9]),
                "median_mae_pct":     _f(row[10]),
                "avg_time_to_stop":   _f(row[11]),
                "p25_time_to_stop":   _f(row[12]),
                "p75_time_to_stop":   _f(row[13]),
                "interpretation": (
                    "Losers had {:.1f}% MFE before reversing; stop hit in {:.0f} min avg.".format(
                        float(row[9] or 0) * 100, float(row[11] or 0)
                    ) if row[9] and row[11] else "Insufficient data."
                ),
            },
        }

    # ── Section 16 — Stop-Loss Intelligence ──────────────────────────────────

    async def get_stop_distribution_report(self, lookback_days: int = 30) -> dict:
        """Classify stopouts by timing bucket.

        Buckets:
          IMMEDIATE  0–15 min
          EARLY     15–30 min
          MEDIUM    30–60 min
          LATE      60+  min

        A high IMMEDIATE% suggests entries are poor or stops are too tight.
        A high LATE% suggests regime shifts or overnight risk.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                # Use stop_timing_bucket if available (post-attribution), else compute live
                r = await db.execute(
                    text("""
                        SELECT
                          COALESCE(
                            stop_timing_bucket,
                            CASE
                              WHEN time_to_stop_minutes <= 15  THEN 'IMMEDIATE'
                              WHEN time_to_stop_minutes <= 30  THEN 'EARLY'
                              WHEN time_to_stop_minutes <= 60  THEN 'MEDIUM'
                              ELSE 'LATE'
                            END
                          )                                       AS bucket,
                          COUNT(*)                                AS n,
                          ROUND(AVG(mfe_pct)*100, 3)             AS avg_mfe,
                          ROUND(AVG(adjusted_score), 1)          AS avg_score,
                          ROUND(AVG(data_quality_score), 1)      AS avg_dq
                        FROM signal_analytics
                        WHERE stop_hit = true
                          AND was_accepted = true
                          AND time_to_stop_minutes IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY bucket
                        ORDER BY MIN(time_to_stop_minutes)
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()

                # Total for percentages
                r_total = await db.execute(
                    text("""
                        SELECT COUNT(*) FROM signal_analytics
                        WHERE stop_hit = true AND was_accepted = true
                          AND time_to_stop_minutes IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                total = int((r_total.fetchone() or [0])[0])
        except Exception as exc:
            _log.warning("journey.stop_dist_error: %s", exc)
            return {"error": str(exc)}

        buckets = []
        for row in rows:
            n = int(row[1] or 0)
            buckets.append({
                "bucket":    row[0],
                "count":     n,
                "pct":       round(n / total * 100, 1) if total else 0,
                "avg_mfe_pct": float(row[2]) if row[2] else None,
                "avg_score": float(row[3]) if row[3] else None,
                "avg_dq":    float(row[4]) if row[4] else None,
            })

        # Diagnosis
        imm = next((b for b in buckets if b["bucket"] == "IMMEDIATE"), None)
        imm_pct = imm["pct"] if imm else 0
        diagnosis = (
            "ENTRY_QUALITY_ISSUE" if imm_pct > 40 else
            "STOP_TOO_TIGHT"      if imm_pct > 30 else
            "NORMAL_DISTRIBUTION"
        )

        return {
            "lookback_days":         lookback_days,
            "total_stopouts":        total,
            "buckets":               buckets,
            "immediate_pct":         imm_pct,
            "diagnosis":             diagnosis,
            "diagnosis_message": (
                f"{imm_pct:.1f}% of stops hit within 15 min. "
                + ("Review entry quality — late entries or stops too tight for normal volatility."
                   if imm_pct > 30 else
                   "Stop timing distribution is normal.")
            ),
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    # ── Section 17 — Recovery Analysis ───────────────────────────────────────

    async def get_recovery_analysis(self, lookback_days: int = 30) -> dict:
        """Analyse whether stopped trades recovered after the stop.

        Uses post_trade_intelligence columns (recovered_after_stop, future_mfe_pct,
        recovery_time_minutes) if available. Falls back to MFE-only analysis.

        Answers:
          - What fraction of stopped trades would have hit breakeven later?
          - What fraction would have hit the original target?
          - What is the typical recovery time?
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                # Primary: use enriched recovery columns
                r_enr = await db.execute(
                    text("""
                        SELECT
                          COUNT(*)                                               AS total_stops,
                          COUNT(*) FILTER (WHERE recovered_after_stop = true)   AS recovered,
                          ROUND(AVG(recovery_time_minutes)
                                FILTER (WHERE recovered_after_stop = true), 1)  AS avg_recovery_min,
                          ROUND(AVG(future_mfe_pct)*100
                                FILTER (WHERE future_mfe_pct IS NOT NULL), 3)   AS avg_future_mfe
                        FROM signal_analytics
                        WHERE stop_hit = true
                          AND was_accepted = true
                          AND attributed_at IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                enr = r_enr.fetchone()

                # Fallback: MFE-based approximate recovery
                # If mfe_pct (max favourable excursion) existed for losing trades,
                # they had a moment where they were ahead of entry — MFE > 0 proxies recovery
                r_mfe = await db.execute(
                    text("""
                        SELECT
                          COUNT(*)                                              AS total_stops,
                          COUNT(*) FILTER (WHERE mfe_pct > 0.005)              AS had_positive_mfe,
                          COUNT(*) FILTER (WHERE mfe_pct > 0.25)               AS would_hit_25pct,
                          COUNT(*) FILTER (WHERE mfe_pct > 0.50)               AS would_hit_50pct,
                          ROUND(AVG(mfe_pct)*100, 3)                           AS avg_mfe
                        FROM signal_analytics
                        WHERE stop_hit = true
                          AND was_accepted = true
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                mfe_row = r_mfe.fetchone()
        except Exception as exc:
            _log.warning("journey.recovery_error: %s", exc)
            return {"error": str(exc)}

        total = int(mfe_row[0] or 0)
        had_positive = int(mfe_row[1] or 0)
        hit_25 = int(mfe_row[2] or 0)
        hit_50 = int(mfe_row[3] or 0)

        # Enriched recovery data if available
        enr_total   = int(enr[0] or 0)
        enr_recover = int(enr[1] or 0)

        pct = lambda n: round(n / total * 100, 1) if total else 0

        return {
            "lookback_days":     lookback_days,
            "total_stopouts":    total,
            # MFE-based proxies (always available)
            "had_positive_mfe":  had_positive,
            "had_positive_mfe_pct": pct(had_positive),
            "would_hit_breakeven_pct": pct(had_positive),  # mfe > 0 ≈ breakeven
            "would_hit_25pct_pct":     pct(hit_25),
            "would_hit_50pct_pct":     pct(hit_50),
            "avg_mfe_on_losses_pct":   float(mfe_row[4]) if mfe_row[4] else None,
            # Enriched recovery (available after PostTradeIntelligenceService runs)
            "enriched_attribution_available": enr_total > 0,
            "enriched_stop_count":   enr_total,
            "enriched_recovered":    enr_recover,
            "enriched_recovery_pct": round(enr_recover / enr_total * 100, 1) if enr_total else None,
            "avg_recovery_minutes":  float(enr[2]) if enr[2] else None,
            "avg_future_mfe_pct":    float(enr[3]) if enr[3] else None,
            "interpretation": (
                f"{pct(had_positive):.1f}% of stopped trades had positive MFE before reversing. "
                f"{pct(hit_25):.1f}% would have hit 25% of target; "
                f"{pct(hit_50):.1f}% would have hit 50% of target. "
                + ("High recovery rate suggests stops may be too tight."
                   if had_positive / max(total, 1) > 0.60 else
                   "Recovery rate is within acceptable bounds.")
            ),
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    async def get_entry_exit_summary(self, lookback_days: int = 30) -> dict:
        """Combined entry/exit analysis joining journey + stop distribution + recovery."""
        import asyncio
        journey, stop_dist, recovery = await asyncio.gather(
            self.get_journey_profile(lookback_days),
            self.get_stop_distribution_report(lookback_days),
            self.get_recovery_analysis(lookback_days),
            return_exceptions=True,
        )
        return {
            "lookback_days":       lookback_days,
            "trade_journey":       journey if not isinstance(journey, Exception) else {"error": str(journey)},
            "stop_distribution":   stop_dist if not isinstance(stop_dist, Exception) else {"error": str(stop_dist)},
            "recovery_analysis":   recovery if not isinstance(recovery, Exception) else {"error": str(recovery)},
            "evaluated_at":        datetime.now(UTC).isoformat(),
        }
