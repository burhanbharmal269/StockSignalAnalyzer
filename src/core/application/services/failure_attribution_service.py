"""Failure Attribution Service — Phase 21.1 Part 5.

Identifies common OI characteristics among failed/losing trades and
generates analytical summaries by failure category.

Reads exclusively from signal_analytics.  Never modifies strategy logic,
never suppresses trades, never affects live execution.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

_log = logging.getLogger(__name__)


class FailureAttributionService:
    """Post-trade failure pattern analysis — Part 5 of Phase 21.1.

    Surfaces common OI conditions at trade entry among failing signals,
    enabling research into whether OI context could have filtered them.
    """

    def __init__(self, session_factory: "async_sessionmaker") -> None:
        self._sf = session_factory

    # ── OI failure patterns (Part 5) ─────────────────────────────────────────

    async def get_oi_failure_patterns(self, days: int = 30) -> dict:
        """Analyse OI conditions at signal time for losing/expired trades.

        Returns:
            Pattern counts, percentage of failures, win rate by OI regime,
            and TMI classification breakdown.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                            COUNT(*) FILTER (WHERE outcome IN ('LOSS','EXPIRED'))
                                AS total_failures,
                            COUNT(*) FILTER (
                                WHERE outcome IN ('LOSS','EXPIRED')
                                  AND oi_regime = 'Long Build-up'
                            ) AS long_buildup_fail,
                            COUNT(*) FILTER (
                                WHERE outcome IN ('LOSS','EXPIRED')
                                  AND oi_direction = 'Falling'
                            ) AS falling_oi_fail,
                            COUNT(*) FILTER (
                                WHERE outcome IN ('LOSS','EXPIRED')
                                  AND oi_quality_score IN ('Poor', 'Unavailable')
                            ) AS poor_quality_fail,
                            COUNT(*) FILTER (
                                WHERE outcome IN ('LOSS','EXPIRED')
                                  AND oi_quality_score IS NULL
                            ) AS no_oi_data_fail,
                            COUNT(*) FILTER (
                                WHERE outcome IN ('LOSS','EXPIRED')
                                  AND trade_classification = 'GOOD_ENTRY_PREMIUM_DECAY'
                            ) AS premium_decay,
                            COUNT(*) FILTER (
                                WHERE outcome IN ('LOSS','EXPIRED')
                                  AND trade_classification = 'GOOD_ENTRY_REGIME_REVERSAL'
                            ) AS regime_reversal,
                            COUNT(*) FILTER (
                                WHERE outcome IN ('LOSS','EXPIRED')
                                  AND trade_classification = 'BAD_ENTRY'
                            ) AS bad_entry,
                            -- Win rate per OI regime (all settled trades)
                            ROUND(AVG(CASE
                                WHEN oi_regime='Long Build-up' AND outcome='WIN'  THEN 1.0
                                WHEN oi_regime='Long Build-up' AND outcome IN ('LOSS','EXPIRED') THEN 0.0
                            END) * 100, 2) AS wr_long_buildup,
                            ROUND(AVG(CASE
                                WHEN oi_regime='Short Build-up' AND outcome='WIN'  THEN 1.0
                                WHEN oi_regime='Short Build-up' AND outcome IN ('LOSS','EXPIRED') THEN 0.0
                            END) * 100, 2) AS wr_short_buildup,
                            ROUND(AVG(CASE
                                WHEN oi_regime='Long Unwinding' AND outcome='WIN'  THEN 1.0
                                WHEN oi_regime='Long Unwinding' AND outcome IN ('LOSS','EXPIRED') THEN 0.0
                            END) * 100, 2) AS wr_long_unwinding,
                            ROUND(AVG(CASE
                                WHEN oi_regime='Short Covering' AND outcome='WIN'  THEN 1.0
                                WHEN oi_regime='Short Covering' AND outcome IN ('LOSS','EXPIRED') THEN 0.0
                            END) * 100, 2) AS wr_short_covering,
                            COUNT(*) AS total_settled
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND created_at >= :cutoff
                          AND outcome IS NOT NULL
                    """),
                    {"cutoff": cutoff},
                )
                row = dict(r.fetchone()._mapping)
        except Exception as exc:
            _log.warning("failure_attr.oi_patterns_failed: %s", exc)
            return {"error": str(exc)}

        total_fail = int(row.get("total_failures") or 0)

        def _n(key: str) -> int:
            return int(row.get(key) or 0)

        def _pct(key: str) -> float:
            return round(_n(key) / total_fail * 100, 1) if total_fail > 0 else 0.0

        return {
            "period_days":    days,
            "total_failures": total_fail,
            "total_settled":  _n("total_settled"),
            "patterns": {
                "Long Build-up Failure": {
                    "count":            _n("long_buildup_fail"),
                    "pct_of_failures":  _pct("long_buildup_fail"),
                    "insight":          "Long build-up regime that subsequently reversed",
                },
                "Falling OI Failure": {
                    "count":            _n("falling_oi_fail"),
                    "pct_of_failures":  _pct("falling_oi_fail"),
                    "insight":          "OI was falling at entry — distribution pressure present",
                },
                "Poor OI Quality": {
                    "count":            _n("poor_quality_fail"),
                    "pct_of_failures":  _pct("poor_quality_fail"),
                    "insight":          "OI data was of poor quality — signal context unreliable",
                },
                "No OI Data": {
                    "count":            _n("no_oi_data_fail"),
                    "pct_of_failures":  _pct("no_oi_data_fail"),
                    "insight":          "OI data was unavailable — traded without OI context",
                },
                "Premium Decay": {
                    "count":            _n("premium_decay"),
                    "pct_of_failures":  _pct("premium_decay"),
                    "insight":          "Theta/IV crush killed trade despite correct initial move",
                },
                "Regime Reversal": {
                    "count":            _n("regime_reversal"),
                    "pct_of_failures":  _pct("regime_reversal"),
                    "insight":          "Market regime changed after entry — OI context decoupled",
                },
                "Bad Entry": {
                    "count":            _n("bad_entry"),
                    "pct_of_failures":  _pct("bad_entry"),
                    "insight":          "Entry thesis wrong — instrument never moved favourably",
                },
            },
            "win_rate_by_oi_regime": {
                "Long Build-up":  float(row.get("wr_long_buildup")  or 0),
                "Short Build-up": float(row.get("wr_short_buildup") or 0),
                "Long Unwinding": float(row.get("wr_long_unwinding") or 0),
                "Short Covering": float(row.get("wr_short_covering") or 0),
            },
        }

    # ── TMI metrics by OI regime (Part 4 — TMI integration) ──────────────────

    async def get_tmi_by_oi_regime(self, days: int = 30) -> dict:
        """Capture ratio, MFE, profit surrender, opportunity lost — split by OI regime."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                            COALESCE(oi_regime, 'Unknown') AS regime,
                            COUNT(*)                                          AS n,
                            ROUND(AVG(mfe_pct)::numeric, 2)                  AS avg_mfe,
                            ROUND(AVG(capture_ratio)::numeric, 4)            AS avg_capture,
                            ROUND(AVG(profit_surrender_pct)::numeric, 2)     AS avg_surrender,
                            ROUND(AVG(opportunity_lost_pct)::numeric, 2)     AS avg_opp_lost,
                            ROUND(AVG(CASE
                                WHEN outcome='WIN' THEN 1.0 ELSE 0.0
                            END)*100, 1) AS win_rate_pct,
                            ROUND(AVG(pnl_pct)::numeric, 4)                  AS avg_pnl,
                            ROUND(AVG(mae_pct)::numeric, 2)                  AS avg_mae
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND created_at >= :cutoff
                          AND outcome IN ('WIN','LOSS','EXPIRED','PARTIAL')
                          AND mfe_pct IS NOT NULL
                        GROUP BY oi_regime
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("failure_attr.tmi_regime_failed: %s", exc)
            return {"error": str(exc)}

        return {
            "period_days": days,
            "by_oi_regime": [
                {
                    "regime":         row[0],
                    "n":              int(row[1] or 0),
                    "avg_mfe_pct":    float(row[2] or 0),
                    "avg_capture":    float(row[3] or 0),
                    "avg_surrender":  float(row[4] or 0),
                    "avg_opp_lost":   float(row[5] or 0),
                    "win_rate_pct":   float(row[6] or 0),
                    "avg_pnl_pct":    float(row[7] or 0),
                    "avg_mae_pct":    float(row[8] or 0),
                }
                for row in rows
            ],
        }

    # ── Walk-forward regime performance (Part 8) ──────────────────────────────

    async def get_regime_walk_forward(self, days: int = 90) -> dict:
        """Win rate, profit factor, expectancy, MAE, MFE — by OI regime.

        Read-only. Generates recommendations for research; does NOT
        recalibrate the strategy.
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
                            ROUND(
                                SUM(CASE WHEN outcome='WIN' THEN ABS(COALESCE(pnl_pct,0)) ELSE 0 END)
                                / NULLIF(SUM(CASE WHEN outcome IN ('LOSS','EXPIRED')
                                              THEN ABS(COALESCE(pnl_pct,0)) ELSE 0 END), 0),
                                3
                            ) AS profit_factor,
                            ROUND(AVG(COALESCE(pnl_pct,0))*100, 4) AS expectancy,
                            ROUND(AVG(mae_pct)::numeric, 2) AS avg_mae,
                            ROUND(AVG(mfe_pct)::numeric, 2) AS avg_mfe,
                            ROUND(MIN(pnl_pct)*100::numeric, 4) AS max_drawdown
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
            _log.warning("failure_attr.walk_forward_failed: %s", exc)
            return {"error": str(exc)}

        results = [
            {
                "regime":           row[0],
                "n":                int(row[1] or 0),
                "win_rate_pct":     float(row[2] or 0),
                "profit_factor":    float(row[3]) if row[3] else None,
                "expectancy_bps":   float(row[4] or 0),
                "avg_mae_pct":      float(row[5] or 0),
                "avg_mfe_pct":      float(row[6] or 0),
                "max_drawdown_pct": float(row[7] or 0),
            }
            for row in rows
        ]

        # Generate text recommendations (Part 8 — never touch strategy)
        recommendations = []
        for r in results:
            if r["n"] < 10:
                continue
            if r["win_rate_pct"] > 60 and r["profit_factor"] and r["profit_factor"] > 1.5:
                recommendations.append(
                    f"{r['regime']}: strong performance (WR {r['win_rate_pct']}%, "
                    f"PF {r['profit_factor']:.2f}). Consider investigating why this regime favours entries."
                )
            elif r["win_rate_pct"] < 40:
                recommendations.append(
                    f"{r['regime']}: weak performance (WR {r['win_rate_pct']}%). "
                    "Research whether OI context can be used to filter these entries post-strategy."
                )

        return {
            "period_days":       days,
            "by_oi_regime":      results,
            "recommendations":   recommendations,
            "note":              "Recommendations are research-only. Strategy is not modified.",
        }
