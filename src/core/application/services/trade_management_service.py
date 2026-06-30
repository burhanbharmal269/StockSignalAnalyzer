"""Trade Management Intelligence (TMI) Service.

Separates signal outcome (did the entry thesis play out?)
from position outcome (what did the trader actually capture?).

Core metrics per signal:
  capture_ratio       — final_return / MFE  (0-1; how much of peak profit was kept)
  opportunity_lost    — MFE - final_return   (profit available but not taken)
  profit_surrender    — MFE - max(0, final)  (positive gains given back after peak)
  trade_classification — one of 6 buckets explaining WHY the trade ended as it did

Trade classifications (in priority order):
  BAD_ENTRY               — MFE < 5%: stock never moved in the right direction
  GOOD_ENTRY_REGIME_REVERSAL — MFE >= 20%, profit_surrender >= 15%: big gain, then reversal
  GOOD_ENTRY_POOR_EXIT    — MFE >= 15%, capture < 35%: had profit, didn't exit
  GOOD_ENTRY_PREMIUM_DECAY — MFE > 5%, final < -5%: theta/IV crush killed the trade
  GOOD_ENTRY_UNREALISTIC_TARGET — 5% <= MFE < 50%, target not hit: target too high for day
  GOOD_ENTRY_CAPTURED     — capture >= 50% and MFE >= 10%: success

All reads are from existing signal_analytics + option_chain_snapshots.
No strategy logic is touched.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

_log = logging.getLogger(__name__)

# ── Classification thresholds ─────────────────────────────────────────────────
_BAD_ENTRY_MFE_MAX       = 5.0    # below this = entry was wrong
_REGIME_REV_MFE_MIN      = 20.0   # MFE needed for regime-reversal label
_REGIME_REV_SURRENDER_MIN = 15.0  # profit given back for regime-reversal label
_POOR_EXIT_MFE_MIN       = 15.0   # MFE needed to be labelled "poor exit"
_POOR_EXIT_CAPTURE_MAX   = 0.35   # capture ratio below this = poor exit
_PREMIUM_DECAY_MFE_MIN   = 5.0    # entry was OK but theta crushed
_PREMIUM_DECAY_FINAL_MAX = -5.0   # final return negative enough to be "decay"
_UNREALISTIC_MFE_MIN     = 5.0    # had some move, just target was too far
_CAPTURED_CAPTURE_MIN    = 0.50   # captured at least half the available profit
_CAPTURED_MFE_MIN        = 10.0   # only call it "captured" if MFE was meaningful

# Profit surrender = MFE - final_return (gains given back after peak)
# Classified only for settled signals (outcome != 'OPEN')


class TradeManagementService:
    """Compute and store Trade Management Intelligence metrics."""

    def __init__(self, session_factory: "async_sessionmaker") -> None:
        self._sf = session_factory

    # ── Public API ─────────────────────────────────────────────────────────────

    async def classify_and_update(self, analytics_id: int) -> None:
        """Compute TMI metrics for one settled signal and persist them."""
        record = await self._fetch_record(analytics_id)
        if not record:
            return
        metrics = self._compute_metrics(record)
        if metrics:
            await self._persist_tmi(analytics_id, metrics)

    async def run_classification_pass(self) -> dict:
        """Batch: classify all settled signals that haven't been classified yet."""
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT id, outcome, mfe_pct, mae_pct, current_return_pct,
                       time_in_profit_minutes, time_in_loss_minutes,
                       option_entry, option_target
                FROM signal_analytics
                WHERE was_accepted = true
                  AND outcome IN ('WIN','LOSS','EXPIRED','PARTIAL')
                  AND trade_classification IS NULL
                  AND mfe_pct IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 500
            """))
            rows = [dict(r._mapping) for r in result.fetchall()]

        updated = errors = 0
        for row in rows:
            try:
                metrics = self._compute_metrics(row)
                if metrics:
                    await self._persist_tmi(row["id"], metrics)
                    updated += 1
            except Exception as exc:
                errors += 1
                _log.debug("tmi.classify_error id=%s: %s", row["id"], exc)

        _log.info("tmi.classification_pass updated=%d errors=%d", updated, errors)
        return {"updated": updated, "errors": errors}

    async def record_position_close(
        self,
        analytics_id: int,
        exit_price: float,
        closed_at: datetime | None = None,
    ) -> dict:
        """Record the actual position exit price (trader-supplied, separate from signal outcome).

        Computes position_return_pct from option_entry and the supplied exit_price.
        """
        async with self._sf() as db:
            rec = await db.execute(text("""
                SELECT id, option_entry, mfe_pct
                FROM signal_analytics WHERE id = :id
            """), {"id": analytics_id})
            row = rec.fetchone()
            if not row:
                return {"error": f"Signal {analytics_id} not found"}

            opt_entry = float(row.option_entry) if row.option_entry else None
            position_return_pct = None
            if opt_entry and opt_entry > 0:
                position_return_pct = round((exit_price - opt_entry) / opt_entry * 100, 4)

            position_closed_at = closed_at or datetime.now(UTC)

            # Recompute capture ratio against actual position return
            mfe = float(row.mfe_pct) if row.mfe_pct else None
            capture_ratio = None
            if mfe and mfe > 0 and position_return_pct is not None:
                capture_ratio = round(position_return_pct / mfe, 4)

            await db.execute(text("""
                UPDATE signal_analytics SET
                    position_exit_price = :exit_price,
                    position_closed_at  = :closed_at,
                    position_return_pct = :pos_ret,
                    capture_ratio       = COALESCE(:capture_ratio, capture_ratio)
                WHERE id = :id
            """), {
                "exit_price":    exit_price,
                "closed_at":     position_closed_at,
                "pos_ret":       position_return_pct,
                "capture_ratio": capture_ratio,
                "id":            analytics_id,
            })
            await db.commit()

        return {
            "analytics_id":       analytics_id,
            "position_exit_price": exit_price,
            "position_return_pct": position_return_pct,
            "capture_ratio":       capture_ratio,
        }

    async def get_summary(self, days: int = 30) -> dict:
        """Overall TMI dashboard: aggregated metrics across all settled signals."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE was_accepted) AS total_accepted,
                    COUNT(*) FILTER (WHERE mfe_pct IS NOT NULL) AS with_mfe,
                    COUNT(*) FILTER (WHERE mfe_pct >= 5)   AS positive_entry,
                    COUNT(*) FILTER (WHERE mfe_pct >= 10)  AS tier_10,
                    COUNT(*) FILTER (WHERE mfe_pct >= 20)  AS tier_20,
                    COUNT(*) FILTER (WHERE mfe_pct >= 30)  AS tier_30,
                    COUNT(*) FILTER (WHERE mfe_pct >= 40)  AS tier_40,
                    COUNT(*) FILTER (WHERE mfe_pct >= 50)  AS tier_50,
                    ROUND(AVG(mfe_pct)::numeric, 2)                         AS avg_mfe,
                    ROUND(AVG(capture_ratio)::numeric, 4)                   AS avg_capture_ratio,
                    ROUND(AVG(profit_surrender_pct)::numeric, 2)            AS avg_profit_surrendered,
                    ROUND(AVG(opportunity_lost_pct)::numeric, 2)            AS avg_opportunity_lost,
                    COUNT(*) FILTER (WHERE trade_classification = 'BAD_ENTRY') AS bad_entry,
                    COUNT(*) FILTER (WHERE trade_classification = 'GOOD_ENTRY_POOR_EXIT') AS poor_exit,
                    COUNT(*) FILTER (WHERE trade_classification = 'GOOD_ENTRY_UNREALISTIC_TARGET') AS unrealistic_target,
                    COUNT(*) FILTER (WHERE trade_classification = 'GOOD_ENTRY_PREMIUM_DECAY') AS premium_decay,
                    COUNT(*) FILTER (WHERE trade_classification = 'GOOD_ENTRY_REGIME_REVERSAL') AS regime_reversal,
                    COUNT(*) FILTER (WHERE trade_classification = 'GOOD_ENTRY_CAPTURED') AS captured
                FROM signal_analytics
                WHERE was_accepted = true
                  AND created_at >= :cutoff
            """), {"cutoff": cutoff})
            row = dict(r.fetchone()._mapping)

        total = row["total_accepted"] or 1
        with_mfe = row["with_mfe"] or 0

        return {
            "period_days":          days,
            "total_accepted":       int(row["total_accepted"] or 0),
            "signals_with_mfe":     with_mfe,
            "positive_entry_count": int(row["positive_entry"] or 0),
            "positive_entry_rate":  round((row["positive_entry"] or 0) / max(with_mfe, 1) * 100, 1),
            "avg_mfe_pct":          float(row["avg_mfe"] or 0),
            "avg_capture_ratio":    float(row["avg_capture_ratio"] or 0),
            "avg_profit_surrendered_pct": float(row["avg_profit_surrendered"] or 0),
            "avg_opportunity_lost_pct":   float(row["avg_opportunity_lost"] or 0),
            "profit_tiers": {
                "mfe_gte_10pct": int(row["tier_10"] or 0),
                "mfe_gte_20pct": int(row["tier_20"] or 0),
                "mfe_gte_30pct": int(row["tier_30"] or 0),
                "mfe_gte_40pct": int(row["tier_40"] or 0),
                "mfe_gte_50pct": int(row["tier_50"] or 0),
            },
            "classifications": {
                "BAD_ENTRY":                    int(row["bad_entry"] or 0),
                "GOOD_ENTRY_POOR_EXIT":         int(row["poor_exit"] or 0),
                "GOOD_ENTRY_UNREALISTIC_TARGET": int(row["unrealistic_target"] or 0),
                "GOOD_ENTRY_PREMIUM_DECAY":     int(row["premium_decay"] or 0),
                "GOOD_ENTRY_REGIME_REVERSAL":   int(row["regime_reversal"] or 0),
                "GOOD_ENTRY_CAPTURED":          int(row["captured"] or 0),
            },
        }

    async def get_profit_tier_details(self, days: int = 30) -> list[dict]:
        """Per-signal MFE breakdown for waterfall chart."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT ticker, direction, regime, mfe_pct, mae_pct,
                       current_return_pct, capture_ratio, profit_surrender_pct,
                       trade_classification, option_symbol,
                       created_at AT TIME ZONE 'Asia/Kolkata' AS created_ist
                FROM signal_analytics
                WHERE was_accepted = true
                  AND mfe_pct IS NOT NULL
                  AND created_at >= :cutoff
                ORDER BY mfe_pct DESC
                LIMIT 200
            """), {"cutoff": cutoff})
            return [dict(row._mapping) for row in r.fetchall()]

    async def get_regime_reversal_analysis(self, days: int = 30) -> list[dict]:
        """Which regimes had big gains then gave them back."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    regime,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE mfe_pct >= 10) AS had_positive,
                    ROUND(AVG(mfe_pct)::numeric, 2) AS avg_mfe,
                    ROUND(AVG(profit_surrender_pct)::numeric, 2) AS avg_surrender,
                    ROUND(AVG(capture_ratio)::numeric, 3) AS avg_capture,
                    COUNT(*) FILTER (WHERE trade_classification = 'GOOD_ENTRY_REGIME_REVERSAL') AS reversals
                FROM signal_analytics
                WHERE was_accepted = true
                  AND mfe_pct IS NOT NULL
                  AND created_at >= :cutoff
                GROUP BY regime
                ORDER BY avg_surrender DESC NULLS LAST
            """), {"cutoff": cutoff})
            return [dict(row._mapping) for row in r.fetchall()]

    async def get_capture_ratio_distribution(self, days: int = 30) -> dict:
        """Bucketed capture ratio — shows where profit is being lost."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE capture_ratio < 0)           AS negative,
                    COUNT(*) FILTER (WHERE capture_ratio >= 0 AND capture_ratio < 0.25)  AS c_0_25,
                    COUNT(*) FILTER (WHERE capture_ratio >= 0.25 AND capture_ratio < 0.50) AS c_25_50,
                    COUNT(*) FILTER (WHERE capture_ratio >= 0.50 AND capture_ratio < 0.75) AS c_50_75,
                    COUNT(*) FILTER (WHERE capture_ratio >= 0.75 AND capture_ratio < 1.0)  AS c_75_100,
                    COUNT(*) FILTER (WHERE capture_ratio >= 1.0)        AS full_capture
                FROM signal_analytics
                WHERE was_accepted = true
                  AND capture_ratio IS NOT NULL
                  AND created_at >= :cutoff
            """), {"cutoff": cutoff})
            row = dict(r.fetchone()._mapping)

        return {
            "below_zero":      int(row["negative"]   or 0),
            "zero_to_25pct":   int(row["c_0_25"]     or 0),
            "25_to_50pct":     int(row["c_25_50"]    or 0),
            "50_to_75pct":     int(row["c_50_75"]    or 0),
            "75_to_100pct":    int(row["c_75_100"]   or 0),
            "full_or_above":   int(row["full_capture"] or 0),
        }

    async def generate_weekly_report(self, lookback_days: int = 7) -> dict:
        """Generate and persist the weekly TMI report."""
        # First update classifications for any settled signals
        await self.run_classification_pass()

        summary    = await self.get_summary(days=lookback_days)
        regimes    = await self.get_regime_reversal_analysis(days=lookback_days)
        cap_dist   = await self.get_capture_ratio_distribution(days=lookback_days)
        tier_detail = await self.get_profit_tier_details(days=lookback_days)

        # Profit surrender analysis
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE profit_surrender_pct > 5)  AS surrendered_5pct,
                    COUNT(*) FILTER (WHERE profit_surrender_pct > 10) AS surrendered_10pct,
                    COUNT(*) FILTER (WHERE profit_surrender_pct > 20) AS surrendered_20pct,
                    ROUND(AVG(profit_surrender_pct) FILTER (WHERE profit_surrender_pct > 0)::numeric, 2) AS avg_surrender_nonzero
                FROM signal_analytics
                WHERE was_accepted = true
                  AND profit_surrender_pct IS NOT NULL
                  AND created_at >= :cutoff
            """), {"cutoff": cutoff})
            surrender_row = dict(r.fetchone()._mapping)

        report = {
            "week_ending":        date.today().isoformat(),
            "lookback_days":      lookback_days,
            "generated_at":       datetime.now(UTC).isoformat(),
            **summary,
            "capture_ratio_distribution": cap_dist,
            "profit_surrender_analysis": {
                "signals_surrendered_5pct_plus":  int(surrender_row["surrendered_5pct"]  or 0),
                "signals_surrendered_10pct_plus": int(surrender_row["surrendered_10pct"] or 0),
                "signals_surrendered_20pct_plus": int(surrender_row["surrendered_20pct"] or 0),
                "avg_surrender_nonzero_pct":      float(surrender_row["avg_surrender_nonzero"] or 0),
            },
            "regime_analysis":   regimes,
            "top_signals":       tier_detail[:20],
            "interpretation": self._interpret(summary, regimes),
        }

        # Persist
        async with self._sf() as db:
            await db.execute(text("""
                INSERT INTO tmi_weekly_reports
                    (week_ending, lookback_days, total_signals, positive_mfe,
                     avg_mfe_pct, avg_capture_ratio, avg_profit_surrendered,
                     tier_10pct, tier_20pct, tier_30pct, tier_40pct, tier_50pct,
                     classifications_json, regime_analysis_json, full_report_json)
                VALUES
                    (:we, :ld, :ts, :pm, :am, :ac, :aps,
                     :t10, :t20, :t30, :t40, :t50,
                     :cj, :rj, :fj)
            """), {
                "we":  date.today(),
                "ld":  lookback_days,
                "ts":  summary["total_accepted"],
                "pm":  summary["positive_entry_count"],
                "am":  summary["avg_mfe_pct"],
                "ac":  summary["avg_capture_ratio"],
                "aps": summary["avg_profit_surrendered_pct"],
                "t10": summary["profit_tiers"]["mfe_gte_10pct"],
                "t20": summary["profit_tiers"]["mfe_gte_20pct"],
                "t30": summary["profit_tiers"]["mfe_gte_30pct"],
                "t40": summary["profit_tiers"]["mfe_gte_40pct"],
                "t50": summary["profit_tiers"]["mfe_gte_50pct"],
                "cj":  json.dumps(summary["classifications"]),
                "rj":  json.dumps(regimes),
                "fj":  json.dumps(report, default=str),
            })
            await db.commit()

        return report

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _fetch_record(self, analytics_id: int) -> dict | None:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT id, outcome, mfe_pct, mae_pct, current_return_pct,
                       time_in_profit_minutes, time_in_loss_minutes,
                       option_entry, option_target, position_return_pct
                FROM signal_analytics WHERE id = :id
            """), {"id": analytics_id})
            row = r.fetchone()
            return dict(row._mapping) if row else None

    @staticmethod
    def _compute_metrics(record: dict) -> dict | None:
        mfe = record.get("mfe_pct")
        if mfe is None:
            return None

        mfe   = float(mfe)
        mae   = float(record.get("mae_pct") or 0)
        # Use position_return_pct if available (trader-supplied actual exit)
        # otherwise fall back to current_return_pct (last known snapshot)
        pos_ret = record.get("position_return_pct")
        cur_ret = record.get("current_return_pct")
        final   = float(pos_ret if pos_ret is not None else (cur_ret or 0))

        # Capture ratio: how much of peak profit was kept
        # Positive MFE only — capturing a loss is not meaningful
        if mfe > 0:
            capture_ratio = round(final / mfe, 4)
        else:
            capture_ratio = 0.0

        # Opportunity lost: MFE that was never turned into realized profit
        # = MFE - max(0, final)  (you only "lose" opportunity on the upside)
        opportunity_lost = round(mfe - max(0.0, final), 4)

        # Profit surrender: peak profit GIVEN BACK (not just uncaptured)
        # = MFE - final  (if final < MFE, you surrendered the difference)
        # Only positive when you had a gain that was then reduced/reversed
        profit_surrender = round(max(0.0, mfe - final), 4)

        classification = TradeManagementService._classify(
            mfe=mfe,
            mae=mae,
            final=final,
            capture_ratio=capture_ratio,
            profit_surrender=profit_surrender,
            time_in_profit=float(record.get("time_in_profit_minutes") or 0),
            time_in_loss=float(record.get("time_in_loss_minutes") or 0),
            outcome=str(record.get("outcome") or "OPEN"),
        )

        return {
            "capture_ratio":        capture_ratio,
            "opportunity_lost_pct": opportunity_lost,
            "profit_surrender_pct": profit_surrender,
            "trade_classification": classification,
        }

    @staticmethod
    def _classify(
        mfe: float,
        mae: float,
        final: float,
        capture_ratio: float,
        profit_surrender: float,
        time_in_profit: float,
        time_in_loss: float,
        outcome: str,
    ) -> str:
        # 1. Bad entry: stock never moved favorably
        if mfe < _BAD_ENTRY_MFE_MAX:
            return "BAD_ENTRY"

        # 2. Regime reversal: had big gain, then big reversal ate it
        if mfe >= _REGIME_REV_MFE_MIN and profit_surrender >= _REGIME_REV_SURRENDER_MIN:
            return "GOOD_ENTRY_REGIME_REVERSAL"

        # 3. Poor exit: had good profit window but didn't take it
        if mfe >= _POOR_EXIT_MFE_MIN and capture_ratio < _POOR_EXIT_CAPTURE_MAX:
            return "GOOD_ENTRY_POOR_EXIT"

        # 4. Premium decay: option lost to theta even with some favorable move
        if mfe >= _PREMIUM_DECAY_MFE_MIN and final < _PREMIUM_DECAY_FINAL_MAX:
            return "GOOD_ENTRY_PREMIUM_DECAY"

        # 5. Unrealistic target: had a move but target was too far for the day
        if mfe >= _UNREALISTIC_MFE_MIN and mfe < 50.0 and outcome not in ("WIN",):
            return "GOOD_ENTRY_UNREALISTIC_TARGET"

        # 6. Captured: successfully took meaningful profit
        if mfe >= _CAPTURED_MFE_MIN and capture_ratio >= _CAPTURED_CAPTURE_MIN:
            return "GOOD_ENTRY_CAPTURED"

        return "GOOD_ENTRY_UNREALISTIC_TARGET"

    async def _persist_tmi(self, analytics_id: int, metrics: dict) -> None:
        async with self._sf() as db:
            await db.execute(text("""
                UPDATE signal_analytics SET
                    capture_ratio        = :capture_ratio,
                    opportunity_lost_pct = :opportunity_lost_pct,
                    profit_surrender_pct = :profit_surrender_pct,
                    trade_classification = :trade_classification
                WHERE id = :id
            """), {**metrics, "id": analytics_id})
            await db.commit()

    @staticmethod
    def _interpret(summary: dict, regimes: list[dict]) -> list[str]:
        """Generate plain-English observations from the metrics."""
        obs: list[str] = []
        total = summary.get("total_accepted", 0)
        if total < 5:
            obs.append(f"Only {total} signals in period — too few for reliable conclusions. Need 50+ settled trades.")
            return obs

        avg_mfe = summary.get("avg_mfe_pct", 0)
        avg_cap = summary.get("avg_capture_ratio", 0)
        avg_sur = summary.get("avg_profit_surrendered_pct", 0)
        tiers   = summary.get("profit_tiers", {})
        cls     = summary.get("classifications", {})

        if avg_mfe < 5:
            obs.append("Average MFE is very low — signals are not generating meaningful favorable moves. Review entry conditions.")
        elif avg_mfe >= 15:
            obs.append(f"Average MFE of {avg_mfe:.1f}% is healthy — the entry logic is finding real momentum.")

        if avg_cap < 0.30:
            obs.append(f"Capture ratio of {avg_cap:.0%} is very low — only {avg_cap:.0%} of available profit is being kept. "
                       "The primary problem is exit, not entry.")
        elif avg_cap >= 0.60:
            obs.append(f"Capture ratio of {avg_cap:.0%} is strong — exits are well-timed relative to MFE peaks.")

        if avg_sur > 10:
            obs.append(f"Average profit surrender of {avg_sur:.1f}% means trades are regularly reversing after reaching a peak. "
                       "Consider a trailing stop or partial exit at +15% option premium.")

        t10 = tiers.get("mfe_gte_10pct", 0)
        if t10 > 0 and total > 0:
            reach_rate = t10 / total * 100
            obs.append(f"{t10}/{total} signals ({reach_rate:.0f}%) reached +10% MFE. "
                       f"Of those, {tiers.get('mfe_gte_20pct',0)} reached +20% and {tiers.get('mfe_gte_30pct',0)} reached +30%.")

        bad = cls.get("BAD_ENTRY", 0)
        if bad > total * 0.4:
            obs.append(f"{bad} of {total} signals ({bad/total:.0%}) were bad entries — stock never moved. "
                       "Entry filters may need tightening, but wait for 200+ trades before acting.")

        poor_exit = cls.get("GOOD_ENTRY_POOR_EXIT", 0)
        unreal    = cls.get("GOOD_ENTRY_UNREALISTIC_TARGET", 0)
        if poor_exit + unreal > total * 0.4:
            obs.append("Most losses are on good entries — the entry logic is working but profit isn't being captured. "
                       "This is a position management problem, not a signal problem.")

        for reg in regimes:
            if reg.get("avg_surrender") and float(reg["avg_surrender"]) > 12:
                obs.append(f"Regime {reg['regime']} has avg profit surrender of {reg['avg_surrender']}% — "
                           "signals in this regime tend to reverse after initial gains.")

        return obs
