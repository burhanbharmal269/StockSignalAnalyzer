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

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from core.application.services.execution_lock_service import ExecutionLockService
    from core.application.services.option_strike_selector import OptionPlay
    from core.domain.value_objects.signal_request import SignalRequest
    from core.domain.value_objects.signal_result import SignalResult

_log = logging.getLogger(__name__)


class SignalAnalyticsService:
    """Persists signal analytics for every scanner result, regardless of outcome."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        execution_lock_service: "ExecutionLockService | None" = None,
    ) -> None:
        self._sf = session_factory
        self._execution_lock = execution_lock_service

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
    ) -> None:
        """Record one scanner result to signal_analytics. Never raises — fail-open."""
        try:
            execution_mode = await self._get_execution_mode()
            await self._insert(
                symbol_name, exchange, is_index, sector,
                request, result, features, execution_mode,
                option_play=option_play,
            )
        except Exception as exc:
            _log.warning("signal_analytics.record_failed symbol=%s: %s", symbol_name, exc)

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

            "raw_score": None,
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
        }

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
                        was_accepted, rejection_reason,
                        option_type, option_strike, option_expiry, option_symbol,
                        option_entry, option_sl, option_target
                    ) VALUES (
                        :signal_id, :ticker, :exchange, :direction, :strategy_type, :regime,
                        :sector, :is_index, :execution_mode,
                        :entry_price, :stop_loss_price, :target_price, :lot_size, :dte,
                        :raw_score, :adjusted_score, :confidence,
                        :trend_score, :volume_score, :vwap_score, :oi_score,
                        :sentiment_score, :iv_score, :option_chain_score,
                        :adx_at_signal, :volume_ratio_at_signal, :rsi_at_signal,
                        :was_accepted, :rejection_reason,
                        :option_type, :option_strike, :option_expiry, :option_symbol,
                        :option_entry, :option_sl, :option_target
                    )
                """),
                params,
            )
            await db.commit()

        _log.debug(
            "signal_analytics.recorded symbol=%s accepted=%s rejection=%s",
            ticker, result.accepted, rejection,
        )

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
    ) -> None:
        """Update outcome fields for a stored signal analytics record."""
        async with self._sf() as db:
            await db.execute(
                text("""
                    UPDATE signal_analytics SET
                        outcome = :outcome,
                        target_hit = :target_hit,
                        stop_hit = :stop_hit,
                        mfe_pct = :mfe,
                        mae_pct = :mae,
                        current_return_pct = :cur,
                        return_1h_pct = :r1h,
                        return_1d_pct = :r1d,
                        return_5d_pct = :r5d,
                        time_to_target_minutes = :ttt,
                        time_to_stop_minutes = :tts,
                        outcome_checked_at = :now
                    WHERE id = :id
                """),
                {
                    "outcome": outcome, "target_hit": target_hit, "stop_hit": stop_hit,
                    "mfe": mfe_pct, "mae": mae_pct, "cur": current_return_pct,
                    "r1h": return_1h_pct, "r1d": return_1d_pct, "r5d": return_5d_pct,
                    "ttt": time_to_target_minutes, "tts": time_to_stop_minutes,
                    "now": datetime.now(UTC), "id": analytics_id,
                },
            )
            await db.commit()

    async def get_pending_outcome_check(self, max_age_days: int = 5) -> list[dict]:
        """Return accepted signals not yet outcome-checked, within max_age_days."""
        cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        cutoff -= timedelta(days=max_age_days)
        async with self._sf() as db:
            result = await db.execute(
                text("""
                    SELECT id, signal_id, ticker, direction, entry_price,
                           stop_loss_price, target_price, created_at
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NULL
                      AND created_at >= :cutoff
                    ORDER BY created_at
                    LIMIT 200
                """),
                {"cutoff": cutoff},
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
