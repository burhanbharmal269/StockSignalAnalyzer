"""SignalScannerService — periodic signal generation trigger.

The missing link: runs every 5 minutes during market hours, fetches candles
for each universe symbol, computes technical features, and calls
SignalEngineService.process() for each candidate.

Architecture:
  Universe symbols → candles → FeatureSnapshot → ScoreContext →
  SignalRequest → SignalEngineService (Score → Confidence → Risk → Signal)

Phase 4 — Runtime Tracing:
  Every step emits a structured log so the pipeline can be validated without
  adding instrumentation to the domain layer.  Log prefix: signal_scanner.*
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.market_data.historical_data_service import HistoricalDataService
    from core.application.services.market_universe_service import MarketUniverseService
    from core.application.services.signal_analytics_service import SignalAnalyticsService
    from core.application.services.signal_engine_service import SignalEngineService

_log = logging.getLogger(__name__)

_SCAN_INTERVAL_SECS  = 300   # 5 minutes
_IST_OFFSET          = timedelta(hours=5, minutes=30)
_MARKET_OPEN         = (9, 15)
_MARKET_CLOSE        = (15, 30)
_CANDLE_LIMIT        = 200   # bars to fetch per symbol
_MAX_CONCURRENT      = 10    # simultaneous candle fetches (rate-limit Kite API)
_CYCLE_BATCH_SIZE    = 50    # symbols per cycle — rotated randomly each run


def _ist_now() -> datetime:
    return datetime.now(UTC) + _IST_OFFSET


def _is_market_hours() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:           # Sat/Sun
        return False
    t = (now.hour, now.minute)
    return _MARKET_OPEN <= t <= _MARKET_CLOSE


def _next_monthly_expiry() -> date:
    """Return the last Thursday of the current or next month (NSE F&O expiry)."""
    today = _ist_now().date()
    for month_offset in range(3):
        year = today.year + (today.month + month_offset - 1) // 12
        month = (today.month + month_offset - 1) % 12 + 1
        last_day = date(year, month, 28)
        while last_day.weekday() != 3:  # 3 = Thursday
            last_day += timedelta(days=1)
        candidate = last_day
        while True:
            nxt = candidate + timedelta(days=7)
            if nxt.month != month:
                break
            candidate = nxt
        if candidate >= today:
            return candidate
    return today + timedelta(days=30)


def _compute_features(candles) -> dict:
    """Compute technical indicators from candle list. Returns indicator dict."""
    if len(candles) < 20:
        return {}
    try:
        import pandas as pd
        import ta

        closes = [float(c.close) for c in candles]
        highs  = [float(c.high)  for c in candles]
        lows   = [float(c.low)   for c in candles]
        vols   = [float(c.volume) for c in candles]

        df = pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": vols})

        # ADX / DI+/-
        adx_ind = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
        adx      = adx_ind.adx().iloc[-1]
        di_plus  = adx_ind.adx_pos().iloc[-1]
        di_minus = adx_ind.adx_neg().iloc[-1]

        # EMAs
        ema_20  = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
        ema_50  = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1] if len(df) >= 50 else None
        ema_200 = ta.trend.EMAIndicator(df["close"], window=200).ema_indicator().iloc[-1] if len(df) >= 200 else None

        # ATR
        atr = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range().iloc[-1]

        # RSI
        rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi().iloc[-1]

        # Bollinger Band width percentile (rolling)
        bb = ta.volatility.BollingerBands(df["close"], window=20)
        bb_width = bb.bollinger_wband().iloc[-1]
        bb_width_series = bb.bollinger_wband().dropna()
        bb_pct = float((bb_width_series < bb_width).sum()) / len(bb_width_series) if len(bb_width_series) > 0 else 0.5

        # Volume ratio (current / 20-bar avg)
        vol_avg   = df["volume"].rolling(20).mean().iloc[-1]
        vol_ratio = float(df["volume"].iloc[-1]) / float(vol_avg) if vol_avg > 0 else 1.0

        # Approx VWAP
        tp   = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (tp * df["volume"]).sum() / df["volume"].sum() if df["volume"].sum() > 0 else closes[-1]

        close      = closes[-1]
        prev_close = closes[-2] if len(closes) > 1 else close

        price_change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0.0

        vwap_std              = float(df["close"].rolling(20).std().iloc[-1]) or 1.0
        vwap_deviation_sigma  = (close - float(vwap)) / vwap_std if vwap_std else 0.0

        # Supertrend approximation (sign of (close - VWAP))
        supertrend_direction = 1 if close > float(vwap) else -1

        return {
            "close": close,
            "adx": float(adx) if adx == adx else None,
            "di_plus": float(di_plus) if di_plus == di_plus else None,
            "di_minus": float(di_minus) if di_minus == di_minus else None,
            "ema_20": float(ema_20) if ema_20 == ema_20 else None,
            "ema_50": float(ema_50) if ema_50 and ema_50 == ema_50 else None,
            "ema_200": float(ema_200) if ema_200 and ema_200 == ema_200 else None,
            "atr": float(atr) if atr == atr else None,
            "rsi_14": float(rsi) if rsi == rsi else None,
            "bb_width_percentile": float(bb_pct),
            "volume_ratio": float(vol_ratio),
            "vwap": float(vwap),
            "price_change_pct": float(price_change_pct),
            "vwap_deviation_sigma": float(vwap_deviation_sigma),
            "supertrend_direction": supertrend_direction,
        }
    except Exception as exc:
        _log.debug("feature_compute error: %s", exc)
        return {}


def _classify_regime(f: dict):
    """Classify market regime from features."""
    from core.domain.enums.market_regime import MarketRegime
    adx    = f.get("adx") or 0
    di_p   = f.get("di_plus") or 0
    di_m   = f.get("di_minus") or 0
    bb_pct = f.get("bb_width_percentile") or 0.5

    if adx > 30:
        return MarketRegime.TRENDING_BULLISH if di_p > di_m else MarketRegime.TRENDING_BEARISH
    if bb_pct > 0.8:
        return MarketRegime.HIGH_VOLATILITY
    if adx < 15 and bb_pct < 0.3:
        return MarketRegime.LOW_VOLATILITY
    return MarketRegime.SIDEWAYS


def _pick_strategy(regime):
    """Pick strategy type that fits the current regime."""
    from core.domain.enums.market_regime import MarketRegime
    from core.domain.enums.strategy_type import StrategyType
    return {
        MarketRegime.TRENDING_BULLISH:  StrategyType.DIRECTIONAL,
        MarketRegime.TRENDING_BEARISH:  StrategyType.DIRECTIONAL,
        MarketRegime.HIGH_VOLATILITY:   StrategyType.VOLATILITY,
        MarketRegime.SIDEWAYS:          StrategyType.MEAN_REVERSION,
        MarketRegime.LOW_VOLATILITY:    StrategyType.BREAKOUT,
    }.get(regime, StrategyType.DIRECTIONAL)


def _build_signal_request(symbol: str, token: int, lot_size: int, f: dict, regime, strategy, is_index: bool = False):
    """Build SignalRequest from features. Returns None if inputs are insufficient."""
    from core.domain.enums.asset_type import AssetType
    from core.domain.enums.instrument_class import InstrumentClass
    from core.domain.value_objects.feature_snapshot import FeatureSnapshot
    from core.domain.value_objects.score_context import ScoreContext
    from core.domain.value_objects.signal_request import SignalRequest

    close = f.get("close")
    atr   = f.get("atr")
    if not close or not atr or atr <= 0:
        return None

    # ATR-based entry / stop / target (1.5× ATR stop, 3× ATR target → RR=2.0)
    entry = Decimal(str(round(close, 2)))
    atr_d = Decimal(str(round(atr, 2)))
    stop  = entry - atr_d * Decimal("1.5")
    tgt   = entry + atr_d * Decimal("3.0")

    expiry = _next_monthly_expiry()
    dte    = max((expiry - _ist_now().date()).days, 1)

    # Scoring engine uses detailed InstrumentClass for performance stats lookup
    score_instrument_class = InstrumentClass.INDEX_FUTURE if is_index else InstrumentClass.STOCK_FUTURE

    snap = FeatureSnapshot(
        instrument_token=token,
        timeframe="15m",
        adx=f.get("adx"),
        di_plus=f.get("di_plus"),
        di_minus=f.get("di_minus"),
        ema_20=f.get("ema_20"),
        ema_50=f.get("ema_50"),
        ema_200=f.get("ema_200"),
        close_price=close,
        atr=atr,
        bb_width_percentile=f.get("bb_width_percentile"),
        vwap=f.get("vwap"),
        supertrend_direction=f.get("supertrend_direction"),
    )

    ctx = ScoreContext(
        instrument_token=token,
        timeframe="15m",
        regime=regime,
        features=snap,
        volume_ratio=f.get("volume_ratio"),
        rsi_14=f.get("rsi_14"),
        price_change_pct=f.get("price_change_pct"),
        vwap_deviation_sigma=f.get("vwap_deviation_sigma"),
        instrument_class=score_instrument_class,
        dte=dte,
    )

    # RiskRequest only accepts "FUTURE" or "OPTION" — not "STOCK_FUTURE"/"INDEX_FUTURE"
    return SignalRequest(
        instrument_token=token,
        underlying=symbol,
        instrument_class="FUTURE",
        expiry_date=expiry,
        strategy_type=strategy,
        asset_type=AssetType.FNO,
        regime=regime,
        score_context=ctx,
        entry_price=entry,
        stop_loss_price=stop,
        target_price=tgt,
        option_premium=None,
        lot_size=lot_size,
        dte=dte,
        atr_14=atr,
        correlation_id=f"scan:{symbol}:{_ist_now().strftime('%Y%m%d%H%M')}",
    )


class SignalScannerService:
    """Background scanner: universe → features → signals every 5 minutes.

    Phase 4 tracing: every pipeline step emits a structured log entry so the
    execution can be verified without a debugger.
    """

    def __init__(
        self,
        universe_svc: "MarketUniverseService",
        historical_svc: "HistoricalDataService",
        signal_engine: "SignalEngineService",
        analytics_svc: "SignalAnalyticsService | None" = None,
    ) -> None:
        self._universe  = universe_svc
        self._history   = historical_svc
        self._engine    = signal_engine
        self._analytics = analytics_svc
        self._running   = False

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Continuous scan loop — registered with BackgroundTaskRegistry."""
        self._running = True
        _log.info(
            "signal_scanner.started interval_secs=%d market_open=%s market_close=%s",
            _SCAN_INTERVAL_SECS, _MARKET_OPEN, _MARKET_CLOSE,
        )
        while self._running:
            if _is_market_hours():
                _log.info("signal_scanner.market_hours — starting scan cycle")
                try:
                    result = await self._scan_cycle()
                    _log.info(
                        "signal_scanner.cycle_done accepted=%d rejected=%d errors=%d",
                        result["accepted"], result["rejected"], result["errors"],
                    )
                except Exception:
                    _log.exception("signal_scanner.cycle_error")
            else:
                now_ist = _ist_now()
                _log.debug(
                    "signal_scanner.outside_market_hours ist=%s weekday=%s — sleeping %ds",
                    now_ist.strftime("%H:%M"), now_ist.strftime("%A"), _SCAN_INTERVAL_SECS,
                )
            await asyncio.sleep(_SCAN_INTERVAL_SECS)

    # ------------------------------------------------------------------
    # Manual trigger (no market-hours gate — for testing and API endpoint)
    # ------------------------------------------------------------------

    async def scan_now(self) -> dict:
        """Run a single scan cycle immediately.

        Does NOT check market hours — useful for testing and the POST /scan endpoint.
        """
        _log.info("signal_scanner.scan_now triggered manually")
        return await self._scan_cycle()

    # ------------------------------------------------------------------
    # Core scan cycle
    # ------------------------------------------------------------------

    async def _scan_cycle(self) -> dict:
        # ── TRACE 1: Universe load ────────────────────────────────────
        # get_active_symbols(fo_only=True) returns BOTH index futures (is_fo=True,
        # is_index=True) AND F&O stocks (is_fo=True, is_index=False)
        all_symbols = await self._universe.get_active_symbols(fo_only=True)
        index_futures = [s for s in all_symbols if s.is_index]
        fo_stocks     = [s for s in all_symbols if not s.is_index]

        # Shuffle F&O stocks each cycle so different sectors get evaluated
        shuffled_stocks = list(fo_stocks)
        random.shuffle(shuffled_stocks)

        # Index futures always evaluated first (small, high-importance set)
        # Then a rotating batch of F&O stocks up to CYCLE_BATCH_SIZE
        batch_stocks = shuffled_stocks[:max(_CYCLE_BATCH_SIZE - len(index_futures), 0)]
        candidates   = index_futures + batch_stocks

        _log.info(
            "signal_scanner.universe_loaded "
            "total_fo=%d index_futures=%d fo_stocks=%d scanning=%d "
            "(stock_batch=%d shuffled=%s)",
            len(all_symbols),
            len(index_futures),
            len(fo_stocks),
            len(candidates),
            len(batch_stocks),
            "yes",
        )

        if not candidates:
            _log.warning("signal_scanner.no_candidates — universe empty or no F&O symbols")
            return {"accepted": 0, "rejected": 0, "errors": 0, "candidates": 0}

        # ── TRACE 2: Concurrent processing with rate-limit semaphore ──
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        accepted = rejected = errors = 0
        results  = await asyncio.gather(
            *[self._process_symbol_sem(sym, semaphore) for sym in candidates],
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                errors += 1
            elif res == "accepted":
                accepted += 1
            elif res == "rejected":
                rejected += 1
            else:
                errors += 1

        _log.info(
            "signal_scanner.cycle_summary accepted=%d rejected=%d errors=%d candidates=%d",
            accepted, rejected, errors, len(candidates),
        )
        return {
            "accepted":   accepted,
            "rejected":   rejected,
            "errors":     errors,
            "candidates": len(candidates),
        }

    async def _process_symbol_sem(self, sym, semaphore: asyncio.Semaphore) -> str:
        async with semaphore:
            return await self._process_symbol(sym)

    async def _process_symbol(self, sym) -> str:
        """Process one universe symbol through the full pipeline. Returns 'accepted'/'rejected'/'error'."""
        symbol   = sym.symbol
        sym_type = "INDEX" if sym.is_index else "STOCK"

        # ── TRACE 2: Historical candles ───────────────────────────────
        candles = await self._history.get_latest(symbol, "15m", _CANDLE_LIMIT)
        if len(candles) < 20:
            _log.debug(
                "signal_scanner.skip symbol=%s reason=insufficient_candles count=%d",
                symbol, len(candles),
            )
            return "rejected"

        # ── TRACE 3: Feature computation ──────────────────────────────
        features = _compute_features(candles)
        if not features:
            _log.debug("signal_scanner.skip symbol=%s reason=feature_compute_failed", symbol)
            return "rejected"

        adx       = features.get("adx", 0)
        vol_ratio = features.get("volume_ratio", 0)
        rsi       = features.get("rsi_14", 50)
        vwap_dev  = features.get("vwap_deviation_sigma", 0)
        _log.info(
            "signal_scanner.features symbol=%s adx=%.1f vol_ratio=%.2f rsi=%.1f "
            "vwap_dev_sigma=%.2f ema20=%.2f bb_pct=%.2f",
            symbol,
            adx or 0,
            vol_ratio or 0,
            rsi or 50,
            vwap_dev or 0,
            features.get("ema_20") or 0,
            features.get("bb_width_percentile") or 0,
        )

        # ── TRACE 4: Regime classification ────────────────────────────
        regime   = _classify_regime(features)
        strategy = _pick_strategy(regime)
        _log.info(
            "signal_scanner.regime symbol=%s type=%s regime=%s strategy=%s",
            symbol, sym_type, regime, strategy,
        )

        # ── TRACE 5: Build SignalRequest ──────────────────────────────
        token    = sym.instrument_token or abs(hash(symbol)) % 1_000_000
        lot_size = sym.lot_size or 1

        req = _build_signal_request(symbol, token, lot_size, features, regime, strategy, is_index=sym.is_index)
        if req is None:
            _log.debug(
                "signal_scanner.skip symbol=%s reason=insufficient_features_for_request",
                symbol,
            )
            return "rejected"

        _log.info(
            "signal_scanner.signal_request symbol=%s token=%d lot_size=%d "
            "entry=%.2f stop=%.2f target=%.2f dte=%d",
            symbol, token, lot_size,
            float(req.entry_price), float(req.stop_loss_price),
            float(req.target_price), req.dte,
        )

        # ── TRACE 6: Signal Engine (Score → Confidence → Risk) ────────
        _log.info("signal_scanner.engine_start symbol=%s", symbol)
        result = await self._engine.process(req)
        _log.info(
            "signal_scanner.engine_result symbol=%s accepted=%s "
            "score=%.1f confidence=%.1f rejection=%s duplicate=%s",
            symbol,
            result.accepted,
            result.adjusted_score or 0.0,
            result.final_confidence or 0.0,
            result.rejection_reason,
            result.is_duplicate,
        )

        # ── TRACE 7: Signal analytics — always record (execution-mode independent) ──
        if self._analytics is not None:
            await self._analytics.record(
                symbol_name=symbol,
                exchange="NSE",
                is_index=sym.is_index,
                sector=getattr(sym, "sector", None),
                request=req,
                result=result,
                features=features,
            )

        if result.accepted:
            _log.info(
                "signal_scanner.SIGNAL_ACCEPTED symbol=%s type=%s regime=%s strategy=%s "
                "score=%.1f confidence=%.1f signal_id=%s",
                symbol, sym_type, regime, strategy,
                result.adjusted_score or 0.0,
                result.final_confidence or 0.0,
                result.signal_id,
            )
            return "accepted"
        else:
            _log.debug(
                "signal_scanner.signal_rejected symbol=%s reason=%s score=%.1f",
                symbol, result.rejection_reason, result.adjusted_score or 0.0,
            )
            return "rejected"

    def stop(self) -> None:
        self._running = False
