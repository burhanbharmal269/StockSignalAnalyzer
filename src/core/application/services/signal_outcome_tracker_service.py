"""SignalOutcomeTrackerService — tracks signal outcomes without requiring order execution.

Runs as a background task (every 15 minutes). For every accepted signal that
hasn't been outcome-checked yet:

1. Fetches historical candles from signal creation time forward.
2. Computes:
   - MFE (Maximum Favorable Excursion) %
   - MAE (Maximum Adverse Excursion) %
   - Return at 1h, 1d, 5d
   - Whether target was hit
   - Whether stop was hit
   - Time to target / stop in minutes
3. Determines outcome: WIN / LOSS / OPEN / EXPIRED
4. Updates signal_analytics record.

This runs regardless of execution mode. Even when execution_mode=MANUAL and no
orders are placed, outcome tracking gives real performance data for strategy
improvement.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.market_data.historical_data_service import HistoricalDataService
    from core.application.services.signal_analytics_service import SignalAnalyticsService

_log = logging.getLogger(__name__)

_TRACK_INTERVAL_SECS = 900   # 15 minutes
_CANDLES_FORWARD = 50        # how many 15m candles to look ahead (50 × 15m = 12.5h)
_MAX_LOOK_AHEAD_DAYS = 5


class SignalOutcomeTrackerService:
    """Background service: checks price progress for accepted signals.

    Computes MFE/MAE and return metrics without needing an order or position.
    """

    def __init__(
        self,
        analytics_svc: "SignalAnalyticsService",
        historical_svc: "HistoricalDataService",
    ) -> None:
        self._analytics = analytics_svc
        self._history   = historical_svc
        self._running   = False

    async def run(self) -> None:
        """Background loop — registered with BackgroundTaskRegistry."""
        self._running = True
        _log.info("outcome_tracker.started interval_secs=%d", _TRACK_INTERVAL_SECS)
        while self._running:
            try:
                await self._check_pending_outcomes()
            except Exception:
                _log.exception("outcome_tracker.cycle_error")
            await asyncio.sleep(_TRACK_INTERVAL_SECS)

    async def run_once(self) -> dict:
        """Run a single outcome-check cycle. Used by API trigger and tests."""
        return await self._check_pending_outcomes()

    def stop(self) -> None:
        self._running = False

    async def _check_pending_outcomes(self) -> dict:
        pending = await self._analytics.get_pending_outcome_check(max_age_days=_MAX_LOOK_AHEAD_DAYS)
        _log.info("outcome_tracker.cycle pending=%d", len(pending))

        updated = skipped = errors = 0
        for record in pending:
            try:
                result = await self._compute_outcome(record)
                if result is None:
                    skipped += 1
                    continue
                await self._analytics.update_outcome(
                    analytics_id=record["id"],
                    **result,
                )
                updated += 1
            except Exception as exc:
                errors += 1
                _log.debug(
                    "outcome_tracker.symbol_error id=%s ticker=%s: %s",
                    record.get("id"), record.get("ticker"), exc,
                )

        _log.info(
            "outcome_tracker.cycle_done updated=%d skipped=%d errors=%d",
            updated, skipped, errors,
        )
        return {"updated": updated, "skipped": skipped, "errors": errors}

    async def _compute_outcome(self, record: dict) -> dict | None:
        """Compute outcome for one signal analytics record. Returns None if insufficient data."""
        ticker      = record["ticker"]
        entry_price = record.get("entry_price")
        stop_price  = record.get("stop_loss_price")
        tgt_price   = record.get("target_price")
        created_at  = record.get("created_at")

        if not entry_price or not created_at:
            return None

        entry = float(entry_price)
        stop  = float(stop_price) if stop_price else None
        tgt   = float(tgt_price) if tgt_price else None

        # Determine direction from stored value (default LONG if unknown)
        direction = record.get("direction", "LONG")

        # Get candles from signal creation time
        candles = await self._history.get_latest(ticker, "15m", _CANDLES_FORWARD + 5)
        if len(candles) < 3:
            return None

        # Find candles AFTER signal creation
        created_ts = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at))
        if created_ts.tzinfo is None:
            created_ts = created_ts.replace(tzinfo=UTC)

        forward_candles = [c for c in candles if c.ts > created_ts]
        if len(forward_candles) < 2:
            return None

        closes  = [float(c.close) for c in forward_candles]
        highs   = [float(c.high)  for c in forward_candles]
        lows    = [float(c.low)   for c in forward_candles]
        now_ts  = datetime.now(UTC)

        # MFE / MAE
        if direction == "LONG":
            mfe_pct = (max(highs) - entry) / entry * 100 if highs else 0.0
            mae_pct = (entry - min(lows)) / entry * 100  if lows  else 0.0
        else:
            mfe_pct = (entry - min(lows)) / entry * 100  if lows  else 0.0
            mae_pct = (max(highs) - entry) / entry * 100 if highs else 0.0

        # Returns at fixed intervals
        candle_15m_count   = len(forward_candles)
        return_1h  = self._return_after_n_candles(closes, 4,  direction, entry)   # 4 × 15m = 1h
        return_1d  = self._return_after_n_candles(closes, 26, direction, entry)   # 26 × 15m ≈ 6.5h (1 session)
        return_5d  = self._return_after_n_candles(closes, min(130, candle_15m_count - 1), direction, entry)

        # Target / stop hit detection
        target_hit   = False
        stop_hit     = False
        ttt_minutes  = None  # time to target
        tts_minutes  = None  # time to stop

        for i, (h, l, c_ts) in enumerate(zip(highs, lows, [fc.ts for fc in forward_candles])):
            bar_minutes = (i + 1) * 15
            if direction == "LONG":
                if tgt and h >= tgt and not target_hit:
                    target_hit   = True
                    ttt_minutes  = bar_minutes
                if stop and l <= stop and not stop_hit:
                    stop_hit     = True
                    tts_minutes  = bar_minutes
            else:
                if tgt and l <= tgt and not target_hit:
                    target_hit   = True
                    ttt_minutes  = bar_minutes
                if stop and h >= stop and not stop_hit:
                    stop_hit     = True
                    tts_minutes  = bar_minutes

        # Current return (latest close vs entry)
        latest_price = closes[-1]
        if direction == "LONG":
            current_return_pct = round((latest_price - entry) / entry * 100, 4)
        else:
            current_return_pct = round((entry - latest_price) / entry * 100, 4)

        # Determine outcome
        if target_hit and (not stop_hit or (ttt_minutes or 99999) < (tts_minutes or 99999)):
            outcome = "WIN"
        elif stop_hit:
            outcome = "LOSS"
        else:
            age_days = (now_ts - created_ts).days
            if age_days >= _MAX_LOOK_AHEAD_DAYS:
                # PARTIAL: moved favourably (MFE > 0.5%) but never hit target
                outcome = "PARTIAL" if mfe_pct > 0.5 else "EXPIRED"
            else:
                outcome = "OPEN"

        return {
            "outcome":                outcome,
            "target_hit":             target_hit,
            "stop_hit":               stop_hit,
            "mfe_pct":                round(mfe_pct, 4),
            "mae_pct":                round(mae_pct, 4),
            "current_return_pct":     current_return_pct,
            "return_1h_pct":          return_1h,
            "return_1d_pct":          return_1d,
            "return_5d_pct":          return_5d,
            "time_to_target_minutes": ttt_minutes,
            "time_to_stop_minutes":   tts_minutes,
        }

    @staticmethod
    def _return_after_n_candles(
        closes: list[float],
        n: int,
        direction: str,
        entry: float,
    ) -> float | None:
        if len(closes) < n:
            return None
        price_at_n = closes[n - 1]
        if direction == "LONG":
            return round((price_at_n - entry) / entry * 100, 4)
        else:
            return round((entry - price_at_n) / entry * 100, 4)
