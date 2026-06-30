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
        """Compute outcome for one signal analytics record. Returns None if insufficient data.

        Routes to option-price tracking when the signal has option fields populated
        (option_entry, option_sl, option_target, option_strike, option_type, option_expiry).
        Falls back to stock-candle tracking when option data is absent.
        """
        created_at = record.get("created_at")
        if not created_at:
            return None

        created_ts = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at))
        if created_ts.tzinfo is None:
            created_ts = created_ts.replace(tzinfo=UTC)

        # Route to option tracking when all option fields are present
        has_option_data = all(
            record.get(f) is not None
            for f in ("option_entry", "option_sl", "option_target", "option_strike", "option_type", "option_expiry")
        )
        if has_option_data:
            return await self._compute_option_outcome(record, created_ts)

        return await self._compute_stock_outcome(record, created_ts)

    async def _compute_option_outcome(self, record: dict, created_ts: datetime) -> dict | None:
        """Track outcome using option_chain_snapshots LTP time series.

        Both CE (LONG signals) and PE (SHORT signals) are bought options, so:
          MFE = (max_ltp - entry) / entry * 100   (option goes up = favourable)
          MAE = (entry - min_ltp) / entry * 100   (option goes down = adverse)
          target_hit when ltp >= option_target
          stop_hit   when ltp <= option_sl
        """
        ticker      = record["ticker"]
        opt_entry   = float(record["option_entry"])
        opt_sl      = float(record["option_sl"])
        opt_target  = float(record["option_target"])
        opt_strike  = float(record["option_strike"])
        opt_type    = str(record["option_type"])
        opt_expiry  = record["option_expiry"]
        opt_expiry_str = opt_expiry.isoformat() if hasattr(opt_expiry, "isoformat") else str(opt_expiry)[:10]

        snapshots = await self._analytics.get_option_snapshots_after(
            underlying=ticker,
            strike=opt_strike,
            option_type=opt_type,
            expiry=opt_expiry_str,
            after_ts=created_ts,
        )

        now_ts = datetime.now(UTC)

        # Need at least 2 snapshots to compute meaningful metrics
        if len(snapshots) < 2:
            # Check if option has expired — mark EXPIRED rather than keep OPEN forever
            from datetime import date as _date
            expiry_date = opt_expiry if isinstance(opt_expiry, _date) else _date.fromisoformat(opt_expiry_str)
            if now_ts.date() > expiry_date:
                return {
                    "outcome": "EXPIRED", "target_hit": False, "stop_hit": False,
                    "mfe_pct": None, "mae_pct": None, "current_return_pct": None,
                    "return_1h_pct": None, "return_1d_pct": None, "return_5d_pct": None,
                    "time_to_target_minutes": None, "time_to_stop_minutes": None,
                }
            return None

        # Filter zero/null LTPs — they represent poller misses (no trade data returned
        # from API at that timestamp), not a real option price of ₹0.
        valid_snaps = [(float(s["ltp"]), s["captured_at"]) for s in snapshots if float(s.get("ltp") or 0) > 0]
        if len(valid_snaps) < 2:
            return None
        ltps, timestamps = zip(*valid_snaps)
        ltps = list(ltps)
        timestamps = list(timestamps)
        if timestamps[0].tzinfo is None:
            timestamps = [t.replace(tzinfo=UTC) for t in timestamps]

        max_ltp = max(ltps)
        min_ltp = min(ltps)
        mfe_pct = (max_ltp - opt_entry) / opt_entry * 100
        mae_pct = (opt_entry - min_ltp) / opt_entry * 100 if min_ltp < opt_entry else 0.0

        # Scan chronologically for SL / target hit
        target_hit = False
        stop_hit   = False
        ttt_minutes: int | None = None
        tts_minutes: int | None = None

        for ltp, ts in zip(ltps, timestamps):
            elapsed = int((ts - created_ts).total_seconds() / 60)
            if ltp >= opt_target and not target_hit:
                target_hit  = True
                ttt_minutes = elapsed
            if ltp <= opt_sl and not stop_hit:
                stop_hit    = True
                tts_minutes = elapsed

        # Fixed-interval returns from snapshot timestamps
        return_1h  = self._return_at_offset(ltps, timestamps, created_ts, minutes=60,   entry=opt_entry)
        return_1d  = self._return_at_offset(ltps, timestamps, created_ts, minutes=390,  entry=opt_entry)  # ~6.5h session
        return_5d  = self._return_at_offset(ltps, timestamps, created_ts, minutes=1950, entry=opt_entry)  # 5 sessions

        current_return_pct = round((ltps[-1] - opt_entry) / opt_entry * 100, 4)

        # ── Phase 24 §5+8: Option Efficiency + Time Analytics ─────────────
        ph24 = self._compute_phase24_option_metrics(
            ltps, timestamps, opt_entry, opt_target, opt_sl, created_ts
        )

        # Determine outcome
        if target_hit and (not stop_hit or (ttt_minutes or 99999) < (tts_minutes or 99999)):
            outcome = "WIN"
        elif stop_hit:
            outcome = "LOSS"
        else:
            from datetime import date as _date
            expiry_date = opt_expiry if isinstance(opt_expiry, _date) else _date.fromisoformat(opt_expiry_str)
            if now_ts.date() > expiry_date:
                outcome = "PARTIAL" if mfe_pct > 1.0 else "EXPIRED"
            else:
                age_days = (now_ts - created_ts).days
                if age_days >= _MAX_LOOK_AHEAD_DAYS:
                    outcome = "PARTIAL" if mfe_pct > 1.0 else "EXPIRED"
                else:
                    outcome = "OPEN"

        # Phase 24 §3: target realism (only meaningful for settled outcomes)
        target_realism = None
        if outcome in ("WIN", "LOSS", "PARTIAL", "EXPIRED") and mfe_pct is not None:
            configured_tgt_pct = (opt_target - opt_entry) / opt_entry * 100
            if configured_tgt_pct > 0:
                target_realism = round(mfe_pct / configured_tgt_pct * 100, 2)

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
            # Phase 24 additions
            "target_realism_pct":       target_realism,
            **ph24,
        }

    async def _compute_stock_outcome(self, record: dict, created_ts: datetime) -> dict | None:
        """Fallback: track outcome using underlying stock 15m candles."""
        ticker      = record["ticker"]
        entry_price = record.get("entry_price")
        stop_price  = record.get("stop_loss_price")
        tgt_price   = record.get("target_price")

        if not entry_price:
            return None

        entry = float(entry_price)
        stop  = float(stop_price) if stop_price else None
        tgt   = float(tgt_price) if tgt_price else None
        direction = record.get("direction", "LONG")

        candles = await self._history.get_latest(ticker, "15m", _CANDLES_FORWARD + 5)
        if len(candles) < 3:
            return None

        forward_candles = [c for c in candles if c.ts > created_ts]
        if len(forward_candles) < 2:
            return None

        closes  = [float(c.close) for c in forward_candles]
        highs   = [float(c.high)  for c in forward_candles]
        lows    = [float(c.low)   for c in forward_candles]
        now_ts  = datetime.now(UTC)

        if direction == "LONG":
            mfe_pct = (max(highs) - entry) / entry * 100 if highs else 0.0
            mae_pct = (entry - min(lows)) / entry * 100  if lows  else 0.0
        else:
            mfe_pct = (entry - min(lows)) / entry * 100  if lows  else 0.0
            mae_pct = (max(highs) - entry) / entry * 100 if highs else 0.0

        candle_15m_count = len(forward_candles)
        return_1h  = self._return_after_n_candles(closes, 4,  direction, entry)
        return_1d  = self._return_after_n_candles(closes, 26, direction, entry)
        return_5d  = self._return_after_n_candles(closes, min(130, candle_15m_count - 1), direction, entry)

        target_hit  = False
        stop_hit    = False
        ttt_minutes = None
        tts_minutes = None

        for i, (h, l, _c_ts) in enumerate(zip(highs, lows, [fc.ts for fc in forward_candles])):
            bar_minutes = (i + 1) * 15
            if direction == "LONG":
                if tgt and h >= tgt and not target_hit:
                    target_hit  = True
                    ttt_minutes = bar_minutes
                if stop and l <= stop and not stop_hit:
                    stop_hit    = True
                    tts_minutes = bar_minutes
            else:
                if tgt and l <= tgt and not target_hit:
                    target_hit  = True
                    ttt_minutes = bar_minutes
                if stop and h >= stop and not stop_hit:
                    stop_hit    = True
                    tts_minutes = bar_minutes

        latest_price = closes[-1]
        if direction == "LONG":
            current_return_pct = round((latest_price - entry) / entry * 100, 4)
        else:
            current_return_pct = round((entry - latest_price) / entry * 100, 4)

        if target_hit and (not stop_hit or (ttt_minutes or 99999) < (tts_minutes or 99999)):
            outcome = "WIN"
        elif stop_hit:
            outcome = "LOSS"
        else:
            age_days = (now_ts - created_ts).days
            if age_days >= _MAX_LOOK_AHEAD_DAYS:
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
    def _compute_phase24_option_metrics(
        ltps: list[float],
        timestamps: list[datetime],
        opt_entry: float,
        opt_target: float,
        opt_sl: float,
        created_ts: datetime,
    ) -> dict:
        """Phase 24 §5+8: Option efficiency and holding time metrics.

        Computes from the LTP time series:
          option_efficiency_score  — premium responsiveness (option_move% / expected 10× move)
          delta_efficiency         — fraction of moves that tracked direction
          time_in_profit_minutes   — cumulative bars where LTP > entry
          time_in_loss_minutes     — cumulative bars where LTP < entry
          time_near_target_minutes — cumulative bars within 10% of target
        """
        if not ltps or len(ltps) < 2:
            return {}

        n = len(ltps)
        time_in_profit = 0
        time_in_loss   = 0
        time_near_tgt  = 0
        direction_hits  = 0        # snapshots where LTP moved UP vs previous
        total_moves     = 0

        near_tgt_threshold = opt_target * 0.90   # within 10% of target

        for i in range(1, n):
            ltp  = ltps[i]
            prev = ltps[i - 1]
            # Approximate interval (we don't have exact gap, use 2-min average)
            interval_min = 2
            if i < len(timestamps) and i - 1 < len(timestamps):
                elapsed = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60.0
                interval_min = max(1, min(30, int(elapsed)))

            if ltp > opt_entry:
                time_in_profit += interval_min
            elif ltp < opt_entry:
                time_in_loss += interval_min

            if ltp >= near_tgt_threshold:
                time_near_tgt += interval_min

            if ltp != prev:
                total_moves += 1
                if ltp > prev:
                    direction_hits += 1

        # Option efficiency: best premium move / entry × premium responsiveness ratio
        max_ltp = max(ltps)
        max_move_pct = (max_ltp - opt_entry) / opt_entry * 100 if opt_entry > 0 else 0
        # Rule of thumb: ATM option should move ~10× underlying % for 29 DTE
        # efficiency > 1 = outperformed, < 1 = underperformed
        option_efficiency_score = round(max_move_pct / max(1.0, max_move_pct), 4)

        # Delta efficiency: % of price moves that went in the right direction
        delta_eff = round(direction_hits / total_moves, 4) if total_moves > 0 else None

        return {
            "option_efficiency_score":  option_efficiency_score,
            "delta_efficiency":         delta_eff,
            "gamma_efficiency":         None,   # requires underlying candles to compute
            "vega_impact":              None,   # requires IV time series
            "time_in_profit_minutes":   time_in_profit,
            "time_in_loss_minutes":     time_in_loss,
            "time_near_target_minutes": time_near_tgt,
        }

    @staticmethod
    def _return_at_offset(
        ltps: list[float],
        timestamps: list[datetime],
        created_ts: datetime,
        minutes: int,
        entry: float,
    ) -> float | None:
        """Return % change at the snapshot closest to `minutes` after signal creation."""
        target_ts = created_ts + timedelta(minutes=minutes)
        # Find last snapshot at or before the target timestamp
        best_ltp = None
        for ltp, ts in zip(ltps, timestamps):
            if ts <= target_ts:
                best_ltp = ltp
            else:
                break
        if best_ltp is None:
            return None
        return round((best_ltp - entry) / entry * 100, 4)

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
