"""SignalAnalyticsService — always-on signal intelligence storage.

Records every scanner result (accepted AND rejected) to the signal_analytics
table. This is completely independent of execution mode — signals are tracked
whether or not orders are placed.

Used by:
  - SignalScannerService: calls record() after every _process_symbol result
  - SignalOutcomeTrackerService: updates outcome fields asynchronously
  - StrategyPerformanceService: queries for leaderboard computation
  - FilterAnalyticsService: queries for filter effectiveness analysis
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import core.application.services.platform_constants as _PLATFORM_CONSTANTS

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from core.application.services.execution_lock_service import ExecutionLockService
    from core.application.services.option_strike_selector import OptionPlay
    from core.application.services.signal_qualification_service import SignalQualificationService
    from core.domain.value_objects.signal_request import SignalRequest
    from core.domain.value_objects.signal_result import SignalResult

_log = logging.getLogger(__name__)


class SignalAnalyticsService:
    """Persists signal analytics for every scanner result, regardless of outcome."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        execution_lock_service: "ExecutionLockService | None" = None,
        qualification_service: "SignalQualificationService | None" = None,
    ) -> None:
        self._sf = session_factory
        self._execution_lock = execution_lock_service
        self._qualification  = qualification_service

    async def _get_execution_mode(self) -> str:
        if self._execution_lock is None:
            return "MANUAL"
        try:
            state = await self._execution_lock.get_state()
            return state.execution_mode
        except Exception:
            return "MANUAL"

    async def record(
        self,
        symbol_name: str,
        exchange: str,
        is_index: bool,
        sector: str | None,
        request: "SignalRequest | None",
        result: "SignalResult",
        features: dict,
        option_play: "OptionPlay | None" = None,
        overlay: "dict | None" = None,
        oi_context: "dict | None" = None,
    ) -> None:
        """Record one scanner result to signal_analytics. Never raises — fail-open."""
        try:
            execution_mode = await self._get_execution_mode()
            await self._insert(
                symbol_name, exchange, is_index, sector,
                request, result, features, execution_mode,
                option_play=option_play,
                overlay=overlay,
                oi_context=oi_context,
            )
        except Exception as exc:
            _log.warning("signal_analytics.record_failed symbol=%s: %s", symbol_name, exc, exc_info=True)

    async def _insert(
        self,
        ticker: str,
        exchange: str,
        is_index: bool,
        sector: str | None,
        request: "SignalRequest | None",
        result: "SignalResult",
        features: dict,
        execution_mode: str = "MANUAL",
        option_play: "OptionPlay | None" = None,
        overlay: "dict | None" = None,
        oi_context: "dict | None" = None,
    ) -> None:
        bd = result.score_breakdown
        rejection = result.rejection_reason.value if result.rejection_reason else None

        params: dict = {
            "signal_id": str(result.signal_id) if result.signal_id else None,
            "ticker": ticker,
            "exchange": exchange,
            "direction": result.direction or "NEUTRAL",
            "strategy_type": str(request.strategy_type) if request else "UNKNOWN",
            "regime": str(request.regime) if request else "UNKNOWN",
            "sector": sector,
            "is_index": is_index,
            "execution_mode": execution_mode,

            "entry_price": float(request.entry_price) if request else None,
            "stop_loss_price": float(request.stop_loss_price) if request else None,
            "target_price": float(request.target_price) if request else None,
            "lot_size": int(request.lot_size) if request else 1,
            "dte": int(request.dte) if request else None,

            "raw_score": round(bd.total_before_penalties, 2) if bd else None,
            "adjusted_score": result.adjusted_score,
            "confidence": result.final_confidence,

            "trend_score": round(bd.trend, 2) if bd else None,
            "volume_score": round(bd.volume, 2) if bd else None,
            "vwap_score": round(bd.vwap, 2) if bd else None,
            "oi_score": round(bd.oi_buildup, 2) if bd else None,
            "sentiment_score": round(bd.sentiment, 2) if bd else None,
            "iv_score": round(bd.iv_analysis, 2) if bd else None,
            "option_chain_score": round(bd.option_chain, 2) if bd else None,

            "adx_at_signal": features.get("adx"),
            "volume_ratio_at_signal": features.get("volume_ratio"),
            "rsi_at_signal": features.get("rsi_14"),

            # Phase 14 MTF attribution fields
            "mtf_alignment":         features.get("mtf_alignment"),
            "mtf_score_bonus":       features.get("mtf_score_bonus"),
            "mtf_confidence_bonus":  features.get("mtf_confidence_bonus"),

            # Phase 15 — data quality monitoring (never affects scoring)
            "data_quality_score":    features.get("data_quality_score"),
            "missing_sources":       features.get("missing_sources"),

            "was_accepted": result.accepted,
            "rejection_reason": rejection,

            # Option contract fields
            "option_type":   option_play.option_type   if option_play else None,
            "option_strike": option_play.option_strike  if option_play else None,
            "option_expiry": (
                date.fromisoformat(option_play.option_expiry)
                if option_play and isinstance(option_play.option_expiry, str)
                else option_play.option_expiry if option_play else None
            ),
            "option_symbol": option_play.option_symbol  if option_play else None,
            "option_entry":  option_play.entry          if option_play else None,
            "option_sl":     option_play.sl             if option_play else None,
            "option_target": option_play.target         if option_play else None,

            # Phase 21.1 — context overlay attribution (all nullable)
            "market_context":              overlay.get("market_context")       if overlay else None,
            "market_context_adj":          overlay.get("market_context_adj")   if overlay else None,
            "event_adj":                   overlay.get("event_adj")            if overlay else None,
            "event_overlay_json":          overlay.get("event_overlay_json")   if overlay else None,
            "regime_stability":            overlay.get("regime_stability")     if overlay else None,
            "regime_stability_adj":        overlay.get("regime_stability_adj") if overlay else None,
            "confidence_attribution_json": (
                json.dumps(overlay) if overlay else None
            ),
            "context_size_multiplier":     overlay.get("size_multiplier")     if overlay else None,
            "overlay_adjusted_confidence": overlay.get("overlay_confidence")  if overlay else None,
            "execution_grade":             overlay.get("execution_grade")      if overlay else None,
            # Phase 21.2 — decision trace + versions
            "decision_trace_json":         overlay.get("decision_trace_json") if overlay else None,
            "decision_version":            overlay.get("decision_version")    if overlay else None,
            "overlay_version":             overlay.get("overlay_version")     if overlay else None,

            # Phase 23 — deployment stage (derived from execution mode)
            "deployment_stage": (
                "PAPER" if execution_mode == "MANUAL" else "LIVE_1LOT"
            ),
            # Phase 23 §2 — qualification defaults (overwritten below if service present)
            "qualification_grade":     None,
            "qualification_reason":    None,
            "qualification_version":   None,
            "qualification_timestamp": None,

            # Phase 24 §1 — Expected Move Engine
            "expected_underlying_move_pct": overlay.get("expected_underlying_move_pct") if overlay else None,
            "expected_option_move_pct":     overlay.get("expected_option_move_pct")     if overlay else None,
            "expected_holding_minutes":     overlay.get("expected_holding_minutes")     if overlay else None,
            "reach_prob_json":              overlay.get("reach_prob_json")              if overlay else None,
            # Phase 24 §2 — Dynamic Target Recommendation
            "recommended_target_pct":      overlay.get("recommended_target_pct")       if overlay else None,
            "recommended_stop_pct":        overlay.get("recommended_stop_pct")         if overlay else None,
            "recommended_holding_minutes": overlay.get("recommended_holding_minutes")  if overlay else None,
            "target_confidence":           overlay.get("target_confidence")            if overlay else None,
            # Phase 24 §3 — Target Realism (configured values captured at signal time)
            "configured_target_pct": (
                round((float(option_play.target) - float(option_play.entry)) / float(option_play.entry) * 100, 4)
                if option_play and option_play.entry and option_play.target else None
            ),
            "configured_sl_pct": (
                round((float(option_play.entry) - float(option_play.sl)) / float(option_play.entry) * 100, 4)
                if option_play and option_play.entry and option_play.sl else None
            ),
            # Phase 25 §5 — Strategy versioning (immutable fingerprint at signal creation)
            "strategy_version": _PLATFORM_CONSTANTS.STRATEGY_VERSION,
            "risk_version":     _PLATFORM_CONSTANTS.RISK_VERSION,
            "target_version":   _PLATFORM_CONSTANTS.TARGET_VERSION,
            # Phase 25 §2 — Experiment assignment (populated by caller via overlay)
            "experiment_id":    overlay.get("experiment_id") if overlay else None,
            "ab_group":         overlay.get("ab_group")      if overlay else None,

            # Phase 21.1 — Futures OI context at signal time (all nullable)
            "futures_oi":              oi_context.get("futures_oi")              if oi_context else None,
            "oi_change":               oi_context.get("oi_change")               if oi_context else None,
            "oi_change_pct":           oi_context.get("oi_change_pct")           if oi_context else None,
            "oi_direction":            oi_context.get("oi_direction")            if oi_context else None,
            "oi_regime":               oi_context.get("oi_regime")               if oi_context else None,
            "futures_contract":        oi_context.get("futures_contract")        if oi_context else None,
            "oi_quality_score":        oi_context.get("oi_quality_score")        if oi_context else None,
            "quote_freshness_seconds": oi_context.get("quote_freshness_seconds") if oi_context else None,
        }

        # Phase 23 §2 — signal qualification (pure research label, no pipeline effect)
        if self._qualification is not None:
            qual = self._qualification.qualify(
                score=params["adjusted_score"],
                confidence=params["confidence"],
                execution_grade=params["execution_grade"],
                data_quality_score=params["data_quality_score"],
                market_context=params["market_context"],
                was_accepted=result.accepted,
            )
            if qual:
                params.update(qual)

        async with self._sf() as db:
            await db.execute(
                text("""
                    INSERT INTO signal_analytics (
                        signal_id, ticker, exchange, direction, strategy_type, regime,
                        sector, is_index, execution_mode,
                        entry_price, stop_loss_price, target_price, lot_size, dte,
                        raw_score, adjusted_score, confidence,
                        trend_score, volume_score, vwap_score, oi_score,
                        sentiment_score, iv_score, option_chain_score,
                        adx_at_signal, volume_ratio_at_signal, rsi_at_signal,
                        mtf_alignment, mtf_score_bonus, mtf_confidence_bonus,
                        data_quality_score, missing_sources,
                        was_accepted, rejection_reason,
                        option_type, option_strike, option_expiry, option_symbol,
                        option_entry, option_sl, option_target,
                        market_context, market_context_adj, event_adj, event_overlay_json,
                        regime_stability, regime_stability_adj,
                        confidence_attribution_json,
                        context_size_multiplier, overlay_adjusted_confidence,
                        execution_grade,
                        decision_trace_json, decision_version, overlay_version,
                        deployment_stage,
                        qualification_grade, qualification_reason,
                        qualification_version, qualification_timestamp,
                        expected_underlying_move_pct, expected_option_move_pct,
                        expected_holding_minutes, reach_prob_json,
                        recommended_target_pct, recommended_stop_pct,
                        recommended_holding_minutes, target_confidence,
                        configured_target_pct, configured_sl_pct,
                        strategy_version, risk_version, target_version,
                        experiment_id, ab_group,
                        futures_oi, oi_change, oi_change_pct, oi_direction,
                        oi_regime, futures_contract, oi_quality_score, quote_freshness_seconds,
                        futures_oi, oi_change, oi_change_pct, oi_direction,
                        oi_regime, futures_contract, oi_quality_score, quote_freshness_seconds
                    ) VALUES (
                        :signal_id, :ticker, :exchange, :direction, :strategy_type, :regime,
                        :sector, :is_index, :execution_mode,
                        :entry_price, :stop_loss_price, :target_price, :lot_size, :dte,
                        :raw_score, :adjusted_score, :confidence,
                        :trend_score, :volume_score, :vwap_score, :oi_score,
                        :sentiment_score, :iv_score, :option_chain_score,
                        :adx_at_signal, :volume_ratio_at_signal, :rsi_at_signal,
                        :mtf_alignment, :mtf_score_bonus, :mtf_confidence_bonus,
                        :data_quality_score, :missing_sources,
                        :was_accepted, :rejection_reason,
                        :option_type, :option_strike, :option_expiry, :option_symbol,
                        :option_entry, :option_sl, :option_target,
                        :market_context, :market_context_adj, :event_adj, :event_overlay_json,
                        :regime_stability, :regime_stability_adj,
                        :confidence_attribution_json,
                        :context_size_multiplier, :overlay_adjusted_confidence,
                        :execution_grade,
                        :decision_trace_json, :decision_version, :overlay_version,
                        :deployment_stage,
                        :qualification_grade, :qualification_reason,
                        :qualification_version, :qualification_timestamp,
                        :expected_underlying_move_pct, :expected_option_move_pct,
                        :expected_holding_minutes, :reach_prob_json,
                        :recommended_target_pct, :recommended_stop_pct,
                        :recommended_holding_minutes, :target_confidence,
                        :configured_target_pct, :configured_sl_pct,
                        :strategy_version, :risk_version, :target_version,
                        :experiment_id, :ab_group,
                        :futures_oi, :oi_change, :oi_change_pct, :oi_direction,
                        :oi_regime, :futures_contract, :oi_quality_score, :quote_freshness_seconds
                    )
                """),
                params,
            )
            await db.commit()

        _log.debug(
            "signal_analytics.recorded symbol=%s accepted=%s rejection=%s",
            ticker, result.accepted, rejection,
        )

    async def get_overlay_for_signal(self, signal_id: str) -> dict | None:
        """Fetch the overlay decision trace for a single signal.

        Returns the most recent signal_analytics row for the given signal_id,
        or None if no analytics record exists yet.
        """
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                            market_context, market_context_adj,
                            event_adj, event_overlay_json,
                            regime_stability, regime_stability_adj,
                            overlay_adjusted_confidence, context_size_multiplier,
                            execution_grade, decision_trace_json,
                            decision_version, overlay_version,
                            confidence, adjusted_score,
                            was_accepted, rejection_reason,
                            expected_underlying_move_pct, expected_option_move_pct,
                            expected_holding_minutes, reach_prob_json,
                            recommended_target_pct, recommended_stop_pct,
                            recommended_holding_minutes, target_confidence,
                            configured_target_pct, configured_sl_pct,
                            target_realism_pct,
                            expiry_reason, expiry_snapshot_json,
                            option_efficiency_score, delta_efficiency,
                            time_in_profit_minutes, time_in_loss_minutes, time_near_target_minutes
                        FROM signal_analytics
                        WHERE signal_id = :sid
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"sid": signal_id},
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("signal_analytics.get_overlay_failed signal_id=%s: %s", signal_id, exc)
            return None

        if row is None:
            return None

        def _f(v: object) -> float | None:
            return float(v) if v is not None else None

        return {
            "market_context":              row[0],
            "market_context_adj":          _f(row[1]),
            "event_adj":                   _f(row[2]),
            "event_overlay_json":          row[3],
            "regime_stability":            row[4],
            "regime_stability_adj":        _f(row[5]),
            "overlay_adjusted_confidence": _f(row[6]),
            "context_size_multiplier":     _f(row[7]),
            "execution_grade":             row[8],
            "decision_trace_json":         row[9],
            "decision_version":            row[10],
            "overlay_version":             row[11],
            "confidence":                  _f(row[12]),
            "adjusted_score":              _f(row[13]),
            "was_accepted":                bool(row[14]) if row[14] is not None else None,
            "rejection_reason":            row[15],
            # Phase 24 fields
            "expected_underlying_move_pct": _f(row[16]),
            "expected_option_move_pct":     _f(row[17]),
            "expected_holding_minutes":     int(row[18]) if row[18] is not None else None,
            "reach_prob_json":              row[19],
            "recommended_target_pct":       _f(row[20]),
            "recommended_stop_pct":         _f(row[21]),
            "recommended_holding_minutes":  int(row[22]) if row[22] is not None else None,
            "target_confidence":            _f(row[23]),
            "configured_target_pct":        _f(row[24]),
            "configured_sl_pct":            _f(row[25]),
            "target_realism_pct":           _f(row[26]),
            "expiry_reason":                row[27],
            "expiry_snapshot_json":         row[28],
            "option_efficiency_score":      _f(row[29]),
            "delta_efficiency":             _f(row[30]),
            "time_in_profit_minutes":       int(row[31]) if row[31] is not None else None,
            "time_in_loss_minutes":         int(row[32]) if row[32] is not None else None,
            "time_near_target_minutes":     int(row[33]) if row[33] is not None else None,
        }

    async def update_outcome(
        self,
        analytics_id: int,
        outcome: str,
        target_hit: bool,
        stop_hit: bool,
        mfe_pct: float | None,
        mae_pct: float | None,
        current_return_pct: float | None = None,
        return_1h_pct: float | None = None,
        return_1d_pct: float | None = None,
        return_5d_pct: float | None = None,
        time_to_target_minutes: int | None = None,
        time_to_stop_minutes: int | None = None,
        pnl_pct: float | None = None,
        # Phase 24 §3
        target_realism_pct: float | None = None,
        # Phase 24 §5
        option_efficiency_score: float | None = None,
        delta_efficiency: float | None = None,
        gamma_efficiency: float | None = None,
        vega_impact: float | None = None,
        # Phase 24 §8
        time_in_profit_minutes: int | None = None,
        time_in_loss_minutes: int | None = None,
        time_near_target_minutes: int | None = None,
    ) -> None:
        """Update outcome fields for a stored signal analytics record.

        pnl_pct: realized P&L % for the trade.
          WIN  → positive value (target hit return)
          LOSS → negative value (stop loss return)
          If not provided, derived from current_return_pct.
        """
        _pnl = pnl_pct
        if _pnl is None and current_return_pct is not None:
            _pnl = current_return_pct if target_hit else (-abs(current_return_pct) if stop_hit else current_return_pct)

        async with self._sf() as db:
            await db.execute(
                text("""
                    UPDATE signal_analytics SET
                        outcome = :outcome,
                        target_hit = :target_hit,
                        stop_hit = :stop_hit,
                        mfe_pct = :mfe,
                        mae_pct = :mae,
                        pnl_pct = :pnl,
                        current_return_pct = :cur,
                        return_1h_pct = :r1h,
                        return_1d_pct = :r1d,
                        return_5d_pct = :r5d,
                        time_to_target_minutes = :ttt,
                        time_to_stop_minutes = :tts,
                        outcome_checked_at = :now,
                        target_realism_pct = COALESCE(:target_realism_pct, target_realism_pct),
                        option_efficiency_score = COALESCE(:option_efficiency_score, option_efficiency_score),
                        delta_efficiency = COALESCE(:delta_efficiency, delta_efficiency),
                        gamma_efficiency = COALESCE(:gamma_efficiency, gamma_efficiency),
                        vega_impact = COALESCE(:vega_impact, vega_impact),
                        time_in_profit_minutes = COALESCE(:time_in_profit_minutes, time_in_profit_minutes),
                        time_in_loss_minutes = COALESCE(:time_in_loss_minutes, time_in_loss_minutes),
                        time_near_target_minutes = COALESCE(:time_near_target_minutes, time_near_target_minutes)
                    WHERE id = :id
                """),
                {
                    "outcome": outcome, "target_hit": target_hit, "stop_hit": stop_hit,
                    "mfe": mfe_pct, "mae": mae_pct, "pnl": _pnl, "cur": current_return_pct,
                    "r1h": return_1h_pct, "r1d": return_1d_pct, "r5d": return_5d_pct,
                    "ttt": time_to_target_minutes, "tts": time_to_stop_minutes,
                    "now": datetime.now(UTC), "id": analytics_id,
                    "target_realism_pct": target_realism_pct,
                    "option_efficiency_score": option_efficiency_score,
                    "delta_efficiency": delta_efficiency,
                    "gamma_efficiency": gamma_efficiency,
                    "vega_impact": vega_impact,
                    "time_in_profit_minutes": time_in_profit_minutes,
                    "time_in_loss_minutes": time_in_loss_minutes,
                    "time_near_target_minutes": time_near_target_minutes,
                },
            )
            await db.commit()

    async def get_pending_outcome_check(self, max_age_days: int = 5) -> list[dict]:
        """Return accepted signals that need outcome checking within max_age_days.

        Includes signals with no outcome yet (NULL) AND signals still OPEN that
        haven't been rechecked in the last 14 minutes. OPEN signals must be tracked
        continuously so current_return_pct/MFE/MAE stay current throughout the day.
        """
        from datetime import timedelta
        cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff -= timedelta(days=max_age_days)
        recheck_cutoff = datetime.now(UTC) - timedelta(minutes=14)
        async with self._sf() as db:
            result = await db.execute(
                text("""
                    SELECT id, signal_id, ticker, direction, entry_price,
                           stop_loss_price, target_price, created_at,
                           option_entry, option_sl, option_target,
                           option_strike, option_type, option_expiry
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND created_at >= :cutoff
                      AND (
                          outcome IS NULL
                          OR (outcome = 'OPEN' AND (
                              outcome_checked_at IS NULL
                              OR outcome_checked_at < :recheck_cutoff
                          ))
                      )
                    ORDER BY created_at
                    LIMIT 200
                """),
                {"cutoff": cutoff, "recheck_cutoff": recheck_cutoff},
            )
            return [dict(r._mapping) for r in result.fetchall()]

    async def get_option_snapshots_after(
        self,
        underlying: str,
        strike: float,
        option_type: str,
        expiry: str,
        after_ts: datetime,
    ) -> list[dict]:
        """Fetch LTP time series for a specific option contract after a given timestamp.

        Queries option_chain_snapshots — the poller stores these every ~1-2 minutes
        while the market is open, giving a dense enough series for SL/target detection.
        """
        from datetime import date as _date
        expiry_date = expiry if isinstance(expiry, _date) else _date.fromisoformat(expiry[:10])
        async with self._sf() as db:
            result = await db.execute(
                text("""
                    SELECT ltp, captured_at
                    FROM option_chain_snapshots
                    WHERE underlying = :underlying
                      AND strike = :strike
                      AND option_type = :opt_type
                      AND expiry = :expiry
                      AND captured_at > :after_ts
                      AND ltp IS NOT NULL
                    ORDER BY captured_at
                """),
                {
                    "underlying": underlying,
                    "strike":     strike,
                    "opt_type":   option_type,
                    "expiry":     expiry_date,
                    "after_ts":   after_ts,
                },
            )
            return [dict(r._mapping) for r in result.fetchall()]

    async def get_summary_today(self) -> dict:
        """Get today's signal summary for the dashboard."""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END) AS accepted,
                        SUM(CASE WHEN NOT was_accepted THEN 1 ELSE 0 END) AS rejected,
                        COUNT(DISTINCT ticker) AS unique_symbols,
                        COUNT(DISTINCT strategy_type) AS strategies_active,
                        AVG(CASE WHEN was_accepted THEN adjusted_score END) AS avg_score,
                        AVG(CASE WHEN was_accepted THEN confidence END) AS avg_confidence
                    FROM signal_analytics
                    WHERE created_at >= :today
                """),
                {"today": today_start},
            )
            row = r.fetchone()
            if not row:
                return {"total": 0, "accepted": 0, "rejected": 0}
            return {
                "total": int(row.total or 0),
                "accepted": int(row.accepted or 0),
                "rejected": int(row.rejected or 0),
                "unique_symbols": int(row.unique_symbols or 0),
                "strategies_active": int(row.strategies_active or 0),
                "avg_score": round(float(row.avg_score or 0), 1),
                "avg_confidence": round(float(row.avg_confidence or 0), 1),
            }

    async def get_top_symbols_today(self, limit: int = 10) -> list[dict]:
        """Top symbols by acceptance count today."""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._sf() as db:
            result = await db.execute(
                text("""
                    SELECT ticker, sector, is_index,
                           COUNT(*) AS signal_count,
                           AVG(adjusted_score) AS avg_score,
                           AVG(confidence) AS avg_confidence
                    FROM signal_analytics
                    WHERE was_accepted = true AND created_at >= :today
                    GROUP BY ticker, sector, is_index
                    ORDER BY signal_count DESC, avg_score DESC
                    LIMIT :limit
                """),
                {"today": today_start, "limit": limit},
            )
            return [
                {
                    "ticker": r.ticker,
                    "sector": r.sector,
                    "is_index": r.is_index,
                    "signal_count": int(r.signal_count),
                    "avg_score": round(float(r.avg_score or 0), 1),
                    "avg_confidence": round(float(r.avg_confidence or 0), 1),
                }
                for r in result.fetchall()
            ]

    async def get_sector_breakdown_today(self) -> list[dict]:
        """Signal count by sector today."""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._sf() as db:
            result = await db.execute(
                text("""
                    SELECT COALESCE(sector, 'Unknown') AS sector,
                           COUNT(*) AS total,
                           SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END) AS accepted
                    FROM signal_analytics
                    WHERE created_at >= :today AND NOT is_index
                    GROUP BY sector
                    ORDER BY accepted DESC
                """),
                {"today": today_start},
            )
            return [
                {"sector": r.sector, "total": int(r.total), "accepted": int(r.accepted)}
                for r in result.fetchall()
            ]
