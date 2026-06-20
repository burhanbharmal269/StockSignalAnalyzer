"""PostTradeIntelligenceService — Phase 20.5 Sections 13, 14, 18, 20, 21, 22, 24.

Analytics-only service. Enriches completed signal_analytics rows with:
  - Failure attribution  (dominant cause when stop was hit)
  - Winner attribution   (dominant driver when target was hit)
  - Signal quality score (independent of outcome — was the signal good?)
  - Gate attribution     (joined from risk_decisions.checks)
  - Premium decay        (option efficiency from entry vs captured return)
  - Model failure class  (ACCEPTABLE_LOSS / MODEL_FAILURE / EXECUTION_FAILURE / MARKET_ANOMALY)
  - Operator explanation (human-readable trade narrative)

CRITICAL: This service only reads and updates signal_analytics / risk_decisions /
execution_lifecycle. It does NOT touch any production pipeline.

Usage:
  # Enrich all unattributed completed trades (run as background job or on demand)
  await svc.enrich_unattributed(limit=200)

  # Enrich a single signal by ID
  await svc.attribute_signal("abc-123")

  # Aggregate attribution report for dashboard
  report = await svc.get_attribution_summary(lookback_days=30)
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# ── Failure reason constants ───────────────────────────────────────────────────
_FAILURE_REASONS = frozenset({
    "TREND_FAILURE", "VWAP_FAILURE", "OI_FAILURE", "VOLUME_FAILURE",
    "OPTION_CHAIN_FAILURE", "MTF_FAILURE", "PREMIUM_DECAY", "IV_CRUSH",
    "REGIME_SHIFT", "LATE_ENTRY", "LOW_LIQUIDITY_IMPACT", "SLIPPAGE_IMPACT",
    "EXECUTION_DELAY", "STOP_TOO_TIGHT", "TARGET_TOO_AGGRESSIVE", "UNKNOWN",
})

_SUCCESS_REASONS = frozenset({
    "TREND_DOMINANT", "VWAP_DOMINANT", "OI_DOMINANT", "OPTION_CHAIN_DOMINANT",
    "BREAKOUT_DOMINANT", "MTF_DOMINANT", "MOMENTUM_DOMINANT", "VOLUME_DOMINANT",
    "REGIME_ALIGNMENT", "UNKNOWN",
})

_QUALITY_CATEGORIES = {
    (90, 101): "EXCELLENT",
    (75, 90):  "GOOD",
    (55, 75):  "ACCEPTABLE",
    (35, 55):  "WEAK",
    (0,  35):  "FAILED",
}

_MODEL_CLASSES = frozenset({
    "ACCEPTABLE_LOSS", "MODEL_FAILURE", "EXECUTION_FAILURE", "MARKET_ANOMALY",
})

_STOP_BUCKETS = (
    (0,   15, "IMMEDIATE"),
    (15,  30, "EARLY"),
    (30,  60, "MEDIUM"),
    (60, 999, "LATE"),
)


class PostTradeIntelligenceService:
    """Enriches completed trade records with post-trade analytics."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Public API ────────────────────────────────────────────────────────────

    async def enrich_unattributed(self, limit: int = 200) -> dict:
        """Enrich all completed trades that have not yet been attributed.

        A trade is eligible when:
          - outcome IS NOT NULL (completed)
          - attributed_at IS NULL (not yet processed)

        Returns dict with counts of processed / skipped / errors.
        """
        cutoff_age = datetime.now(UTC) - timedelta(days=365)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          signal_id, ticker, direction, regime, dte,
                          adjusted_score, confidence,
                          trend_score, volume_score, vwap_score, oi_score,
                          sentiment_score, iv_score, option_chain_score,
                          adx_at_signal, volume_ratio_at_signal, rsi_at_signal,
                          mtf_alignment, mtf_score_bonus,
                          entry_price, stop_loss_price, target_price,
                          option_entry, option_sl, option_target, option_type,
                          outcome, target_hit, stop_hit,
                          mfe_pct, mae_pct, pnl_pct, current_return_pct,
                          time_to_target_minutes, time_to_stop_minutes,
                          data_quality_score, was_accepted, rejection_reason,
                          created_at
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND attributed_at IS NULL
                          AND created_at >= :cutoff
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    {"cutoff": cutoff_age, "lim": limit},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("pti.fetch_unattributed_error: %s", exc)
            return {"error": str(exc)}

        processed = skipped = errors = 0
        for row in rows:
            if not row.signal_id:
                skipped += 1
                continue
            try:
                rec = dict(row._mapping)
                await self._enrich_record(rec)
                processed += 1
            except Exception as exc:
                _log.warning("pti.enrich_error signal=%s: %s", row.signal_id, exc)
                errors += 1

        _log.info("pti.enrich_unattributed processed=%d skipped=%d errors=%d",
                  processed, skipped, errors)
        return {"processed": processed, "skipped": skipped, "errors": errors}

    async def attribute_signal(self, signal_id: str) -> dict:
        """Attribute a single signal by ID. Returns the enriched attribution dict."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          signal_id, ticker, direction, regime, dte,
                          adjusted_score, confidence,
                          trend_score, volume_score, vwap_score, oi_score,
                          sentiment_score, iv_score, option_chain_score,
                          adx_at_signal, volume_ratio_at_signal, rsi_at_signal,
                          mtf_alignment, mtf_score_bonus,
                          entry_price, stop_loss_price, target_price,
                          option_entry, option_sl, option_target, option_type,
                          outcome, target_hit, stop_hit,
                          mfe_pct, mae_pct, pnl_pct, current_return_pct,
                          time_to_target_minutes, time_to_stop_minutes,
                          data_quality_score, was_accepted, rejection_reason,
                          created_at
                        FROM signal_analytics
                        WHERE signal_id = :sid
                        LIMIT 1
                    """),
                    {"sid": signal_id},
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("pti.fetch_signal_error: %s", exc)
            return {"error": str(exc)}

        if not row:
            return {"error": f"Signal {signal_id} not found"}
        if row.outcome is None:
            return {"status": "PENDING", "message": "Signal not yet completed"}

        rec = dict(row._mapping)
        return await self._enrich_record(rec)

    async def get_attribution_summary(self, lookback_days: int = 30) -> dict:
        """Aggregate attribution report across all attributed completed trades."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                # Failure distribution
                r_fail = await db.execute(
                    text("""
                        SELECT failure_reason, COUNT(*) AS n,
                               ROUND(AVG(failure_confidence)::numeric, 3) AS avg_conf
                        FROM signal_analytics
                        WHERE stop_hit = true
                          AND failure_reason IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY failure_reason
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                # Success distribution
                r_succ = await db.execute(
                    text("""
                        SELECT success_reason, COUNT(*) AS n,
                               ROUND(AVG(success_confidence)::numeric, 3) AS avg_conf
                        FROM signal_analytics
                        WHERE target_hit = true
                          AND success_reason IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY success_reason
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                # Model failure class distribution
                r_class = await db.execute(
                    text("""
                        SELECT model_failure_class, COUNT(*) AS n
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND model_failure_class IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY model_failure_class
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                # Quality distribution
                r_qual = await db.execute(
                    text("""
                        SELECT signal_quality_category,
                               COUNT(*) AS n,
                               ROUND(AVG(signal_quality_score)::numeric, 1) AS avg_score
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL
                          AND signal_quality_category IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY signal_quality_category
                        ORDER BY avg_score DESC
                    """),
                    {"cutoff": cutoff},
                )
                # Coverage
                r_cov = await db.execute(
                    text("""
                        SELECT
                          COUNT(*) FILTER (WHERE outcome IS NOT NULL)           AS completed,
                          COUNT(*) FILTER (WHERE attributed_at IS NOT NULL)     AS attributed
                        FROM signal_analytics
                        WHERE created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                cov = r_cov.fetchone()
        except Exception as exc:
            _log.warning("pti.summary_error: %s", exc)
            return {"error": str(exc)}

        completed  = int(cov[0] or 0)
        attributed = int(cov[1] or 0)

        return {
            "lookback_days":      lookback_days,
            "completed_trades":   completed,
            "attributed_trades":  attributed,
            "attribution_coverage_pct": round(attributed / completed * 100, 1) if completed else 0,
            "failure_reasons": [
                {"reason": r[0], "count": int(r[1]), "avg_confidence": float(r[2] or 0)}
                for r in r_fail.fetchall()
            ],
            "success_reasons": [
                {"reason": r[0], "count": int(r[1]), "avg_confidence": float(r[2] or 0)}
                for r in r_succ.fetchall()
            ],
            "model_failure_classes": [
                {"class": r[0], "count": int(r[1])}
                for r in r_class.fetchall()
            ],
            "quality_distribution": [
                {"category": r[0], "count": int(r[1]), "avg_quality_score": float(r[2] or 0)}
                for r in r_qual.fetchall()
            ],
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    # ── Internal enrichment ───────────────────────────────────────────────────

    async def _enrich_record(self, rec: dict) -> dict:
        """Compute all attribution fields for a completed trade record and write back."""
        signal_id = rec["signal_id"]
        is_loss   = bool(rec.get("stop_hit"))
        is_win    = bool(rec.get("target_hit"))

        # ── Gate snapshot (from risk_decisions) ───────────────────────────
        gate_data = await self._fetch_gate_snapshot(signal_id)

        # ── Execution data (from execution_lifecycle) ─────────────────────
        exec_data = await self._fetch_execution_data(signal_id)

        # ── Attribution ───────────────────────────────────────────────────
        failure_reason = failure_confidence = failure_snapshot = None
        success_reason = success_confidence = success_snapshot = None

        if is_loss:
            failure_reason, failure_confidence, failure_snapshot = _attribute_failure(rec)
        if is_win:
            success_reason, success_confidence, success_snapshot = _attribute_success(rec)

        # ── Stop bucket ───────────────────────────────────────────────────
        tts            = rec.get("time_to_stop_minutes")
        stop_bucket    = _stop_bucket(tts) if is_loss and tts is not None else None

        # ── Signal quality ────────────────────────────────────────────────
        quality_score  = _compute_quality_score(rec)
        quality_cat    = _quality_category(quality_score)

        # ── Model failure class ───────────────────────────────────────────
        mf_class = _model_failure_class(
            quality_score=quality_score,
            is_loss=is_loss,
            tts=tts,
            slippage_pct=exec_data.get("total_slippage_pct"),
            signal_to_fill_ms=exec_data.get("signal_to_fill_ms"),
        )

        # ── Premium decay ─────────────────────────────────────────────────
        prem = _compute_premium_decay(rec)

        # ── Operator explanation ──────────────────────────────────────────
        explanation = _generate_explanation(
            rec=rec,
            failure_reason=failure_reason,
            failure_snapshot=failure_snapshot,
            success_reason=success_reason,
            quality_score=quality_score,
            mf_class=mf_class,
        )

        # ── Write back ────────────────────────────────────────────────────
        update_data = {
            "sig": signal_id,
            "failure_reason":            failure_reason,
            "failure_confidence":        failure_confidence,
            "failure_snapshot_json":     json.dumps(failure_snapshot) if failure_snapshot else None,
            "success_reason":            success_reason,
            "success_confidence":        success_confidence,
            "success_snapshot_json":     json.dumps(success_snapshot) if success_snapshot else None,
            "stop_timing_bucket":        stop_bucket,
            "signal_quality_score":      round(quality_score, 1),
            "signal_quality_category":   quality_cat,
            "model_failure_class":       mf_class,
            "gate_snapshot_json":        json.dumps(gate_data.get("checks")) if gate_data.get("checks") else None,
            "gate_pass_count":           gate_data.get("pass_count"),
            "gate_fail_count":           gate_data.get("fail_count"),
            "premium_efficiency":        prem.get("premium_efficiency"),
            "premium_capture_ratio":     prem.get("premium_capture_ratio"),
            "theta_drag_estimate":       prem.get("theta_drag_estimate"),
            "iv_drag_estimate":          prem.get("iv_drag_estimate"),
            "operator_explanation":      explanation,
            "attributed_at":             datetime.now(UTC),
        }

        try:
            async with self._sf() as db:
                await db.execute(
                    text("""
                        UPDATE signal_analytics SET
                          failure_reason          = :failure_reason,
                          failure_confidence      = :failure_confidence,
                          failure_snapshot_json   = :failure_snapshot_json,
                          success_reason          = :success_reason,
                          success_confidence      = :success_confidence,
                          success_snapshot_json   = :success_snapshot_json,
                          stop_timing_bucket      = :stop_timing_bucket,
                          signal_quality_score    = :signal_quality_score,
                          signal_quality_category = :signal_quality_category,
                          model_failure_class     = :model_failure_class,
                          gate_snapshot_json      = :gate_snapshot_json,
                          gate_pass_count         = :gate_pass_count,
                          gate_fail_count         = :gate_fail_count,
                          premium_efficiency      = :premium_efficiency,
                          premium_capture_ratio   = :premium_capture_ratio,
                          theta_drag_estimate     = :theta_drag_estimate,
                          iv_drag_estimate        = :iv_drag_estimate,
                          operator_explanation    = :operator_explanation,
                          attributed_at           = :attributed_at
                        WHERE signal_id = :sig
                    """),
                    update_data,
                )
                await db.commit()
        except Exception as exc:
            _log.warning("pti.write_error signal=%s: %s", signal_id, exc)
            raise

        result = {
            "signal_id":              signal_id,
            "failure_reason":         failure_reason,
            "failure_confidence":     failure_confidence,
            "success_reason":         success_reason,
            "success_confidence":     success_confidence,
            "stop_timing_bucket":     stop_bucket,
            "signal_quality_score":   quality_score,
            "signal_quality_category": quality_cat,
            "model_failure_class":    mf_class,
            "premium_efficiency":     prem.get("premium_efficiency"),
            "operator_explanation":   explanation,
            "attributed_at":          update_data["attributed_at"].isoformat(),
        }
        _log.debug("pti.attributed signal=%s quality=%.1f class=%s",
                   signal_id, quality_score, mf_class)
        return result

    async def _fetch_gate_snapshot(self, signal_id: str) -> dict:
        """Fetch risk decision gate snapshot for this signal."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT checks, approved
                        FROM risk_decisions
                        WHERE signal_id = :sid
                        ORDER BY evaluated_at DESC
                        LIMIT 1
                    """),
                    {"sid": signal_id},
                )
                row = r.fetchone()
        except Exception:
            return {}

        if not row:
            return {}

        checks = row[0] if isinstance(row[0], dict) else {}
        pass_count = sum(1 for v in checks.values() if v is True or (isinstance(v, dict) and v.get("pass")))
        fail_count = len(checks) - pass_count
        return {"checks": checks, "pass_count": pass_count, "fail_count": fail_count}

    async def _fetch_execution_data(self, signal_id: str) -> dict:
        """Fetch execution slippage and latency for this signal."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT total_slippage_pct, signal_to_fill_ms
                        FROM execution_lifecycle
                        WHERE signal_id = :sid
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"sid": signal_id},
                )
                row = r.fetchone()
        except Exception:
            return {}

        if not row:
            return {}
        return {
            "total_slippage_pct":  float(row[0]) if row[0] is not None else None,
            "signal_to_fill_ms":   float(row[1]) if row[1] is not None else None,
        }


# ── Pure-function attribution helpers ─────────────────────────────────────────

def _attribute_failure(rec: dict) -> tuple[str, float, dict]:
    """Return (reason, confidence, evidence_snapshot) for a stop-hit trade."""
    evidence: dict[str, float] = {}

    direction = (rec.get("direction") or "").upper()
    mtf       = (rec.get("mtf_alignment") or "").upper()
    regime    = (rec.get("regime") or "").upper()
    dte       = rec.get("dte")
    tts       = rec.get("time_to_stop_minutes")
    mfe       = float(rec.get("mfe_pct") or 0)

    ts  = rec.get("trend_score")
    vs  = rec.get("vwap_score")
    vls = rec.get("volume_score")
    ois = rec.get("oi_score")
    ocs = rec.get("option_chain_score")
    ivs = rec.get("iv_score")
    adx = rec.get("adx_at_signal")
    vr  = rec.get("volume_ratio_at_signal")

    # ── MTF conflict ──────────────────────────────────────────────────────
    if mtf and mtf not in ("NEUTRAL", "UNKNOWN", ""):
        expecting_bull = direction == "CE"
        if (expecting_bull and mtf == "BEARISH") or (not expecting_bull and mtf == "BULLISH"):
            evidence["MTF_FAILURE"] = 0.85

    # ── Time-based evidence ───────────────────────────────────────────────
    if tts is not None:
        if tts <= 5:
            evidence["LATE_ENTRY"]    = max(evidence.get("LATE_ENTRY", 0), 0.72)
            evidence["STOP_TOO_TIGHT"] = max(evidence.get("STOP_TOO_TIGHT", 0), 0.65)
        elif tts <= 15:
            evidence["STOP_TOO_TIGHT"] = max(evidence.get("STOP_TOO_TIGHT", 0), 0.70)

    # ── Trade behaviour ───────────────────────────────────────────────────
    if mfe < 0.005:
        # Trade never went in our favour — directional premise failed
        evidence["TREND_FAILURE"] = max(evidence.get("TREND_FAILURE", 0), 0.70)
    elif mfe > 0.30 and tts is not None and tts <= 25:
        # Had a favourable move then sharply reversed
        evidence["REGIME_SHIFT"] = max(evidence.get("REGIME_SHIFT", 0), 0.60)

    # ── Regime ────────────────────────────────────────────────────────────
    if regime == "SIDEWAYS":
        evidence["REGIME_SHIFT"] = max(evidence.get("REGIME_SHIFT", 0), 0.55)

    # ── Near-expiry premium decay ─────────────────────────────────────────
    if dte is not None and dte <= 2:
        evidence["PREMIUM_DECAY"] = max(evidence.get("PREMIUM_DECAY", 0), 0.65)

    # ── ADX low → weak trend ──────────────────────────────────────────────
    if adx is not None and float(adx) < 18.0:
        evidence["TREND_FAILURE"] = max(evidence.get("TREND_FAILURE", 0), 0.50)

    # ── Volume collapsed ──────────────────────────────────────────────────
    if vr is not None and float(vr) < 0.6:
        evidence["VOLUME_FAILURE"] = max(evidence.get("VOLUME_FAILURE", 0), 0.55)

    # ── Component weakness: find the weakest relative to others ───────────
    present = {
        "trend":  float(ts)  if ts  is not None else None,
        "vwap":   float(vs)  if vs  is not None else None,
        "volume": float(vls) if vls is not None else None,
        "oi":     float(ois) if ois is not None else None,
        "oc":     float(ocs) if ocs is not None else None,
        "iv":     float(ivs) if ivs is not None else None,
    }
    present_vals = {k: v for k, v in present.items() if v is not None}
    if len(present_vals) >= 3:
        avg_cs = sum(present_vals.values()) / len(present_vals)
        if avg_cs > 0:
            # Component whose shortfall from avg is largest
            shortfalls = {k: avg_cs - v for k, v in present_vals.items()}
            worst_comp, worst_shortfall = max(shortfalls.items(), key=lambda x: x[1])
            if worst_shortfall > avg_cs * 0.35:
                _reason_map = {
                    "trend":  "TREND_FAILURE",  "vwap":  "VWAP_FAILURE",
                    "volume": "VOLUME_FAILURE",  "oi":    "OI_FAILURE",
                    "oc":     "OPTION_CHAIN_FAILURE", "iv": "IV_CRUSH",
                }
                r = _reason_map.get(worst_comp)
                if r:
                    evidence[r] = max(evidence.get(r, 0), 0.55)

    # OI None = index with no OI tracking
    if ois is None and not present_vals:
        evidence["OI_FAILURE"] = max(evidence.get("OI_FAILURE", 0), 0.20)

    if not evidence:
        return "UNKNOWN", 0.25, {}

    sorted_ev = sorted(evidence.items(), key=lambda x: x[1], reverse=True)
    top, top_conf = sorted_ev[0]

    if len(sorted_ev) > 1:
        second_conf = sorted_ev[1][1]
        separation  = (top_conf - second_conf) / (top_conf + 0.001)
        final_conf  = top_conf * (0.55 + 0.45 * separation)
    else:
        final_conf  = top_conf * 0.88

    return top, round(min(final_conf, 0.99), 3), {k: round(v, 3) for k, v in evidence.items()}


def _attribute_success(rec: dict) -> tuple[str, float, dict]:
    """Return (reason, confidence, evidence_snapshot) for a target-hit trade."""
    evidence: dict[str, float] = {}

    direction = (rec.get("direction") or "").upper()
    mtf       = (rec.get("mtf_alignment") or "").upper()
    regime    = (rec.get("regime") or "").upper()
    ttt       = rec.get("time_to_target_minutes")
    mfe       = float(rec.get("mfe_pct") or 0)
    adx       = rec.get("adx_at_signal")
    vr        = rec.get("volume_ratio_at_signal")

    ts  = rec.get("trend_score")
    vs  = rec.get("vwap_score")
    vls = rec.get("volume_score")
    ois = rec.get("oi_score")
    ocs = rec.get("option_chain_score")
    ivs = rec.get("iv_score")

    # ── MTF aligned ───────────────────────────────────────────────────────
    if mtf and mtf not in ("NEUTRAL", "UNKNOWN", ""):
        expecting_bull = direction == "CE"
        if (expecting_bull and mtf == "BULLISH") or (not expecting_bull and mtf == "BEARISH"):
            evidence["MTF_DOMINANT"] = 0.80

    # ── Strong regime ─────────────────────────────────────────────────────
    if regime in ("TRENDING", "BULLISH_TRENDING", "BEARISH_TRENDING", "STRONG"):
        evidence["REGIME_ALIGNMENT"] = 0.65

    # ── ADX strong trend ──────────────────────────────────────────────────
    if adx is not None and float(adx) > 28.0:
        evidence["TREND_DOMINANT"] = max(evidence.get("TREND_DOMINANT", 0), 0.72)
        if float(adx) > 35.0:
            evidence["BREAKOUT_DOMINANT"] = max(evidence.get("BREAKOUT_DOMINANT", 0), 0.65)

    # ── Volume surge ──────────────────────────────────────────────────────
    if vr is not None and float(vr) >= 2.0:
        evidence["VOLUME_DOMINANT"] = max(evidence.get("VOLUME_DOMINANT", 0), 0.68)
        evidence["MOMENTUM_DOMINANT"] = max(evidence.get("MOMENTUM_DOMINANT", 0), 0.55)

    # ── Fast hit → strong momentum ────────────────────────────────────────
    if ttt is not None and ttt <= 30:
        evidence["MOMENTUM_DOMINANT"] = max(evidence.get("MOMENTUM_DOMINANT", 0), 0.70)
        evidence["BREAKOUT_DOMINANT"] = max(evidence.get("BREAKOUT_DOMINANT", 0), 0.55)

    # ── Component strength: find the strongest contributor ────────────────
    present = {
        "trend":  float(ts)  if ts  is not None else None,
        "vwap":   float(vs)  if vs  is not None else None,
        "volume": float(vls) if vls is not None else None,
        "oi":     float(ois) if ois is not None else None,
        "oc":     float(ocs) if ocs is not None else None,
        "iv":     float(ivs) if ivs is not None else None,
    }
    present_vals = {k: v for k, v in present.items() if v is not None}
    if len(present_vals) >= 3:
        avg_cs = sum(present_vals.values()) / len(present_vals)
        if avg_cs > 0:
            best_comp, best_val = max(present_vals.items(), key=lambda x: x[1])
            if best_val > avg_cs * 1.35:
                _reason_map = {
                    "trend":  "TREND_DOMINANT",  "vwap":  "VWAP_DOMINANT",
                    "volume": "VOLUME_DOMINANT",  "oi":    "OI_DOMINANT",
                    "oc":     "OPTION_CHAIN_DOMINANT", "iv": "MOMENTUM_DOMINANT",
                }
                r = _reason_map.get(best_comp)
                if r:
                    evidence[r] = max(evidence.get(r, 0), 0.62)

    if not evidence:
        return "UNKNOWN", 0.30, {}

    sorted_ev = sorted(evidence.items(), key=lambda x: x[1], reverse=True)
    top, top_conf = sorted_ev[0]

    if len(sorted_ev) > 1:
        second_conf = sorted_ev[1][1]
        separation  = (top_conf - second_conf) / (top_conf + 0.001)
        final_conf  = top_conf * (0.55 + 0.45 * separation)
    else:
        final_conf  = top_conf * 0.88

    return top, round(min(final_conf, 0.99), 3), {k: round(v, 3) for k, v in evidence.items()}


def _compute_quality_score(rec: dict) -> float:
    """Compute signal quality score (0-100) independently of outcome.

    Measures: was this a good signal regardless of what the market did?

    Components:
      35% — Overall adjusted score (signal strength)
      20% — Data quality at signal time
      20% — Component alignment (low variance = high alignment)
      15% — MTF agreement with direction
      10% — Entry timing quality (not-immediate stop = better entry)
    """
    adj_score = float(rec.get("adjusted_score") or 0)
    dq        = float(rec.get("data_quality_score") or 60)  # default 60 if missing
    direction = (rec.get("direction") or "").upper()
    mtf       = (rec.get("mtf_alignment") or "").upper()
    tts       = rec.get("time_to_stop_minutes")
    is_loss   = bool(rec.get("stop_hit"))
    is_win    = bool(rec.get("target_hit"))

    cs_vals = [
        float(v) for k, v in rec.items()
        if k in ("trend_score", "volume_score", "vwap_score", "oi_score", "option_chain_score", "iv_score")
        and v is not None
    ]

    # ── Adjusted score component (35%) ────────────────────────────────────
    score_component = min(adj_score, 100.0) * 0.35

    # ── Data quality component (20%) ──────────────────────────────────────
    dq_component = min(dq, 100.0) * 0.20

    # ── Component alignment / consistency (20%) ───────────────────────────
    if len(cs_vals) >= 3:
        avg_cs = sum(cs_vals) / len(cs_vals)
        if avg_cs > 0:
            cv = statistics.stdev(cs_vals) / avg_cs  # coefficient of variation
            # Low CV = high alignment (all components agree)
            alignment_score = max(0.0, 1.0 - cv) * 100.0
        else:
            alignment_score = 50.0
    else:
        alignment_score = 50.0  # insufficient data
    align_component = alignment_score * 0.20

    # ── MTF alignment (15%) ───────────────────────────────────────────────
    if mtf in ("NEUTRAL", "UNKNOWN", ""):
        mtf_component = 50.0 * 0.15
    else:
        expecting_bull = direction == "CE"
        aligned = (expecting_bull and mtf == "BULLISH") or (not expecting_bull and mtf == "BEARISH")
        mtf_component = (100.0 if aligned else 20.0) * 0.15

    # ── Entry timing (10%) ────────────────────────────────────────────────
    if is_loss and tts is not None:
        if tts <= 5:
            timing_score = 10.0   # immediate stop = very poor entry
        elif tts <= 15:
            timing_score = 35.0
        elif tts <= 30:
            timing_score = 65.0
        else:
            timing_score = 90.0   # survived 30+ min = reasonable entry
    elif is_win:
        timing_score = 90.0
    else:
        timing_score = 60.0       # open / expired

    timing_component = timing_score * 0.10

    raw = score_component + dq_component + align_component + mtf_component + timing_component
    return round(max(0.0, min(100.0, raw)), 1)


def _quality_category(score: float) -> str:
    for (lo, hi), cat in _QUALITY_CATEGORIES.items():
        if lo <= score < hi:
            return cat
    return "FAILED"


def _model_failure_class(
    *,
    quality_score: float,
    is_loss: bool,
    tts: int | None,
    slippage_pct: float | None,
    signal_to_fill_ms: float | None,
) -> str:
    """Classify the nature of a trade outcome."""
    if not is_loss:
        return "ACCEPTABLE_LOSS"  # wins don't need classification

    # Execution failure: high slippage OR very slow fill
    if slippage_pct is not None and float(slippage_pct) > 1.5:
        return "EXECUTION_FAILURE"
    if signal_to_fill_ms is not None and float(signal_to_fill_ms) > 300_000:  # >5 min
        return "EXECUTION_FAILURE"

    # Market anomaly: good signal, immediate reversal (< 10 min)
    if quality_score >= 70 and tts is not None and tts <= 10:
        return "MARKET_ANOMALY"

    # Acceptable loss: good signal, bad luck
    if quality_score >= 65:
        return "ACCEPTABLE_LOSS"

    # Model failure: weak signal that should not have passed the gate
    return "MODEL_FAILURE"


def _stop_bucket(tts: int) -> str:
    for lo, hi, label in _STOP_BUCKETS:
        if lo <= tts < hi:
            return label
    return "LATE"


def _compute_premium_decay(rec: dict) -> dict:
    """Estimate premium decay metrics from option fields and pnl.

    premium_efficiency:   pnl_pct / theoretical_max_gain (how much we captured)
    premium_capture_ratio: actual_pnl / option_spread  (capture vs max spread)
    theta_drag_estimate:  rough theta impact = days_held × daily_theta_proxy
    iv_drag_estimate:     proxy using iv_score direction
    """
    option_entry  = rec.get("option_entry")
    option_target = rec.get("option_target")
    option_sl     = rec.get("option_sl")
    pnl_pct       = rec.get("pnl_pct") or rec.get("current_return_pct")
    dte           = rec.get("dte")
    tts           = rec.get("time_to_stop_minutes")
    ttt           = rec.get("time_to_target_minutes")
    iv_score      = rec.get("iv_score")

    result: dict = {}

    if option_entry and option_target and float(option_entry) > 0:
        entry_f  = float(option_entry)
        target_f = float(option_target)
        sl_f     = float(option_sl) if option_sl else None
        pnl_f    = float(pnl_pct) if pnl_pct is not None else None

        theoretical_gain = (target_f - entry_f) / entry_f
        theoretical_loss = ((sl_f - entry_f) / entry_f) if sl_f else None

        if pnl_f is not None and theoretical_gain > 0:
            # premium_efficiency: 1.0 = captured full theoretical gain
            eff = pnl_f / theoretical_gain
            result["premium_efficiency"] = round(max(-5.0, min(5.0, eff)), 4)

        if pnl_f is not None and theoretical_loss is not None:
            spread = abs(theoretical_gain - theoretical_loss)
            if spread > 0:
                capture = (pnl_f - theoretical_loss) / spread
                result["premium_capture_ratio"] = round(max(-1.0, min(1.0, capture)), 4)

        # Theta drag estimate: proxy = 1/(dte×5) per 15-min candle
        if dte is not None and dte > 0:
            held_minutes = (tts or ttt or 60)
            candles_held = held_minutes / 15
            daily_theta_proxy = 1.0 / (float(dte) * 5)
            theta_drag = candles_held * daily_theta_proxy / 4  # rough fraction of premium
            result["theta_drag_estimate"] = round(min(theta_drag, 1.0), 4)

        # IV drag estimate: if IV was falling (low iv_score), options lost to IV crush
        if iv_score is not None:
            iv_s = float(iv_score)
            # Higher iv_score = better IV environment; negative iv_score proxy = IV crush
            iv_drag = max(0.0, (3.0 - iv_s) / 10.0)  # 0 to 0.3 range
            result["iv_drag_estimate"] = round(iv_drag, 4)

    return result


def _generate_explanation(
    *,
    rec: dict,
    failure_reason: str | None,
    failure_snapshot: dict | None,
    success_reason: str | None,
    quality_score: float,
    mf_class: str,
) -> str:
    """Generate a human-readable trade narrative for the operator."""
    ticker    = rec.get("ticker", "?")
    direction = (rec.get("direction") or "").upper()
    regime    = (rec.get("regime") or "UNKNOWN")
    score     = rec.get("adjusted_score") or 0
    conf      = rec.get("confidence") or 0
    adx       = rec.get("adx_at_signal")
    vr        = rec.get("volume_ratio_at_signal")
    mtf       = (rec.get("mtf_alignment") or "UNKNOWN").upper()
    is_win    = bool(rec.get("target_hit"))
    is_loss   = bool(rec.get("stop_hit"))
    tts       = rec.get("time_to_stop_minutes")
    ttt       = rec.get("time_to_target_minutes")
    mfe       = float(rec.get("mfe_pct") or 0)
    dte       = rec.get("dte")

    lines = [f"Signal: {ticker} {direction} | Regime: {regime}"]
    lines.append(f"Score: {score:.1f}  Confidence: {conf:.1f}%  ADX: {adx or 'N/A'}  "
                 f"Volume: {f'{float(vr):.1f}x' if vr else 'N/A'}  MTF: {mtf}  DTE: {dte or 'N/A'}")

    lines.append("")
    lines.append("Signal generated because:")
    if adx and float(adx) > 25:
        lines.append(f"  • Strong trend — ADX {float(adx):.0f}")
    if vr and float(vr) >= 1.5:
        lines.append(f"  • Volume surge — {float(vr):.1f}× average")
    if mtf in ("BULLISH", "BEARISH"):
        lines.append(f"  • MTF {mtf.lower()} alignment confirmed")
    if float(score) >= 70:
        lines.append(f"  • High composite score {score:.1f}")

    lines.append("")
    if is_win:
        lines.append("Trade succeeded because:")
        if success_reason and success_reason != "UNKNOWN":
            label = success_reason.replace("_", " ").title()
            lines.append(f"  • {label}")
        if ttt:
            lines.append(f"  • Target reached in {ttt} minutes")
        if mfe > 0:
            lines.append(f"  • Max favourable excursion: {mfe*100:.2f}%")
    elif is_loss:
        lines.append("Trade failed because:")
        if failure_reason and failure_reason != "UNKNOWN":
            label = failure_reason.replace("_", " ").title()
            lines.append(f"  • {label} (confidence: {failure_snapshot and max(failure_snapshot.values(), default=0):.0%})")
        if mfe > 0:
            lines.append(f"  • Max favourable excursion before reversal: {mfe*100:.2f}%")
        if tts:
            lines.append(f"  • Stop hit at {tts} minutes")
    else:
        lines.append("Trade expired without target or stop hit.")

    lines.append("")
    lines.append(f"Signal Quality Score: {quality_score:.0f}/100")
    lines.append(f"Classification: {mf_class.replace('_', ' ').title()}")

    return "\n".join(lines)
