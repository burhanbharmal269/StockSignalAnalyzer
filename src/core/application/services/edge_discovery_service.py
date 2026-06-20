"""EdgeDiscoveryService — Phase 20.6 Section 3.

Automatically identifies the strongest and weakest multi-dimensional
trade combinations by crossing:
  score_bucket × regime × mtf_cohort

For each combination with sufficient trades, classifies:
  EDGE_DISCOVERED   PF ≥ 1.50 AND WR ≥ 50% AND n ≥ 20
  EDGE_WEAK         PF ≥ 1.20 OR  WR ≥ 47%  AND n ≥ 10
  NO_EDGE           Below thresholds

Also crosses:
  time_window × regime           — best/worst entry timing
  dte × regime                   — DTE-specific edge
  score_bucket × confidence      — double-confirmation edge

All methods are read-only analytics.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_EDGE_DISCOVERED_PF  = 1.50
_EDGE_DISCOVERED_WR  = 50.0
_EDGE_DISCOVERED_MIN = 20
_EDGE_WEAK_PF        = 1.20
_EDGE_WEAK_WR        = 47.0
_EDGE_WEAK_MIN       = 10

_PERF = """
    COUNT(*)                                                                          AS n,
    ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1)                    AS win_rate,
    ROUND(
      SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END)
      / NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
    ::numeric, 3)                                                                    AS profit_factor,
    ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100, 4)                        AS expectancy,
    ROUND(AVG(mfe_pct)*100, 3)                                                       AS avg_mfe,
    ROUND(AVG(mae_pct)*100, 3)                                                       AS avg_mae
"""

_MTF_CASE = """
    CASE
      WHEN mtf_alignment IS NULL OR mtf_alignment = 'NEUTRAL' THEN 'NEUTRAL'
      WHEN (direction='CE' AND mtf_alignment='BULLISH')
        OR (direction='PE' AND mtf_alignment='BEARISH') THEN 'ALIGNED'
      ELSE 'CONFLICT'
    END
"""

_SCORE_CASE = """
    CASE
      WHEN adjusted_score BETWEEN 60 AND 64 THEN '60-64'
      WHEN adjusted_score BETWEEN 65 AND 69 THEN '65-69'
      WHEN adjusted_score BETWEEN 70 AND 74 THEN '70-74'
      WHEN adjusted_score BETWEEN 75 AND 79 THEN '75-79'
      WHEN adjusted_score BETWEEN 80 AND 84 THEN '80-84'
      WHEN adjusted_score >= 85             THEN '85+'
      ELSE 'OTHER'
    END
"""

_CONF_CASE = """
    CASE
      WHEN confidence < 60               THEN '<60'
      WHEN confidence BETWEEN 60 AND 69  THEN '60-69'
      WHEN confidence BETWEEN 70 AND 79  THEN '70-79'
      WHEN confidence BETWEEN 80 AND 89  THEN '80-89'
      WHEN confidence >= 90              THEN '90+'
      ELSE 'OTHER'
    END
"""

_TW_CASE = """
    CASE
      WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
          + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
           BETWEEN 570 AND 629 THEN '09:30-10:30'
      WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
          + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
           BETWEEN 630 AND 719 THEN '10:30-12:00'
      WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
          + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
           BETWEEN 720 AND 809 THEN '12:00-13:30'
      WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
          + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
           BETWEEN 810 AND 869 THEN '13:30-14:30'
      ELSE '14:30+'
    END
"""

_DTE_CASE = """
    CASE
      WHEN dte = 0  THEN '0-DTE'
      WHEN dte = 1  THEN '1-DTE'
      WHEN dte = 2  THEN '2-DTE'
      WHEN dte >= 3 THEN '3+-DTE'
      ELSE 'UNKNOWN'
    END
"""

_BASE_WHERE = """
    was_accepted = true AND outcome IS NOT NULL
    AND adjusted_score IS NOT NULL
    AND created_at >= :cutoff
"""


def _classify(pf, wr, n) -> str:
    if pf is None or wr is None:
        return "INSUFFICIENT_DATA"
    if n >= _EDGE_DISCOVERED_MIN and pf >= _EDGE_DISCOVERED_PF and wr >= _EDGE_DISCOVERED_WR:
        return "EDGE_DISCOVERED"
    if n >= _EDGE_WEAK_MIN and (pf >= _EDGE_WEAK_PF or wr >= _EDGE_WEAK_WR):
        return "EDGE_WEAK"
    return "NO_EDGE"


def _parse(keys: list[str], row) -> dict:
    n   = int(row[len(keys)] or 0)
    wr  = float(row[len(keys)+1]) if row[len(keys)+1] else None
    pf  = float(row[len(keys)+2]) if row[len(keys)+2] else None
    exp = float(row[len(keys)+3]) if row[len(keys)+3] else None
    mfe = float(row[len(keys)+4]) if row[len(keys)+4] else None
    mae = float(row[len(keys)+5]) if row[len(keys)+5] else None
    return {
        "combination":     {k: str(row[i]) for i, k in enumerate(keys)},
        "label":           " | ".join(f"{k}={row[i]}" for i, k in enumerate(keys)),
        "count":           n,
        "win_rate_pct":    wr,
        "profit_factor":   pf,
        "expectancy_pct":  exp,
        "avg_mfe_pct":     mfe,
        "avg_mae_pct":     mae,
        "edge":            _classify(pf, wr, n),
    }


class EdgeDiscoveryService:
    """Multi-dimensional edge discovery across cohort combinations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def discover_edges(
        self,
        lookback_days: int = 90,
        min_trades:    int = 10,
    ) -> dict:
        """Run all four edge-discovery crosses concurrently.

        Returns best/worst combinations and a summary of where edge exists.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        results = await asyncio.gather(
            self._cross_score_regime_mtf(cutoff, min_trades),
            self._cross_time_regime(cutoff, min_trades),
            self._cross_dte_regime(cutoff, min_trades),
            self._cross_score_confidence(cutoff, min_trades),
            return_exceptions=True,
        )
        labels = ["score_regime_mtf", "time_regime", "dte_regime", "score_confidence"]
        crosses: dict = {}
        all_combos: list[dict] = []
        for label, result in zip(labels, results):
            if isinstance(result, Exception):
                crosses[label] = {"error": str(result)}
            else:
                crosses[label] = result
                all_combos.extend(result.get("combinations", []))

        # Best / worst across all crosses
        valid = [c for c in all_combos if c.get("count", 0) >= min_trades]
        best  = sorted(valid, key=lambda x: x.get("expectancy_pct") or 0, reverse=True)[:10]
        worst = sorted(valid, key=lambda x: x.get("expectancy_pct") or 0)[:10]

        discovered = [c for c in valid if c["edge"] == "EDGE_DISCOVERED"]
        no_edge    = [c for c in valid if c["edge"] == "NO_EDGE"]

        return {
            "lookback_days":          lookback_days,
            "min_trades_threshold":   min_trades,
            "total_combinations":     len(valid),
            "edge_discovered_count":  len(discovered),
            "no_edge_count":          len(no_edge),
            "top_10_combinations":    best,
            "bottom_10_combinations": worst,
            "edge_discovered":        discovered[:10],
            "crosses":                crosses,
            "evaluated_at":           datetime.now(UTC).isoformat(),
        }

    # ── Cross 1: Score × Regime × MTF (primary edge discovery) ───────────────

    async def _cross_score_regime_mtf(self, cutoff: datetime, min_n: int) -> dict:
        sql = f"""
            SELECT
              ({_SCORE_CASE}) AS score_bucket,
              regime,
              ({_MTF_CASE})   AS mtf_cohort,
              {_PERF}
            FROM signal_analytics
            WHERE {_BASE_WHERE}
            GROUP BY score_bucket, regime, mtf_cohort
            HAVING COUNT(*) >= :min_n
            ORDER BY expectancy DESC NULLS LAST
        """
        rows = await self._fetch(sql, cutoff, min_n)
        combos = [_parse(["score_bucket", "regime", "mtf_cohort"], r) for r in rows]
        return {
            "description":  "Score × Regime × MTF — primary edge discovery",
            "combinations": combos,
            "best":         [c for c in combos if c["edge"] == "EDGE_DISCOVERED"][:5],
            "worst":        [c for c in combos if c["edge"] == "NO_EDGE"][:5],
        }

    # ── Cross 2: Time Window × Regime (timing edge) ──────────────────────────

    async def _cross_time_regime(self, cutoff: datetime, min_n: int) -> dict:
        sql = f"""
            SELECT
              ({_TW_CASE}) AS time_window,
              regime,
              {_PERF}
            FROM signal_analytics
            WHERE {_BASE_WHERE}
            GROUP BY time_window, regime
            HAVING COUNT(*) >= :min_n
            ORDER BY expectancy DESC NULLS LAST
        """
        rows = await self._fetch(sql, cutoff, min_n)
        combos = [_parse(["time_window", "regime"], r) for r in rows]
        return {
            "description":  "Time Window × Regime — entry timing edge",
            "combinations": combos,
            "best":         [c for c in combos if c["edge"] in ("EDGE_DISCOVERED", "EDGE_WEAK")][:5],
        }

    # ── Cross 3: DTE × Regime (premium decay edge) ───────────────────────────

    async def _cross_dte_regime(self, cutoff: datetime, min_n: int) -> dict:
        sql = f"""
            SELECT
              ({_DTE_CASE}) AS dte_bucket,
              regime,
              {_PERF}
            FROM signal_analytics
            WHERE {_BASE_WHERE} AND dte IS NOT NULL
            GROUP BY dte_bucket, regime
            HAVING COUNT(*) >= :min_n
            ORDER BY expectancy DESC NULLS LAST
        """
        rows = await self._fetch(sql, cutoff, min_n)
        combos = [_parse(["dte_bucket", "regime"], r) for r in rows]
        return {
            "description":  "DTE × Regime — premium decay and expiry edge",
            "combinations": combos,
            "best":         [c for c in combos if c["edge"] in ("EDGE_DISCOVERED", "EDGE_WEAK")][:5],
        }

    # ── Cross 4: Score × Confidence (double-confirmation edge) ───────────────

    async def _cross_score_confidence(self, cutoff: datetime, min_n: int) -> dict:
        sql = f"""
            SELECT
              ({_SCORE_CASE}) AS score_bucket,
              ({_CONF_CASE})  AS conf_bucket,
              {_PERF}
            FROM signal_analytics
            WHERE {_BASE_WHERE} AND confidence IS NOT NULL
            GROUP BY score_bucket, conf_bucket
            HAVING COUNT(*) >= :min_n
            ORDER BY expectancy DESC NULLS LAST
        """
        rows = await self._fetch(sql, cutoff, min_n)
        combos = [_parse(["score_bucket", "conf_bucket"], r) for r in rows]
        return {
            "description":  "Score × Confidence — double-confirmation edge",
            "combinations": combos,
            "best":         [c for c in combos if c["edge"] in ("EDGE_DISCOVERED", "EDGE_WEAK")][:5],
        }

    async def _fetch(self, sql: str, cutoff: datetime, min_n: int) -> list:
        try:
            async with self._sf() as db:
                r = await db.execute(text(sql), {"cutoff": cutoff, "min_n": min_n})
                return r.fetchall()
        except Exception as exc:
            _log.warning("edge.fetch_error: %s", exc)
            return []
