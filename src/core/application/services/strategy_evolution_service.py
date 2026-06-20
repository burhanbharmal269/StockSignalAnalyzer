"""StrategyEvolutionService — Phase 20.5 Section 25.

Generates evidence-based strategy tuning recommendations from historical
signal_analytics data. This service NEVER changes anything — it produces
human-readable recommendations for operator review.

CRITICAL: No changes to signals, scoring, thresholds, or filters.
This is observation and recommendation only.

Recommendation types:
  - Component weight candidates (based on discriminative power delta)
  - Regime filter candidates (based on per-regime PF performance)
  - Entry timing improvements (based on stop bucket analysis)
  - Gate threshold candidates (based on quality tier outcome data)
  - Premium decay awareness (option DTE / IV regime patterns)
  - MTF conflict patterns (correlation with loss)
  - Volume pattern insights (volume ratio at winners vs losers)

All recommendations include:
  - supporting_evidence: the data backing the recommendation
  - expected_impact: what improvement is plausible
  - min_trades_before_action: how many trades to validate before acting
  - change_category: maps to ChangeControlService categories
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_MIN_TRADES_THRESHOLD = 30  # minimum trades in a sub-group before generating a recommendation


class StrategyEvolutionService:
    """Evidence-based strategy tuning recommendations. Read-only."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_recommendations(self, lookback_days: int = 30) -> dict:
        """Generate all evolution recommendations from available evidence.

        Returns a list of recommendations sorted by priority (estimated impact).
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

        recs: list[dict] = []
        try:
            async with self._sf() as db:
                recs += await self._regime_recommendations(db, cutoff)
                recs += await self._mtf_conflict_recommendations(db, cutoff)
                recs += await self._stop_timing_recommendations(db, cutoff)
                recs += await self._premium_decay_recommendations(db, cutoff)
                recs += await self._volume_threshold_recommendations(db, cutoff)
                recs += await self._score_bucket_recommendations(db, cutoff)
                recs += await self._failure_reason_recommendations(db, cutoff)
        except Exception as exc:
            _log.warning("evolution.get_recommendations_error: %s", exc)
            return {"error": str(exc)}

        # Sort by priority: CRITICAL → HIGH → MEDIUM → LOW
        _pri = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        recs.sort(key=lambda r: _pri.get(r.get("priority", "LOW"), 3))

        return {
            "lookback_days":      lookback_days,
            "recommendation_count": len(recs),
            "note":               "These are observations only. No action is taken automatically. "
                                  "All changes require passing the ChangeControlService evidence gate.",
            "recommendations":    recs,
            "evaluated_at":       datetime.now(UTC).isoformat(),
        }

    # ── Internal recommendation generators ───────────────────────────────────

    async def _regime_recommendations(self, db, cutoff) -> list[dict]:
        """Identify regimes with PF < 1.0 — potential filter or weight candidates."""
        r = await db.execute(
            text("""
                SELECT
                  regime,
                  COUNT(*) AS n,
                  SUM(CASE WHEN target_hit THEN 1 ELSE 0 END) AS wins,
                  SUM(CASE WHEN stop_hit  THEN 1 ELSE 0 END)  AS losses,
                  ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1) AS win_rate,
                  ROUND(
                    SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                  , 3) AS profit_factor
                FROM signal_analytics
                WHERE was_accepted = true AND outcome IS NOT NULL
                  AND created_at >= :cutoff
                GROUP BY regime
                HAVING COUNT(*) >= :min_n
                ORDER BY profit_factor ASC NULLS LAST
            """),
            {"cutoff": cutoff, "min_n": _MIN_TRADES_THRESHOLD},
        )
        rows = r.fetchall()
        recs = []
        for row in rows:
            regime = row[0]
            n = int(row[1] or 0)
            wr = float(row[4] or 0)
            pf = float(row[5] or 0) if row[5] else None
            if pf is None or pf >= 1.0:
                continue
            priority = "CRITICAL" if pf < 0.70 else "HIGH" if pf < 0.85 else "MEDIUM"
            recs.append({
                "id":                   f"REGIME_{regime}",
                "priority":             priority,
                "category":             "REGIME_THRESHOLD",
                "title":                f"{regime} regime underperforming",
                "recommendation":       (
                    f"{regime} regime has PF {pf:.2f} and win rate {wr:.1f}% over {n} trades. "
                    f"Consider raising the minimum signal score gate for this regime, "
                    f"or restricting to higher-conviction setups only."
                ),
                "supporting_evidence":  f"PF={pf:.2f}, WR={wr:.1f}%, n={n} trades in {lookback_days}d",
                "expected_impact":      f"Filtering low-score signals in {regime} could improve system PF by 0.05-0.15.",
                "min_trades_before_action": 100,
                "change_category":      "REGIME_THRESHOLD",
            })
        return recs

    async def _mtf_conflict_recommendations(self, db, cutoff) -> list[dict]:
        """Flag if MTF-conflicted trades significantly underperform aligned trades."""
        r = await db.execute(
            text("""
                SELECT
                  CASE
                    WHEN mtf_alignment = 'NEUTRAL' OR mtf_alignment IS NULL THEN 'NEUTRAL'
                    WHEN (direction = 'CE' AND mtf_alignment = 'BULLISH')
                      OR (direction = 'PE' AND mtf_alignment = 'BEARISH') THEN 'ALIGNED'
                    ELSE 'CONFLICT'
                  END AS mtf_group,
                  COUNT(*) AS n,
                  ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1) AS win_rate,
                  ROUND(
                    SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                  , 3) AS profit_factor
                FROM signal_analytics
                WHERE was_accepted = true AND outcome IS NOT NULL
                  AND created_at >= :cutoff
                GROUP BY mtf_group
                HAVING COUNT(*) >= :min_n
            """),
            {"cutoff": cutoff, "min_n": _MIN_TRADES_THRESHOLD},
        )
        rows = {row[0]: row for row in r.fetchall()}

        recs = []
        aligned  = rows.get("ALIGNED")
        conflict = rows.get("CONFLICT")
        if aligned and conflict:
            aligned_pf  = float(aligned[3] or 0) if aligned[3] else None
            conflict_pf = float(conflict[3] or 0) if conflict[3] else None
            conflict_wr = float(conflict[2] or 0)
            conflict_n  = int(conflict[1] or 0)

            if aligned_pf and conflict_pf and aligned_pf - conflict_pf > 0.15:
                recs.append({
                    "id":                   "MTF_CONFLICT_FILTER",
                    "priority":             "HIGH" if conflict_pf < 0.85 else "MEDIUM",
                    "category":             "COMPONENT_PARAMETER",
                    "title":                "MTF-conflict trades underperforming aligned trades",
                    "recommendation":       (
                        f"MTF-aligned trades: PF {aligned_pf:.2f}. "
                        f"MTF-conflict trades: PF {conflict_pf:.2f} ({conflict_n} trades, WR {conflict_wr:.1f}%). "
                        f"MTF conflict trades have {aligned_pf - conflict_pf:.2f} lower PF. "
                        f"Consider increasing score penalty for MTF conflicts or requiring stricter "
                        f"component alignment when MTF is conflicted."
                    ),
                    "supporting_evidence":  (
                        f"Aligned PF={aligned_pf:.2f} vs Conflict PF={conflict_pf:.2f} "
                        f"over {lookback_days}d"
                    ),
                    "expected_impact":      (
                        f"Filtering MTF-conflict trades could improve system PF by "
                        f"{(aligned_pf - conflict_pf) * conflict_n / max(int(aligned[1] or 1), 1):.2f}."
                    ),
                    "min_trades_before_action": 100,
                    "change_category":      "COMPONENT_PARAMETER",
                })
        return recs

    async def _stop_timing_recommendations(self, db, cutoff) -> list[dict]:
        """Detect high IMMEDIATE stop rate, suggesting entry or stop quality issues."""
        r = await db.execute(
            text("""
                SELECT
                  COALESCE(stop_timing_bucket,
                    CASE WHEN time_to_stop_minutes <= 15 THEN 'IMMEDIATE'
                         WHEN time_to_stop_minutes <= 30 THEN 'EARLY'
                         WHEN time_to_stop_minutes <= 60 THEN 'MEDIUM'
                         ELSE 'LATE' END)  AS bucket,
                  COUNT(*) AS n
                FROM signal_analytics
                WHERE stop_hit = true AND was_accepted = true
                  AND time_to_stop_minutes IS NOT NULL
                  AND created_at >= :cutoff
                GROUP BY bucket
            """),
            {"cutoff": cutoff},
        )
        buckets = {row[0]: int(row[1] or 0) for row in r.fetchall()}
        total = sum(buckets.values())

        recs = []
        if total >= _MIN_TRADES_THRESHOLD:
            imm_n = buckets.get("IMMEDIATE", 0)
            imm_pct = imm_n / total * 100
            if imm_pct > 40:
                recs.append({
                    "id":                   "STOP_IMMEDIATE_HIGH",
                    "priority":             "HIGH",
                    "category":             "RISK_PARAMETER",
                    "title":                f"{imm_pct:.0f}% of stops hit within 15 minutes",
                    "recommendation":       (
                        f"{imm_pct:.0f}% of losing trades stopped out within 15 minutes ({imm_n}/{total}). "
                        f"This indicates either (a) entries are late into already-extended moves, "
                        f"(b) stop loss % is too tight for normal option noise, "
                        f"or (c) signals are triggered at poor price locations. "
                        f"Investigate average entry timing and compare to candle structure."
                    ),
                    "supporting_evidence":  f"{imm_n}/{total} stops hit in ≤15 min ({imm_pct:.1f}%)",
                    "expected_impact":      "Widening stop by 5pp or improving entry filters could reduce IMMEDIATE% by 10-15pp.",
                    "min_trades_before_action": 50,
                    "change_category":      "RISK_PARAMETER",
                })
            elif imm_pct > 30:
                recs.append({
                    "id":                   "STOP_IMMEDIATE_ELEVATED",
                    "priority":             "MEDIUM",
                    "category":             "RISK_PARAMETER",
                    "title":                f"{imm_pct:.0f}% IMMEDIATE stops — elevated but not critical",
                    "recommendation":       (
                        f"{imm_pct:.0f}% of stops hit within 15 min. Monitor this metric. "
                        f"If it exceeds 40%, review entry quality and stop sizing."
                    ),
                    "supporting_evidence":  f"{imm_n}/{total} IMMEDIATE stops",
                    "expected_impact":      "Monitor only — no action recommended at this level.",
                    "min_trades_before_action": 100,
                    "change_category":      "RISK_PARAMETER",
                })
        return recs

    async def _premium_decay_recommendations(self, db, cutoff) -> list[dict]:
        """Detect if low-DTE signals are disproportionately losing due to decay."""
        r = await db.execute(
            text("""
                SELECT
                  CASE WHEN dte <= 2 THEN 'LOW_DTE' ELSE 'NORMAL_DTE' END AS dte_group,
                  COUNT(*) AS n,
                  ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1) AS win_rate,
                  ROUND(AVG(COALESCE(pnl_pct, current_return_pct))*100, 4) AS avg_pnl
                FROM signal_analytics
                WHERE was_accepted = true AND outcome IS NOT NULL
                  AND dte IS NOT NULL
                  AND created_at >= :cutoff
                GROUP BY dte_group
                HAVING COUNT(*) >= :min_n
            """),
            {"cutoff": cutoff, "min_n": _MIN_TRADES_THRESHOLD},
        )
        rows = {row[0]: row for row in r.fetchall()}

        recs = []
        low_dte    = rows.get("LOW_DTE")
        normal_dte = rows.get("NORMAL_DTE")
        if low_dte and normal_dte:
            low_pnl  = float(low_dte[3] or 0) if low_dte[3] else None
            norm_pnl = float(normal_dte[3] or 0) if normal_dte[3] else None
            low_wr   = float(low_dte[2] or 0)
            norm_wr  = float(normal_dte[2] or 0)
            low_n    = int(low_dte[1] or 0)

            if low_pnl is not None and norm_pnl is not None and norm_pnl - low_pnl > 0.5:
                recs.append({
                    "id":                   "PREMIUM_DECAY_DTE",
                    "priority":             "HIGH" if low_wr < norm_wr - 10 else "MEDIUM",
                    "category":             "COMPONENT_PARAMETER",
                    "title":                f"Low DTE (≤2) signals underperforming",
                    "recommendation":       (
                        f"DTE ≤2 signals: WR {low_wr:.1f}%, avg PnL {low_pnl:.2f}%. "
                        f"DTE >2 signals: WR {norm_wr:.1f}%, avg PnL {norm_pnl:.2f}%. "
                        f"Premium decay on near-expiry options is consuming {norm_pnl - low_pnl:.2f}pp "
                        f"of average return. Consider raising minimum DTE or requiring higher score "
                        f"threshold for ≤2 DTE trades ({low_n} trades affected)."
                    ),
                    "supporting_evidence":  (
                        f"Low DTE n={low_n}, WR={low_wr:.1f}% vs Normal DTE WR={norm_wr:.1f}%"
                    ),
                    "expected_impact":      f"Filtering DTE ≤2 could improve avg pnl by ~{norm_pnl - low_pnl:.2f}pp.",
                    "min_trades_before_action": 100,
                    "change_category":      "COMPONENT_PARAMETER",
                })
        return recs

    async def _volume_threshold_recommendations(self, db, cutoff) -> list[dict]:
        """Check if low-volume signals underperform significantly."""
        r = await db.execute(
            text("""
                SELECT
                  CASE WHEN volume_ratio_at_signal < 1.0 THEN 'LOW_VOLUME'
                       WHEN volume_ratio_at_signal < 1.5 THEN 'MED_VOLUME'
                       ELSE 'HIGH_VOLUME' END AS vol_group,
                  COUNT(*) AS n,
                  ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1) AS win_rate
                FROM signal_analytics
                WHERE was_accepted = true AND outcome IS NOT NULL
                  AND volume_ratio_at_signal IS NOT NULL
                  AND created_at >= :cutoff
                GROUP BY vol_group
                HAVING COUNT(*) >= :min_n
            """),
            {"cutoff": cutoff, "min_n": _MIN_TRADES_THRESHOLD},
        )
        rows = {row[0]: row for row in r.fetchall()}

        recs = []
        low_vol  = rows.get("LOW_VOLUME")
        high_vol = rows.get("HIGH_VOLUME")
        if low_vol and high_vol:
            low_wr   = float(low_vol[2] or 0)
            high_wr  = float(high_vol[2] or 0)
            low_n    = int(low_vol[1] or 0)
            if high_wr - low_wr > 12:
                recs.append({
                    "id":                   "LOW_VOLUME_UNDERPERFORM",
                    "priority":             "MEDIUM",
                    "category":             "GATE_THRESHOLD",
                    "title":                f"Low-volume signals underperforming by {high_wr - low_wr:.0f}pp WR",
                    "recommendation":       (
                        f"Signals with volume ratio <1.0x have {low_wr:.1f}% WR vs "
                        f"{high_wr:.1f}% for volume ≥1.5x ({low_n} trades). "
                        f"Consider raising the minimum volume ratio gate threshold or "
                        f"applying a volume penalty to the confidence score."
                    ),
                    "supporting_evidence":  f"Low vol WR={low_wr:.1f}% vs High vol WR={high_wr:.1f}%",
                    "expected_impact":      f"~{high_wr - low_wr:.0f}pp WR improvement if low-volume signals are filtered.",
                    "min_trades_before_action": 100,
                    "change_category":      "GATE_THRESHOLD",
                })
        return recs

    async def _score_bucket_recommendations(self, db, cutoff) -> list[dict]:
        """Check score bucket monotonicity — lower buckets should not outperform higher."""
        r = await db.execute(
            text("""
                SELECT
                  CASE WHEN adjusted_score >= 80 THEN '80+'
                       WHEN adjusted_score >= 70 THEN '70-79'
                       WHEN adjusted_score >= 65 THEN '65-69'
                       ELSE '60-64' END              AS bucket,
                  COUNT(*)                            AS n,
                  ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1) AS win_rate
                FROM signal_analytics
                WHERE was_accepted = true AND outcome IS NOT NULL
                  AND adjusted_score IS NOT NULL
                  AND created_at >= :cutoff
                GROUP BY bucket
                HAVING COUNT(*) >= :min_n
                ORDER BY bucket DESC
            """),
            {"cutoff": cutoff, "min_n": _MIN_TRADES_THRESHOLD},
        )
        rows = list(r.fetchall())

        recs = []
        # Check monotonicity: each higher bucket should have >= lower bucket WR
        bucket_wr = {row[0]: float(row[2] or 0) for row in rows}
        bucket_n  = {row[0]: int(row[1] or 0) for row in rows}
        ordered = ["80+", "70-79", "65-69", "60-64"]

        for i in range(len(ordered) - 1):
            hi = ordered[i]
            lo = ordered[i + 1]
            if hi in bucket_wr and lo in bucket_wr:
                if bucket_wr[lo] > bucket_wr[hi] + 3.0:  # +3pp tolerance
                    recs.append({
                        "id":                   f"SCORE_MONOTONICITY_{hi}_{lo}",
                        "priority":             "HIGH",
                        "category":             "SCORING_WEIGHT",
                        "title":                f"Score monotonicity violation: {lo} bucket beating {hi} bucket",
                        "recommendation":       (
                            f"Signals with score {lo} have {bucket_wr[lo]:.1f}% WR vs "
                            f"{bucket_wr[hi]:.1f}% for score {hi}. Score is not predicting outcome. "
                            f"Review component weights — a weight may be rewarding noise. "
                            f"This is the strongest signal to investigate component calibration."
                        ),
                        "supporting_evidence":  (
                            f"{lo}: WR={bucket_wr[lo]:.1f}% n={bucket_n.get(lo,0)} | "
                            f"{hi}: WR={bucket_wr[hi]:.1f}% n={bucket_n.get(hi,0)}"
                        ),
                        "expected_impact":      "Fixing score monotonicity should materially improve signal quality.",
                        "min_trades_before_action": 200,
                        "change_category":      "SCORING_WEIGHT",
                    })
        return recs

    async def _failure_reason_recommendations(self, db, cutoff) -> list[dict]:
        """Generate text insights from the most common failure reasons."""
        r = await db.execute(
            text("""
                SELECT failure_reason, COUNT(*) AS n,
                       ROUND(AVG(failure_confidence), 3) AS avg_conf
                FROM signal_analytics
                WHERE stop_hit = true AND failure_reason IS NOT NULL
                  AND failure_reason != 'UNKNOWN'
                  AND created_at >= :cutoff
                GROUP BY failure_reason
                HAVING COUNT(*) >= :min_n
                ORDER BY n DESC
                LIMIT 5
            """),
            {"cutoff": cutoff, "min_n": max(_MIN_TRADES_THRESHOLD // 3, 5)},
        )
        rows = r.fetchall()

        r_total = await db.execute(
            text("""
                SELECT COUNT(*) FROM signal_analytics
                WHERE stop_hit = true AND was_accepted = true AND created_at >= :cutoff
            """),
            {"cutoff": cutoff},
        )
        total_losses = int((r_total.fetchone() or [0])[0])

        recs = []
        for row in rows:
            reason = row[0]
            n = int(row[1] or 0)
            conf = float(row[2] or 0)
            pct = n / total_losses * 100 if total_losses else 0

            _advice = {
                "VWAP_FAILURE":           "Review VWAP component weight. Consider requiring price to be above/below VWAP by a minimum margin.",
                "TREND_FAILURE":          "ADX < 20 at entry correlated with TREND_FAILURE. Consider raising minimum ADX gate.",
                "MTF_FAILURE":            "MTF-conflict entries are flagged. Consider score penalty for MTF conflicts.",
                "STOP_TOO_TIGHT":         "Immediate stops suggest too-tight SL%. Consider widening stop by 3-5pp for higher-IV environments.",
                "REGIME_SHIFT":           "SIDEWAYS regime losses concentrated here. Consider reducing lot size in SIDEWAYS regime.",
                "PREMIUM_DECAY":          "Near-expiry (DTE ≤2) options losing to theta. Consider minimum DTE gate of 3.",
                "LATE_ENTRY":             "Very fast stopouts indicate late entry into moves. Review entry candle criteria.",
                "VOLUME_FAILURE":         "Volume faded after entry. Consider requiring sustained volume confirmation before entry.",
                "OI_FAILURE":             "OI component unavailable or weak. For index signals, verify OI source.",
                "IV_CRUSH":               "IV falling post-entry. Consider tracking IV rank and avoiding low-IV-rank environments.",
                "OPTION_CHAIN_FAILURE":   "Option chain signals weakened after entry. Consider rechecking OI walls before entry confirmation.",
            }.get(reason, f"Investigate {reason} pattern — {pct:.1f}% of losses attributed here.")

            recs.append({
                "id":                   f"FAILURE_{reason}",
                "priority":             "HIGH" if pct > 25 else "MEDIUM" if pct > 12 else "LOW",
                "category":             "COMPONENT_PARAMETER",
                "title":                f"{reason}: {pct:.1f}% of losses ({n} trades)",
                "recommendation":       _advice,
                "supporting_evidence":  (
                    f"{n}/{total_losses} losses attributed to {reason} "
                    f"(avg confidence: {conf:.0%})"
                ),
                "expected_impact":      f"Addressing {reason} could reduce total losses by up to {pct:.0f}%.",
                "min_trades_before_action": 100,
                "change_category":      "COMPONENT_PARAMETER",
            })
        return recs
