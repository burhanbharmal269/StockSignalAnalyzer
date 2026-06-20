"""LossClusterService — Phase 20.6 Sections 5 & 6.

Section 5 — Loss Cluster Detection:
  Finds recurring multi-condition failure combinations.
  Each cluster is a named set of co-occurring conditions in losing trades.
  Output: cluster label, frequency, % of total losses, avg pnl, avg confidence.

Section 6 — Winner Cluster Detection:
  Same approach for target-hit trades.
  Output: cluster label, frequency, % of total wins, avg pnl.

Clustering approach:
  - Categorical attributes: failure_reason, regime, mtf_cohort, score_bucket, time_window, dte_bucket
  - For each N-dimensional combination (where N=2,3), count co-occurrence frequency
  - Top clusters = most frequent co-occurring conditions

Clusters are labeled as a human-readable combination string:
  "VWAP_FAILURE + SIDEWAYS + MTF_CONFLICT"

All methods are read-only analytics.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Shared SQL fragments
_MTF_CASE = """
    CASE
      WHEN mtf_alignment IS NULL OR mtf_alignment = 'NEUTRAL' THEN 'MTF_NEUTRAL'
      WHEN (direction='CE' AND mtf_alignment='BULLISH')
        OR (direction='PE' AND mtf_alignment='BEARISH') THEN 'MTF_ALIGNED'
      ELSE 'MTF_CONFLICT'
    END
"""

_TW_CASE = """
    CASE
      WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
          + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
           BETWEEN 570 AND 629 THEN 'EARLY_SESSION'
      WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
          + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
           BETWEEN 630 AND 719 THEN 'MID_MORNING'
      WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
          + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
           BETWEEN 720 AND 809 THEN 'MIDDAY'
      WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
          + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
           BETWEEN 810 AND 869 THEN 'LATE_SESSION'
      ELSE 'END_OF_DAY'
    END
"""

_SCORE_CASE = """
    CASE
      WHEN adjusted_score BETWEEN 60 AND 64 THEN 'SCORE_60-64'
      WHEN adjusted_score BETWEEN 65 AND 69 THEN 'SCORE_65-69'
      WHEN adjusted_score BETWEEN 70 AND 74 THEN 'SCORE_70-74'
      WHEN adjusted_score BETWEEN 75 AND 79 THEN 'SCORE_75-79'
      WHEN adjusted_score >= 80             THEN 'SCORE_80+'
      ELSE 'SCORE_OTHER'
    END
"""

_DTE_CASE = """
    CASE
      WHEN dte <= 1 THEN 'LOW_DTE'
      WHEN dte <= 3 THEN 'MED_DTE'
      ELSE 'NORMAL_DTE'
    END
"""


def _cluster_label(*parts: str | None) -> str:
    return " + ".join(p for p in parts if p and p not in ("None",))


class LossClusterService:
    """Identifies recurring loss and winner condition clusters."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Section 5 — Loss Clusters ─────────────────────────────────────────────

    async def get_loss_clusters(
        self, lookback_days: int = 30, top_n: int = 15
    ) -> dict:
        """Find the most common multi-condition failure clusters.

        Crosses: failure_reason × regime × mtf_cohort × time_window

        Each combination counts how often it co-occurs in losing trades.
        Sorted by frequency × avg_confidence (most reliable, most common).
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

        # Primary cluster: failure_reason × regime × mtf
        primary = await self._loss_primary(cutoff, top_n)
        # Secondary: regime × mtf × time_window (no attribution required)
        secondary = await self._loss_secondary(cutoff, top_n)
        # Score-based: score_bucket × regime (what scores are losing in which regimes)
        score_based = await self._loss_score_regime(cutoff, top_n)

        return {
            "lookback_days":   lookback_days,
            "primary_clusters":   primary,
            "secondary_clusters": secondary,
            "score_clusters":     score_based,
            "evaluated_at":    datetime.now(UTC).isoformat(),
        }

    async def _loss_primary(self, cutoff: datetime, top_n: int) -> list[dict]:
        """failure_reason × regime × mtf_cohort (requires attribution)."""
        try:
            async with self._sf() as db:
                r_total = await db.execute(
                    text("SELECT COUNT(*) FROM signal_analytics WHERE stop_hit=true AND was_accepted=true AND created_at >= :cutoff"),
                    {"cutoff": cutoff},
                )
                total = int((r_total.fetchone() or [0])[0])

                r = await db.execute(
                    text(f"""
                        SELECT
                          COALESCE(failure_reason, 'UNATTRIBUTED') AS failure,
                          regime,
                          ({_MTF_CASE})                             AS mtf,
                          ({_TW_CASE})                              AS time_window,
                          COUNT(*)                                  AS cluster_n,
                          ROUND(AVG(failure_confidence)::numeric,3) AS avg_conf,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS avg_pnl,
                          ROUND(AVG(adjusted_score)::numeric,1)     AS avg_score
                        FROM signal_analytics
                        WHERE stop_hit = true AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY failure, regime, mtf, time_window
                        HAVING COUNT(*) >= 3
                        ORDER BY COUNT(*) DESC
                        LIMIT :top_n
                    """),
                    {"cutoff": cutoff, "top_n": top_n},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("loss_cluster.primary_error: %s", exc)
            return []

        return [
            {
                "cluster":          _cluster_label(row[0], row[1], row[2], row[3]),
                "failure_reason":   row[0],
                "regime":           row[1],
                "mtf_cohort":       row[2],
                "time_window":      row[3],
                "frequency":        int(row[4] or 0),
                "pct_of_losses":    round(int(row[4] or 0) / max(total, 1) * 100, 1),
                "avg_confidence":   float(row[5]) if row[5] else None,
                "avg_pnl_pct":      float(row[6]) if row[6] else None,
                "avg_score":        float(row[7]) if row[7] else None,
            }
            for row in rows
        ]

    async def _loss_secondary(self, cutoff: datetime, top_n: int) -> list[dict]:
        """regime × mtf_cohort × time_window — no attribution required."""
        try:
            async with self._sf() as db:
                r_total = await db.execute(
                    text("SELECT COUNT(*) FROM signal_analytics WHERE stop_hit=true AND was_accepted=true AND created_at>=:cutoff"),
                    {"cutoff": cutoff},
                )
                total = int((r_total.fetchone() or [0])[0])

                r = await db.execute(
                    text(f"""
                        SELECT
                          regime,
                          ({_MTF_CASE})  AS mtf,
                          ({_TW_CASE})   AS time_window,
                          ({_DTE_CASE})  AS dte_group,
                          COUNT(*)       AS cluster_n,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS avg_pnl,
                          ROUND(AVG(adjusted_score)::numeric,1) AS avg_score,
                          ROUND(AVG(volume_ratio_at_signal)::numeric,2) AS avg_vol_ratio
                        FROM signal_analytics
                        WHERE stop_hit = true AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY regime, mtf, time_window, dte_group
                        HAVING COUNT(*) >= 3
                        ORDER BY COUNT(*) DESC
                        LIMIT :top_n
                    """),
                    {"cutoff": cutoff, "top_n": top_n},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("loss_cluster.secondary_error: %s", exc)
            return []

        return [
            {
                "cluster":        _cluster_label(row[0], row[1], row[2], row[3]),
                "regime":         row[0],
                "mtf_cohort":     row[1],
                "time_window":    row[2],
                "dte_group":      row[3],
                "frequency":      int(row[4] or 0),
                "pct_of_losses":  round(int(row[4] or 0) / max(total, 1) * 100, 1),
                "avg_pnl_pct":    float(row[5]) if row[5] else None,
                "avg_score":      float(row[6]) if row[6] else None,
                "avg_vol_ratio":  float(row[7]) if row[7] else None,
            }
            for row in rows
        ]

    async def _loss_score_regime(self, cutoff: datetime, top_n: int) -> list[dict]:
        """score_bucket × regime — losing patterns by score level and regime."""
        try:
            async with self._sf() as db:
                r_total = await db.execute(
                    text("SELECT COUNT(*) FROM signal_analytics WHERE stop_hit=true AND was_accepted=true AND created_at>=:cutoff"),
                    {"cutoff": cutoff},
                )
                total = int((r_total.fetchone() or [0])[0])

                r = await db.execute(
                    text(f"""
                        SELECT
                          ({_SCORE_CASE}) AS score_bucket,
                          regime,
                          COUNT(*)        AS cluster_n,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS avg_pnl,
                          ROUND(AVG(mae_pct)*100,3) AS avg_mae
                        FROM signal_analytics
                        WHERE stop_hit = true AND was_accepted = true
                          AND adjusted_score IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY score_bucket, regime
                        HAVING COUNT(*) >= 3
                        ORDER BY COUNT(*) DESC
                        LIMIT :top_n
                    """),
                    {"cutoff": cutoff, "top_n": top_n},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("loss_cluster.score_error: %s", exc)
            return []

        return [
            {
                "cluster":       _cluster_label(row[0], row[1]),
                "score_bucket":  row[0],
                "regime":        row[1],
                "frequency":     int(row[2] or 0),
                "pct_of_losses": round(int(row[2] or 0) / max(total, 1) * 100, 1),
                "avg_pnl_pct":   float(row[3]) if row[3] else None,
                "avg_mae_pct":   float(row[4]) if row[4] else None,
            }
            for row in rows
        ]

    # ── Section 6 — Winner Clusters ───────────────────────────────────────────

    async def get_winner_clusters(
        self, lookback_days: int = 30, top_n: int = 15
    ) -> dict:
        """Find the most common multi-condition winner patterns."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        primary   = await self._winner_primary(cutoff, top_n)
        secondary = await self._winner_secondary(cutoff, top_n)

        return {
            "lookback_days":      lookback_days,
            "primary_clusters":   primary,
            "secondary_clusters": secondary,
            "evaluated_at":       datetime.now(UTC).isoformat(),
        }

    async def _winner_primary(self, cutoff: datetime, top_n: int) -> list[dict]:
        """success_reason × regime × mtf_cohort (requires attribution)."""
        try:
            async with self._sf() as db:
                r_total = await db.execute(
                    text("SELECT COUNT(*) FROM signal_analytics WHERE target_hit=true AND was_accepted=true AND created_at>=:cutoff"),
                    {"cutoff": cutoff},
                )
                total = int((r_total.fetchone() or [0])[0])

                r = await db.execute(
                    text(f"""
                        SELECT
                          COALESCE(success_reason, 'UNATTRIBUTED') AS success,
                          regime,
                          ({_MTF_CASE})                             AS mtf,
                          ({_TW_CASE})                              AS time_window,
                          COUNT(*)                                  AS cluster_n,
                          ROUND(AVG(success_confidence)::numeric,3) AS avg_conf,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS avg_pnl,
                          ROUND(AVG(mfe_pct)*100,3)                 AS avg_mfe,
                          ROUND(AVG(time_to_target_minutes)::numeric,1) AS avg_ttt
                        FROM signal_analytics
                        WHERE target_hit = true AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY success, regime, mtf, time_window
                        HAVING COUNT(*) >= 3
                        ORDER BY COUNT(*) DESC
                        LIMIT :top_n
                    """),
                    {"cutoff": cutoff, "top_n": top_n},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("winner_cluster.primary_error: %s", exc)
            return []

        return [
            {
                "cluster":          _cluster_label(row[0], row[1], row[2], row[3]),
                "success_reason":   row[0],
                "regime":           row[1],
                "mtf_cohort":       row[2],
                "time_window":      row[3],
                "frequency":        int(row[4] or 0),
                "pct_of_wins":      round(int(row[4] or 0) / max(total, 1) * 100, 1),
                "avg_confidence":   float(row[5]) if row[5] else None,
                "avg_pnl_pct":      float(row[6]) if row[6] else None,
                "avg_mfe_pct":      float(row[7]) if row[7] else None,
                "avg_time_to_target": float(row[8]) if row[8] else None,
            }
            for row in rows
        ]

    async def _winner_secondary(self, cutoff: datetime, top_n: int) -> list[dict]:
        """regime × mtf_cohort × time_window × score_bucket (no attribution required)."""
        try:
            async with self._sf() as db:
                r_total = await db.execute(
                    text("SELECT COUNT(*) FROM signal_analytics WHERE target_hit=true AND was_accepted=true AND created_at>=:cutoff"),
                    {"cutoff": cutoff},
                )
                total = int((r_total.fetchone() or [0])[0])

                r = await db.execute(
                    text(f"""
                        SELECT
                          regime,
                          ({_MTF_CASE})   AS mtf,
                          ({_TW_CASE})    AS time_window,
                          ({_SCORE_CASE}) AS score_bucket,
                          COUNT(*)        AS cluster_n,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS avg_pnl,
                          ROUND(AVG(mfe_pct)*100,3) AS avg_mfe,
                          ROUND(AVG(time_to_target_minutes)::numeric,1) AS avg_ttt,
                          ROUND(AVG(volume_ratio_at_signal)::numeric,2) AS avg_vol
                        FROM signal_analytics
                        WHERE target_hit = true AND was_accepted = true
                          AND adjusted_score IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY regime, mtf, time_window, score_bucket
                        HAVING COUNT(*) >= 3
                        ORDER BY avg_pnl DESC NULLS LAST
                        LIMIT :top_n
                    """),
                    {"cutoff": cutoff, "top_n": top_n},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("winner_cluster.secondary_error: %s", exc)
            return []

        return [
            {
                "cluster":         _cluster_label(row[0], row[1], row[2], row[3]),
                "regime":          row[0],
                "mtf_cohort":      row[1],
                "time_window":     row[2],
                "score_bucket":    row[3],
                "frequency":       int(row[4] or 0),
                "pct_of_wins":     round(int(row[4] or 0) / max(total, 1) * 100, 1),
                "avg_pnl_pct":     float(row[5]) if row[5] else None,
                "avg_mfe_pct":     float(row[6]) if row[6] else None,
                "avg_time_to_target": float(row[7]) if row[7] else None,
                "avg_vol_ratio":   float(row[8]) if row[8] else None,
            }
            for row in rows
        ]

    # ── Combined report ───────────────────────────────────────────────────────

    async def get_cluster_report(self, lookback_days: int = 30) -> dict:
        """Combined loss and winner cluster report."""
        import asyncio
        losses, winners = await asyncio.gather(
            self.get_loss_clusters(lookback_days),
            self.get_winner_clusters(lookback_days),
            return_exceptions=True,
        )
        return {
            "lookback_days": lookback_days,
            "loss_clusters": losses if not isinstance(losses, Exception) else {"error": str(losses)},
            "winner_clusters": winners if not isinstance(winners, Exception) else {"error": str(winners)},
            "evaluated_at": datetime.now(UTC).isoformat(),
        }
