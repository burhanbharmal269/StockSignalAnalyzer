"""ComponentAttributionService — Phase 20.5 Sections 19, 20.

Section 19 — Component Attribution:
  Per-component statistics (avg, median, p95) split by winners vs losers.
  Identifies which components are most predictive of outcome.

Section 20 — Gate Attribution:
  Analyses risk_decisions gate checks to identify which gates protect capital
  and which contribute little value.

All methods are read-only analytics.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_COMPONENTS = [
    ("trend_score",        "Trend"),
    ("volume_score",       "Volume"),
    ("vwap_score",         "VWAP"),
    ("oi_score",           "OI Buildup"),
    ("sentiment_score",    "Sentiment"),
    ("iv_score",           "IV"),
    ("option_chain_score", "Option Chain"),
]


class ComponentAttributionService:
    """Component and gate effectiveness analytics."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Section 19 — Component Attribution ───────────────────────────────────

    async def get_component_performance(self, lookback_days: int = 30) -> dict:
        """Per-component stats (avg, median, p95) split by winners and losers.

        Purpose: identify which components are most predictive of good outcomes.

        A component with:
          high winner_avg AND low loser_avg → strong discriminator
          similar winner/loser avgs         → weak discriminator (potential deadweight)
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          -- Trend
                          ROUND(AVG(trend_score) FILTER (WHERE target_hit), 2)                    AS t_win_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY trend_score)
                                FILTER (WHERE target_hit), 2)                                     AS t_win_med,
                          ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY trend_score)
                                FILTER (WHERE target_hit), 2)                                     AS t_win_p95,
                          ROUND(AVG(trend_score) FILTER (WHERE stop_hit), 2)                     AS t_loss_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY trend_score)
                                FILTER (WHERE stop_hit), 2)                                       AS t_loss_med,

                          -- Volume
                          ROUND(AVG(volume_score) FILTER (WHERE target_hit), 2)                  AS v_win_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY volume_score)
                                FILTER (WHERE target_hit), 2)                                     AS v_win_med,
                          ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY volume_score)
                                FILTER (WHERE target_hit), 2)                                     AS v_win_p95,
                          ROUND(AVG(volume_score) FILTER (WHERE stop_hit), 2)                    AS v_loss_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY volume_score)
                                FILTER (WHERE stop_hit), 2)                                       AS v_loss_med,

                          -- VWAP
                          ROUND(AVG(vwap_score) FILTER (WHERE target_hit), 2)                    AS vw_win_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY vwap_score)
                                FILTER (WHERE target_hit), 2)                                     AS vw_win_med,
                          ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY vwap_score)
                                FILTER (WHERE target_hit), 2)                                     AS vw_win_p95,
                          ROUND(AVG(vwap_score) FILTER (WHERE stop_hit), 2)                      AS vw_loss_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY vwap_score)
                                FILTER (WHERE stop_hit), 2)                                       AS vw_loss_med,

                          -- OI
                          ROUND(AVG(oi_score) FILTER (WHERE target_hit), 2)                      AS oi_win_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY oi_score)
                                FILTER (WHERE target_hit), 2)                                     AS oi_win_med,
                          ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY oi_score)
                                FILTER (WHERE target_hit), 2)                                     AS oi_win_p95,
                          ROUND(AVG(oi_score) FILTER (WHERE stop_hit), 2)                        AS oi_loss_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY oi_score)
                                FILTER (WHERE stop_hit), 2)                                       AS oi_loss_med,

                          -- Option Chain
                          ROUND(AVG(option_chain_score) FILTER (WHERE target_hit), 2)            AS oc_win_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY option_chain_score)
                                FILTER (WHERE target_hit), 2)                                     AS oc_win_med,
                          ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY option_chain_score)
                                FILTER (WHERE target_hit), 2)                                     AS oc_win_p95,
                          ROUND(AVG(option_chain_score) FILTER (WHERE stop_hit), 2)              AS oc_loss_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY option_chain_score)
                                FILTER (WHERE stop_hit), 2)                                       AS oc_loss_med,

                          -- IV
                          ROUND(AVG(iv_score) FILTER (WHERE target_hit), 2)                      AS iv_win_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY iv_score)
                                FILTER (WHERE target_hit), 2)                                     AS iv_win_med,
                          ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY iv_score)
                                FILTER (WHERE target_hit), 2)                                     AS iv_win_p95,
                          ROUND(AVG(iv_score) FILTER (WHERE stop_hit), 2)                        AS iv_loss_avg,
                          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY iv_score)
                                FILTER (WHERE stop_hit), 2)                                       AS iv_loss_med,

                          -- MTF
                          ROUND(AVG(mtf_score_bonus) FILTER (WHERE target_hit), 2)              AS mtf_win_avg,
                          ROUND(AVG(mtf_score_bonus) FILTER (WHERE stop_hit), 2)                AS mtf_loss_avg,
                          COUNT(*) FILTER (WHERE target_hit)                                     AS win_n,
                          COUNT(*) FILTER (WHERE stop_hit)                                       AS loss_n
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("component.performance_error: %s", exc)
            return {"error": str(exc)}

        def _f(v) -> float | None:
            return float(v) if v is not None else None

        def _disc(win_avg, loss_avg) -> str | None:
            """Rate discriminative power of a component."""
            if win_avg is None or loss_avg is None:
                return None
            diff = float(win_avg) - float(loss_avg)
            if diff > 1.5:
                return "STRONG"
            if diff > 0.5:
                return "MODERATE"
            if diff > 0.0:
                return "WEAK"
            return "NO_DISCRIMINATIVE_POWER"

        win_n  = int(row[36] or 0)
        loss_n = int(row[37] or 0)

        components = [
            {
                "component":          "Trend",
                "winner_avg":         _f(row[0]),
                "winner_median":      _f(row[1]),
                "winner_p95":         _f(row[2]),
                "loser_avg":          _f(row[3]),
                "loser_median":       _f(row[4]),
                "discriminative_power": _disc(row[0], row[3]),
            },
            {
                "component":          "Volume",
                "winner_avg":         _f(row[5]),
                "winner_median":      _f(row[6]),
                "winner_p95":         _f(row[7]),
                "loser_avg":          _f(row[8]),
                "loser_median":       _f(row[9]),
                "discriminative_power": _disc(row[5], row[8]),
            },
            {
                "component":          "VWAP",
                "winner_avg":         _f(row[10]),
                "winner_median":      _f(row[11]),
                "winner_p95":         _f(row[12]),
                "loser_avg":          _f(row[13]),
                "loser_median":       _f(row[14]),
                "discriminative_power": _disc(row[10], row[13]),
            },
            {
                "component":          "OI Buildup",
                "winner_avg":         _f(row[15]),
                "winner_median":      _f(row[16]),
                "winner_p95":         _f(row[17]),
                "loser_avg":          _f(row[18]),
                "loser_median":       _f(row[19]),
                "discriminative_power": _disc(row[15], row[18]),
            },
            {
                "component":          "Option Chain",
                "winner_avg":         _f(row[20]),
                "winner_median":      _f(row[21]),
                "winner_p95":         _f(row[22]),
                "loser_avg":          _f(row[23]),
                "loser_median":       _f(row[24]),
                "discriminative_power": _disc(row[20], row[23]),
            },
            {
                "component":          "IV",
                "winner_avg":         _f(row[25]),
                "winner_median":      _f(row[26]),
                "winner_p95":         _f(row[27]),
                "loser_avg":          _f(row[28]),
                "loser_median":       _f(row[29]),
                "discriminative_power": _disc(row[25], row[28]),
            },
            {
                "component":          "MTF Bonus",
                "winner_avg":         _f(row[30]),
                "winner_median":      None,
                "winner_p95":         None,
                "loser_avg":          _f(row[31]),
                "loser_median":       None,
                "discriminative_power": _disc(row[30], row[31]),
            },
        ]

        # Rank by discriminative power
        _order = {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "NO_DISCRIMINATIVE_POWER": 3, None: 4}
        components.sort(key=lambda c: _order.get(c["discriminative_power"], 4))

        return {
            "lookback_days":  lookback_days,
            "win_count":      win_n,
            "loss_count":     loss_n,
            "components":     components,
            "top_predictor":  components[0]["component"] if components else None,
            "evaluated_at":   datetime.now(UTC).isoformat(),
        }

    async def get_regime_component_breakdown(self, lookback_days: int = 30) -> list[dict]:
        """Per-regime component averages for winners — shows where each component shines."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          regime,
                          COUNT(*) FILTER (WHERE target_hit)                AS wins,
                          COUNT(*) FILTER (WHERE stop_hit)                  AS losses,
                          ROUND(AVG(trend_score)        FILTER (WHERE target_hit), 2) AS t_avg,
                          ROUND(AVG(vwap_score)         FILTER (WHERE target_hit), 2) AS vw_avg,
                          ROUND(AVG(volume_score)       FILTER (WHERE target_hit), 2) AS v_avg,
                          ROUND(AVG(option_chain_score) FILTER (WHERE target_hit), 2) AS oc_avg,
                          ROUND(AVG(oi_score)           FILTER (WHERE target_hit), 2) AS oi_avg
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY regime
                        ORDER BY wins DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("component.regime_error: %s", exc)
            return []

        def _f(v): return float(v) if v is not None else None

        return [
            {
                "regime":         row[0],
                "wins":           int(row[1] or 0),
                "losses":         int(row[2] or 0),
                "win_rate":       round(int(row[1] or 0) / max(int(row[1] or 0) + int(row[2] or 0), 1) * 100, 1),
                "trend_avg_win":  _f(row[3]),
                "vwap_avg_win":   _f(row[4]),
                "volume_avg_win": _f(row[5]),
                "oc_avg_win":     _f(row[6]),
                "oi_avg_win":     _f(row[7]),
            }
            for row in rows
        ]

    # ── Section 20 — Gate Attribution ────────────────────────────────────────

    async def get_gate_effectiveness(self, lookback_days: int = 30) -> dict:
        """Analyse gate-level effectiveness from risk_decisions and signal_analytics.

        For each gate that can reject a signal, we ask:
          1. How many signals did this gate reject?
          2. Of the signals that PASSED this gate, what was the outcome?
          3. Was the gate protecting capital or just suppressing signals?

        Available gate signals:
          - rejection_reason in signal_analytics: gate code when a signal was rejected
          - signal_quality_score: overall quality when the signal did pass
          - model_failure_class: outcome classification for accepted signals
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                # Rejection distribution (rejected signals)
                r_rej = await db.execute(
                    text("""
                        SELECT
                          rejection_reason                                     AS gate,
                          COUNT(*)                                             AS rejected_count,
                          ROUND(AVG(adjusted_score), 1)                       AS avg_score_at_rejection,
                          ROUND(AVG(confidence), 1)                           AS avg_conf_at_rejection
                        FROM signal_analytics
                        WHERE was_accepted = false
                          AND rejection_reason IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY rejection_reason
                        ORDER BY rejected_count DESC
                    """),
                    {"cutoff": cutoff},
                )
                rej_rows = r_rej.fetchall()

                # Risk decisions gate detail (from risk_decisions.checks JSONB)
                r_risk = await db.execute(
                    text("""
                        SELECT
                          rejection_code                                       AS gate,
                          COUNT(*)                                             AS n,
                          ROUND(AVG(CASE WHEN approved THEN 0.0 ELSE 1.0 END)*100, 1) AS rejection_rate_pct
                        FROM risk_decisions
                        WHERE evaluated_at >= :cutoff
                          AND rejection_code IS NOT NULL
                        GROUP BY rejection_code
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                risk_rows = r_risk.fetchall()

                # Outcome of accepted signals by quality tier
                # This shows: do high-quality-score signals have better outcomes? (gate validation)
                r_qual = await db.execute(
                    text("""
                        SELECT
                          signal_quality_category,
                          COUNT(*)                                              AS n,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1) AS win_rate,
                          ROUND(AVG(COALESCE(pnl_pct, current_return_pct))*100, 4)       AS avg_pnl
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND signal_quality_category IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY signal_quality_category
                        ORDER BY avg_pnl DESC
                    """),
                    {"cutoff": cutoff},
                )
                qual_rows = r_qual.fetchall()

                # Model failure rate summary
                r_mf = await db.execute(
                    text("""
                        SELECT
                          model_failure_class,
                          COUNT(*) AS n
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND model_failure_class IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY model_failure_class
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                mf_rows = r_mf.fetchall()
        except Exception as exc:
            _log.warning("component.gate_effectiveness_error: %s", exc)
            return {"error": str(exc)}

        def _f(v): return float(v) if v is not None else None

        signal_level_gates = [
            {
                "gate":                    row[0],
                "rejected_count":          int(row[1] or 0),
                "avg_score_at_rejection":  _f(row[2]),
                "avg_conf_at_rejection":   _f(row[3]),
                "note": (
                    "Rejecting high-score signals — review threshold."
                    if row[2] and float(row[2]) >= 70 else
                    "Rejecting borderline signals — expected behavior."
                ),
            }
            for row in rej_rows
        ]

        risk_level_gates = [
            {
                "gate":              row[0],
                "rejection_count":   int(row[1] or 0),
                "rejection_rate_pct": _f(row[2]),
            }
            for row in risk_rows
        ]

        quality_outcome = [
            {
                "quality_category": row[0],
                "count":            int(row[1] or 0),
                "win_rate_pct":     _f(row[2]),
                "avg_pnl_pct":      _f(row[3]),
            }
            for row in qual_rows
        ]

        mf_distribution = [
            {"class": row[0], "count": int(row[1] or 0)}
            for row in mf_rows
        ]

        # Gate quality verdict: if quality_outcome shows EXCELLENT/GOOD signals
        # have materially better WR than WEAK/FAILED, gates are working
        gate_verdict = "INSUFFICIENT_DATA"
        if len(quality_outcome) >= 2:
            best  = next((q for q in quality_outcome if q["quality_category"] in ("EXCELLENT", "GOOD")), None)
            worst = next((q for q in reversed(quality_outcome) if q["quality_category"] in ("WEAK", "FAILED")), None)
            if best and worst and best["win_rate_pct"] and worst["win_rate_pct"]:
                diff = float(best["win_rate_pct"]) - float(worst["win_rate_pct"])
                gate_verdict = (
                    "GATES_EFFECTIVE"   if diff > 15 else
                    "GATES_MODERATE"    if diff > 5  else
                    "GATES_WEAK"
                )

        return {
            "lookback_days":          lookback_days,
            "signal_level_gates":     signal_level_gates,
            "risk_level_gates":       risk_level_gates,
            "quality_tier_outcomes":  quality_outcome,
            "model_failure_distribution": mf_distribution,
            "gate_effectiveness_verdict": gate_verdict,
            "gate_verdict_note": {
                "GATES_EFFECTIVE":    "Quality tiers show >15pp WR difference — gates are protecting capital.",
                "GATES_MODERATE":     "Quality tiers show 5-15pp WR difference — moderate gate value.",
                "GATES_WEAK":         "Quality tiers show <5pp WR difference — gates need review.",
                "INSUFFICIENT_DATA":  "Not enough attributed data to assess gates.",
            }.get(gate_verdict, ""),
            "evaluated_at": datetime.now(UTC).isoformat(),
        }
