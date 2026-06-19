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
from datetime import UTC, date, datetime, time as _dtime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.market_data.historical_data_service import HistoricalDataService
    from core.application.services.market_universe_service import MarketUniverseService
    from core.application.services.option_chain_service import OptionChainService
    from core.application.services.signal_analytics_service import SignalAnalyticsService
    from core.application.services.signal_engine_service import SignalEngineService
    from core.infrastructure.config.signal_config import SignalConfig

_log = logging.getLogger(__name__)

_SCAN_INTERVAL_SECS  = 300   # 5 minutes
_IST_OFFSET          = timedelta(hours=5, minutes=30)
_MARKET_OPEN         = (9, 15)
_MARKET_CLOSE        = (15, 30)
_CANDLE_LIMIT        = 200   # bars to fetch per symbol
_MAX_CONCURRENT      = 10    # simultaneous candle fetches (rate-limit Kite API)
_CYCLE_BATCH_SIZE    = 50    # symbols per cycle — rotated randomly each run

# Regime overlay: additional pts added to the minimum passing score (base 70) per regime.
# "Base engine + regime overlay" pattern: engine scores against flat min_score=70,
# scanner then adds a regime-specific bump so HIGH_VOL/SIDEWAYS require stronger evidence.
# Keyed by MarketRegime string value to avoid circular import at module init time.
_REGIME_SCORE_BUMP: dict[str, float] = {
    "HIGH_VOLATILITY": 8.0,   # require 78+ in panic/spike markets (IV dislocated)
    "SIDEWAYS":        3.0,   # require 73+ in choppy markets (was 75; most signals are SIDEWAYS regime)
}

# Stock liquidity gate: reject thin-volume stock F&O before any scoring.
# Ratio vs own 20-bar avg volume — index futures (NIFTY/BNF) are exempt (deep liquidity).
# 0.60 = must be at least 60% of average volume. Below this, option spreads widen,
# fills are poor, and the signal reflects historical not current momentum.
_STOCK_MIN_VOLUME_RATIO = 0.60

# ATR quality gate for option trades: underlying must have enough daily range.
# Our ATR is the 14-period ATR on 15-minute candles (not daily).
# A 15m ATR of 0.30% maps to ~1.5% daily range (0.30% × √26 candles/day ≈ 1.5%).
# Below this the stock barely moves per session; theta/IV crush kills option premium
# before any directional gain materialises. Also reject if ATR is in deep compression
# (atr_ratio < 0.50 = current volatility less than half the stock's own recent average).
_MIN_ATR_PCT_FOR_OPTIONS = 0.30

# OI wall clearance gate: for a 55% option premium gain the underlying needs ~1.5-2%
# directional move (ATM delta ≈ 0.45 → ₹19.25 gain on ₹35 option ≈ ₹43 move on ₹2800
# stock ≈ 1.5%). If the dominant OI wall in the trade direction is within this distance,
# price will stall at the wall before generating the premium gain — target won't be hit.
# Exemption: index futures (NIFTY/BANKNIFTY) — their option walls shift faster and
# intraday algo buying routinely breaks through them.
_MIN_OI_WALL_CLEARANCE_PCT = 1.5


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

        # Session-only VWAP index: institutional VWAP resets at 09:15 IST each day.
        # Candle list is newest-last (chronological). Find the first candle of today's
        # session so VWAP is computed from 09:15 only — not a 3-day rolling average.
        _today_ist = _ist_now().date()
        _session_start_idx = 0
        for _i, _c in enumerate(candles):
            _ts = getattr(_c, "date", None) or getattr(_c, "timestamp", None)
            if _ts is not None:
                try:
                    _cd = _ts.date() if hasattr(_ts, "date") else _ts
                    if _cd >= _today_ist:
                        _session_start_idx = _i
                        break
                except Exception:
                    pass

        # ADX / DI+/-
        adx_ind = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
        adx      = adx_ind.adx().iloc[-1]
        di_plus  = adx_ind.adx_pos().iloc[-1]
        di_minus = adx_ind.adx_neg().iloc[-1]
        adx_series = adx_ind.adx().dropna()
        adx_rising = bool(
            len(adx_series) >= 3 and float(adx_series.iloc[-1]) > float(adx_series.iloc[-3])
        )

        # MACD (12/26/9) — momentum direction and histogram expansion
        _macd_ind = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
        macd_line   = _macd_ind.macd().iloc[-1]
        macd_signal = _macd_ind.macd_signal().iloc[-1]
        _macd_hist_series = _macd_ind.macd_diff().dropna()
        macd_hist_expanding: bool | None = None
        if len(_macd_hist_series) >= 2:
            _h_cur  = float(_macd_hist_series.iloc[-1])
            _h_prev = float(_macd_hist_series.iloc[-2])
            macd_hist_expanding = abs(_h_cur) > abs(_h_prev)

        # EMAs
        ema_20  = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
        ema_50  = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1] if len(df) >= 50 else None
        ema_200 = ta.trend.EMAIndicator(df["close"], window=200).ema_indicator().iloc[-1] if len(df) >= 200 else None

        # ATR + ATR ratio (expansion detection for breakout regime classification)
        # atr_ratio > 1.3 = volatility expanding; < 0.7 = compression still intact
        _atr_ind    = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14)
        _atr_series = _atr_ind.average_true_range().dropna()
        atr         = float(_atr_series.iloc[-1])
        _atr_mean10 = float(_atr_series.rolling(10).mean().iloc[-1]) if len(_atr_series) >= 10 else float(_atr_series.mean())
        atr_ratio   = atr / _atr_mean10 if _atr_mean10 > 0 else 1.0

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

        # Session VWAP — computed only on today's candles (resets at 09:15 IST).
        # Using all 200 candles (50 hrs) produced a multi-day average that sits at a
        # completely different level than the intraday VWAP institutions actually use.
        df_session = df.iloc[_session_start_idx:] if _session_start_idx > 0 else df
        _tp_session = (df_session["high"] + df_session["low"] + df_session["close"]) / 3
        _vol_sum    = df_session["volume"].sum()
        vwap = float((_tp_session * df_session["volume"]).sum() / _vol_sum) if _vol_sum > 0 else closes[-1]

        close      = closes[-1]
        prev_close = closes[-2] if len(closes) > 1 else close

        price_change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0.0

        # VWAP deviation uses session std-dev so sigma scale is calibrated to today
        _session_closes = df_session["close"]
        vwap_std              = float(_session_closes.std()) if len(_session_closes) > 1 else (float(df["close"].rolling(20).std().iloc[-1]) or 1.0)
        vwap_std              = vwap_std or 1.0
        vwap_deviation_sigma  = (close - float(vwap)) / vwap_std

        # Supertrend: replaced the VWAP-alias with EMA50 cross — independent signal.
        # close > EMA50 = bullish trend continuation; close < EMA50 = bearish.
        # This eliminates the double-counting between TREND and VWAP components.
        _ema50_val = float(ema_50) if ema_50 is not None and ema_50 == ema_50 else None
        supertrend_direction = (1 if close > _ema50_val else -1) if _ema50_val is not None else None

        # OI change from consecutive candles — Kite includes OI in F&O historical data.
        # oi_change_pct feeds the OI_BUILDUP scoring component (Component 1, weight 25).
        # Use 3-bar smoothed average to reduce single-candle rollover noise near expiry.
        if len(candles) >= 6:
            _recent_oi = sum(getattr(c, "oi", 0) or 0 for c in candles[-3:]) / 3
            _prior_oi  = sum(getattr(c, "oi", 0) or 0 for c in candles[-6:-3]) / 3
            oi_change_pct: float | None = (
                (_recent_oi - _prior_oi) / _prior_oi * 100.0 if _prior_oi > 0 else None
            )
        elif len(candles) >= 2:
            _curr_oi = getattr(candles[-1], "oi", 0) or 0
            _prev_oi = getattr(candles[-2], "oi", 0) or 0
            oi_change_pct = (_curr_oi - _prev_oi) / _prev_oi * 100.0 if _prev_oi > 0 else None
        else:
            oi_change_pct = None

        # IV percentile proxy — BB width percentile is a reliable volatility regime
        # proxy: wide bands = high realised vol = typically high implied vol.
        # Mapped linearly to 0-100 scale for IV_ANALYSIS component (Component 7, weight 5).
        iv_percentile_proxy = float(bb_pct) * 100.0

        # OBV (On-Balance Volume) trend — feeds VolumeComponent step 3 (+/-2 pts).
        # Direction determined by whether OBV slope over last 10 bars is positive.
        obv_series = ta.volume.OnBalanceVolumeIndicator(
            df["close"], df["volume"]
        ).on_balance_volume()
        obv_trend: str | None = None
        if len(obv_series.dropna()) >= 10:
            obv_slope = obv_series.iloc[-1] - obv_series.iloc[-10]
            if obv_slope > 0:
                obv_trend = "UP"
            elif obv_slope < 0:
                obv_trend = "DOWN"
            else:
                obv_trend = "FLAT"

        # VPOC (Volume Point of Control) — price level with highest cumulative volume.
        # Feeds VolumeComponent step 5 (+1 pt when price is within 0.2% of VPOC).
        vpoc_distance_pct: float | None = None
        if df["volume"].sum() > 0:
            # Bin closes into 50 price buckets and find the highest-volume bin
            price_min, price_max = df["close"].min(), df["close"].max()
            if price_max > price_min:
                n_bins = 50
                bin_width = (price_max - price_min) / n_bins
                bins = ((df["close"] - price_min) / bin_width).astype(int).clip(0, n_bins - 1)
                vol_by_bin = df.groupby(bins)["volume"].sum()
                vpoc_bin = int(vol_by_bin.idxmax())
                vpoc_price = price_min + (vpoc_bin + 0.5) * bin_width
                vpoc_distance_pct = (close - vpoc_price) / vpoc_price * 100.0

        # Cumulative delta (30-bar): net buy/sell pressure from bar-close direction.
        # Close above previous close → buying pressure; below → selling pressure.
        # Feeds VolumeComponent Step 4 (delta_confirms/against_score: ±2 pts).
        _delta_diff = df["close"].diff().tail(30)
        _delta_vol  = df["volume"].tail(30)
        _delta_sign = _delta_diff.apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
        cumulative_delta = float((_delta_sign * _delta_vol).sum())

        # Historical Volatility (HV) — 30-bar annualised realized vol from log returns.
        # HV/IV ratio feeds IVAnalysisComponent step 3:
        #   HV > IV (ratio > 1.2) → options are cheap → buy vol
        #   HV < IV (ratio < 0.8) → options are expensive → sell vol
        hv_iv_ratio: float | None = None
        if len(df) >= 30:
            import math
            log_returns = df["close"].pct_change().dropna()
            hv_30 = float(log_returns.rolling(30).std().iloc[-1]) * math.sqrt(252 * 26)
            # 252 trading days × 26 fifteen-min bars per day for annualised 15m HV
            iv_proxy_decimal = iv_percentile_proxy / 100.0
            if iv_proxy_decimal > 0.01:
                hv_iv_ratio = hv_30 / iv_proxy_decimal

        return {
            "close": close,
            "adx": float(adx) if adx == adx else None,
            "di_plus": float(di_plus) if di_plus == di_plus else None,
            "di_minus": float(di_minus) if di_minus == di_minus else None,
            "ema_20": float(ema_20) if ema_20 == ema_20 else None,
            "ema_50": float(ema_50) if ema_50 and ema_50 == ema_50 else None,
            "ema_200": float(ema_200) if ema_200 and ema_200 == ema_200 else None,
            "atr": float(atr) if atr == atr else None,
            "atr_ratio": float(atr_ratio),
            "rsi_14": float(rsi) if rsi == rsi else None,
            "bb_width_percentile": float(bb_pct),
            "volume_ratio": float(vol_ratio),
            "vwap": float(vwap),
            "price_change_pct": float(price_change_pct),
            "vwap_deviation_sigma": float(vwap_deviation_sigma),
            "supertrend_direction": supertrend_direction,
            "oi_change_pct": oi_change_pct,
            "iv_percentile_proxy": iv_percentile_proxy,
            "obv_trend": obv_trend,
            "vpoc_distance_pct": vpoc_distance_pct,
            "hv_iv_ratio": hv_iv_ratio,
            "adx_rising": adx_rising,
            "macd": float(macd_line) if macd_line == macd_line else None,
            "macd_signal": float(macd_signal) if macd_signal == macd_signal else None,
            "macd_hist_expanding": macd_hist_expanding,
            "cumulative_delta": cumulative_delta,
        }
    except Exception as exc:
        _log.debug("feature_compute error: %s", exc)
        return {}


def _classify_regime(f: dict):
    """Classify market regime from features.

    Thresholds aligned with strategy.yaml adx_gate (20) and research:
      - TRENDING: ADX 25+ (research consensus for intraday momentum)
      - HIGH_VOLATILITY: BB width in top-20th percentile
      - LOW_VOLATILITY: ADX < 20 (below our gate) + compressed BB
        → maps to BREAKOUT strategy; atr_ratio > 1.3 signals expansion is loading
      - SIDEWAYS: everything else (ADX 20-25, moderate BB)
    """
    from core.domain.enums.market_regime import MarketRegime
    adx     = f.get("adx") or 0
    di_p    = f.get("di_plus") or 0
    di_m    = f.get("di_minus") or 0
    bb_pct  = f.get("bb_width_percentile") or 0.5
    atr_rat = f.get("atr_ratio") or 1.0

    # Strong trend: ADX ≥ 27 to ENTER trending regime (hysteresis upper band).
    # Exit trending only when ADX < 22 (hysteresis lower band).
    # Without hysteresis, ADX oscillating 24–26 across scans causes the regime to
    # flip TRENDING↔SIDEWAYS every 5 min, destabilising dynamic multipliers for the
    # same symbol within a session. With a 5-pt hysteresis band (22–27), the regime
    # stays stable through normal ADX oscillation.
    if adx >= 27:
        return MarketRegime.TRENDING_BULLISH if di_p > di_m else MarketRegime.TRENDING_BEARISH
    # Vol expansion: BB in top 20th pct OR ATR expanding sharply (>1.5×)
    if bb_pct > 0.80 or atr_rat > 1.5:
        return MarketRegime.HIGH_VOLATILITY
    # Compression: ADX in the hysteresis grey zone below exit threshold + narrow BB
    # atr_ratio 1.2-1.5 with compression = breakout loading; LOW_VOLATILITY
    # maps to BREAKOUT strategy in _pick_strategy()
    if adx < 22 and bb_pct < 0.35:
        return MarketRegime.LOW_VOLATILITY
    # Default: ADX 22-27 or moderate BB = choppy/range (hysteresis "grey zone")
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


def _build_signal_request(symbol: str, token: int, lot_size: int, f: dict, regime, strategy, is_index: bool = False, option_chain_snap=None, max_pain: float | None = None, pcr: float | None = None, india_vix: float | None = None, vwap_touch_count: int = 0):
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
        # IV percentile: BB proxy when no option chain data; overridden by real BS IV
        # from OptionChainSnapshot.iv_percentile once the option chain poller has run.
        iv_percentile=f.get("iv_percentile_proxy"),
        # PCR from option chain DB snapshot — None when no snapshot available yet.
        pcr=pcr,
        # HV/IV ratio — feeds IVAnalysisComponent step 3 (cheap/expensive options).
        # Computed from 30-bar annualised realized vol vs BB-width IV proxy.
        hv_iv_ratio=f.get("hv_iv_ratio"),
        # India VIX — fetched once per scan cycle from Kite (NSE:INDIA VIX).
        # Feeds IVAnalysisComponent step 1 (VIX structural penalty on short vol).
        india_vix=india_vix,
        # Momentum confirmations — used by TrendComponent for bonus scoring.
        adx_rising=f.get("adx_rising"),
        macd_hist_expanding=f.get("macd_hist_expanding"),
    )

    ctx = ScoreContext(
        instrument_token=token,
        timeframe="15m",
        regime=regime,
        features=snap,
        volume_ratio=f.get("volume_ratio"),
        rsi_14=f.get("rsi_14"),
        # oi_change_pct from consecutive candle OI — Kite includes OI in F&O historical data.
        oi_change_pct=f.get("oi_change_pct"),
        price_change_pct=f.get("price_change_pct"),
        vwap_deviation_sigma=f.get("vwap_deviation_sigma"),
        instrument_class=score_instrument_class,
        dte=dte,
        # OBV trend from 10-bar OBV slope — feeds VolumeComponent step 3 (+/-2 pts).
        obv_trend=f.get("obv_trend"),
        # VPOC distance — feeds VolumeComponent step 5 (+1 pt at VPOC).
        vpoc_distance_pct=f.get("vpoc_distance_pct"),
        # Cumulative delta — feeds VolumeComponent step 4 (±2 pts).
        # Net buy/sell pressure from 30 bars of close-direction × volume.
        cumulative_delta=f.get("cumulative_delta"),
        # VWAP touch count — feeds VWAPComponent Mode A touch-degradation multiplier.
        vwap_touch_count=vwap_touch_count,
        # Option chain from DB snapshot: PCR trend + OI walls + real IV/GEX when available.
        option_chain=option_chain_snap,
        # Max pain from OptionChainService strike OI calculation.
        max_pain_price=max_pain,
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
        option_chain_svc: "OptionChainService | None" = None,
        signal_config: "SignalConfig | None" = None,
    ) -> None:
        from core.application.services.option_strike_selector import OptionStrikeSelector
        self._universe        = universe_svc
        self._history         = historical_svc
        self._engine          = signal_engine
        self._analytics       = analytics_svc
        self._option_chain    = option_chain_svc
        self._signal_config   = signal_config
        self._strike_selector = OptionStrikeSelector()
        self._running         = False
        # Per-symbol PCR history (last two readings) for trend detection.
        # Format: {symbol: [older_pcr, current_pcr]}
        self._pcr_history: dict[str, list[float]] = {}
        # Per-symbol VWAP touch count — counts sigma-sign flips (VWAP crosses) per session.
        # Feeds VWAPComponent Mode A touch-degradation multiplier (0.88 → 0.70 → 0.50).
        self._vwap_touch_count: dict[str, int] = {}
        self._vwap_last_sigma_sign: dict[str, int] = {}  # +1 or -1
        self._vwap_touch_date: dict[str, date] = {}

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
        # ── Pre-cycle: India VIX (once per cycle, shared across all symbols) ──
        india_vix: float | None = await self._fetch_india_vix()
        if india_vix is not None:
            _log.info("signal_scanner.india_vix vix=%.2f", india_vix)

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
        accepted = rejected = errors = gated = 0
        _GATE_OUTCOMES = frozenset({
            "opening_volatility", "closing_volatility", "vix_too_high",
            "thin_volume", "low_atr", "rsi_extreme", "macd_against",
            "regime_score_too_low", "iv_too_expensive", "expiry_day_gamma",
            "no_contract", "wall_too_close", "obv_against_trend",
        })
        results  = await asyncio.gather(
            *[self._process_symbol_sem(sym, semaphore, india_vix) for sym in candidates],
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                errors += 1
                _log.warning(
                    "signal_scanner.symbol_exception type=%s msg=%s",
                    type(res).__name__, str(res),
                )
            elif res == "accepted":
                accepted += 1
            elif res == "rejected":
                rejected += 1
            elif res in _GATE_OUTCOMES:
                gated += 1
            else:
                errors += 1

        _log.info(
            "signal_scanner.cycle_summary accepted=%d rejected=%d gated=%d errors=%d candidates=%d "
            "(gated=pre-engine filters: thin_vol/rsi/macd/iv/no_contract/etc)",
            accepted, rejected, gated, errors, len(candidates),
        )
        return {
            "accepted":   accepted,
            "rejected":   rejected,
            "gated":      gated,
            "errors":     errors,
            "candidates": len(candidates),
        }

    async def _process_symbol_sem(self, sym, semaphore: asyncio.Semaphore, india_vix: float | None = None) -> str:
        async with semaphore:
            return await self._process_symbol(sym, india_vix=india_vix)

    async def _process_symbol(self, sym, india_vix: float | None = None) -> str:
        """Process one universe symbol through the full pipeline. Returns 'accepted'/'rejected'/'error'."""
        symbol   = sym.symbol
        sym_type = "INDEX" if sym.is_index else "STOCK"

        # ── Time-of-day hard gates (before any I/O) ───────────────────
        # Opening volatility (9:15-9:30 IST): first 15 min = price discovery chaos,
        # IV is dislocated, option spreads wide — no new entries.
        # Closing volatility (≥15:00 IST): last 20 min before market-close exit fires
        # at 15:20; a signal with 5-20 min to live has no meaningful hold window.
        _now_ist = _ist_now().time()
        if _dtime(9, 15) <= _now_ist < _dtime(9, 30):
            return "opening_volatility"
        if _now_ist >= _dtime(15, 0):
            return "closing_volatility"

        # ── India VIX hard gate ────────────────────────────────────────
        # VIX ≥ 22: option premiums severely dislocated; directional buying
        # has unfavourable risk-reward until VIX settles below 22 (AIMarketAnalyzer calibrated).
        _VIX_GATE = 22.0
        if india_vix is not None and india_vix >= _VIX_GATE:
            _log.warning(
                "signal_scanner.vix_gate symbol=%s vix=%.1f threshold=%.1f",
                symbol, india_vix, _VIX_GATE,
            )
            return "vix_too_high"

        # ── TRACE 2: Historical candles ───────────────────────────────
        # Gap-fill: fetch any new candles since last stored timestamp before reading.
        # fetch_and_store is lightweight after the initial seed — it only requests
        # the delta from last_stored_ts+1m to now, typically 1-2 new candles per cycle.
        try:
            await self._history.fetch_and_store(symbol, "15m")
        except Exception as _fe:
            _log.debug("signal_scanner.candle_fetch_failed symbol=%s: %s", symbol, _fe)

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
            "vwap_dev_sigma=%.2f ema20=%.2f bb_pct=%.2f obv=%s vpoc=%s hv_iv=%s",
            symbol,
            adx or 0,
            vol_ratio or 0,
            rsi or 50,
            vwap_dev or 0,
            features.get("ema_20") or 0,
            features.get("bb_width_percentile") or 0,
            features.get("obv_trend") or "N/A",
            f"{features['vpoc_distance_pct']:.2f}%" if features.get("vpoc_distance_pct") is not None else "N/A",
            f"{features['hv_iv_ratio']:.2f}" if features.get("hv_iv_ratio") is not None else "N/A",
        )

        # ── Stock liquidity gate ──────────────────────────────────────
        # Index futures (NIFTY, BANKNIFTY, FINNIFTY) always have deep liquidity.
        # Stock F&O below 60% of own 20-bar avg volume: option spreads widen,
        # fills are poor, and the volume signal is unreliable.
        if not sym.is_index:
            _vol_ratio_chk = features.get("volume_ratio") or 1.0
            if _vol_ratio_chk < _STOCK_MIN_VOLUME_RATIO:
                _log.info(
                    "signal_scanner.liquidity_gate symbol=%s vol_ratio=%.2f "
                    "threshold=%.2f — thin volume, skipping",
                    symbol, _vol_ratio_chk, _STOCK_MIN_VOLUME_RATIO,
                )
                return "thin_volume"

        # ── ATR quality gate ─────────────────────────────────────────
        # Two checks: (1) ATR% of price too low = stock barely moves;
        # (2) atr_ratio too low = stock in deep compression vs own history.
        # Either condition means theta/IV crush will kill option premium
        # before any directional gain materialises.
        if not sym.is_index:
            _close_chk    = features.get("close") or 0.0
            _atr_chk      = features.get("atr") or 0.0
            _atr_ratio_chk = features.get("atr_ratio") or 1.0
            _atr_pct      = (_atr_chk / _close_chk * 100) if _close_chk > 0 else 0.0
            if _atr_pct < _MIN_ATR_PCT_FOR_OPTIONS or _atr_ratio_chk < 0.50:
                _log.info(
                    "signal_scanner.atr_gate symbol=%s atr=%.2f price=%.2f "
                    "atr_pct=%.2f%% atr_ratio=%.2f — insufficient range for options",
                    symbol, _atr_chk, _close_chk, _atr_pct, _atr_ratio_chk,
                )
                return "low_atr"

        # ── TRACE 4: Regime classification ────────────────────────────
        regime   = _classify_regime(features)
        strategy = _pick_strategy(regime)
        _log.info(
            "signal_scanner.regime symbol=%s type=%s regime=%s strategy=%s",
            symbol, sym_type, regime, strategy,
        )

        # ── TRACE 4b: Option chain from DB (PCR, max pain, OI walls) ─
        close_price = features.get("close") or 0.0
        oc_snap, max_pain, pcr_val = await self._fetch_option_chain_snapshot(symbol, close_price)
        if oc_snap is not None:
            _log.info(
                "signal_scanner.option_chain symbol=%s pcr=%.2f max_pain=%.0f "
                "ce_wall=%s pe_wall=%s pcr_trend=%s iv_pct=%s iv_skew=%s gex_positive=%s",
                symbol,
                pcr_val or 0,
                max_pain or 0,
                f"{oc_snap.nearest_call_wall_distance_pct:.1f}%" if oc_snap.nearest_call_wall_distance_pct else "N/A",
                f"{oc_snap.nearest_put_wall_distance_pct:.1f}%" if oc_snap.nearest_put_wall_distance_pct else "N/A",
                oc_snap.pcr_trend or "N/A",
                f"{oc_snap.iv_percentile:.1f}" if oc_snap.iv_percentile is not None else "N/A",
                f"{oc_snap.iv_skew:.4f}" if oc_snap.iv_skew is not None else "N/A",
                oc_snap.gex_positive if oc_snap.gex_positive is not None else "N/A",
            )

        # ── TRACE 5: Build SignalRequest ──────────────────────────────
        token    = sym.instrument_token or abs(hash(symbol)) % 1_000_000
        lot_size = sym.lot_size or 1

        # Track VWAP crosses per session for Mode A touch-count degradation.
        # Each time price crosses VWAP (sigma sign flips), increment the counter.
        # Counter resets at the start of each trading day.
        _sigma_now  = features.get("vwap_deviation_sigma", 0) or 0
        _sigma_sign = 1 if _sigma_now >= 0 else -1
        _today_vwap = _ist_now().date()
        if self._vwap_touch_date.get(symbol) != _today_vwap:
            self._vwap_touch_count[symbol] = 0
            self._vwap_last_sigma_sign[symbol] = _sigma_sign
            self._vwap_touch_date[symbol] = _today_vwap
        elif self._vwap_last_sigma_sign.get(symbol, _sigma_sign) != _sigma_sign:
            self._vwap_touch_count[symbol] = self._vwap_touch_count.get(symbol, 0) + 1
            self._vwap_last_sigma_sign[symbol] = _sigma_sign
        _vwap_touches = self._vwap_touch_count.get(symbol, 0)

        req = _build_signal_request(
            symbol, token, lot_size, features, regime, strategy,
            is_index=sym.is_index,
            option_chain_snap=oc_snap,
            max_pain=max_pain,
            pcr=pcr_val,
            india_vix=india_vix,
            vwap_touch_count=_vwap_touches,
        )
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

        # Hard gate: RSI extreme — buying CE into overbought / PE into oversold
        # RSI > 75 on LONG or < 25 on SHORT = chasing exhausted move on 15m candles
        if result.accepted and result.direction in ("LONG", "SHORT"):
            _rsi = features.get("rsi_14", 50)
            if (result.direction == "LONG" and _rsi > 75) or \
               (result.direction == "SHORT" and _rsi < 25):
                _log.warning(
                    "signal_scanner.rsi_extreme_skip symbol=%s direction=%s rsi=%.1f",
                    symbol, result.direction, _rsi,
                )
                return "rsi_extreme"

        # Hard gate: MACD histogram expanding against direction.
        # Original gate blocked any MACD/signal misalignment — too aggressive since
        # MACD is a 26-bar lagging indicator and will lag price on early-day moves.
        # Tighter rule: only block when the histogram is ACTIVELY EXPANDING against
        # direction (bearish/bullish divergence is accelerating), not just slightly off.
        if result.accepted and result.direction in ("LONG", "SHORT"):
            _macd     = features.get("macd")
            _macd_sig = features.get("macd_signal")
            _hist_exp = features.get("macd_hist_expanding")
            if _macd is not None and _macd_sig is not None:
                _hist = _macd - _macd_sig
                _macd_strongly_against = (
                    (result.direction == "LONG"  and _hist < 0 and _hist_exp is True) or
                    (result.direction == "SHORT" and _hist > 0 and _hist_exp is True)
                )
                if _macd_strongly_against:
                    _log.warning(
                        "signal_scanner.macd_gate symbol=%s direction=%s "
                        "macd=%.4f signal=%.4f hist=%.4f expanding=True",
                        symbol, result.direction, _macd, _macd_sig, _hist,
                    )
                    return "macd_against"

        # ── Regime overlay score floor ────────────────────────────────
        # The base engine scores against a flat min_score=70. In regimes where
        # false signals are costly, we impose a stricter floor without touching
        # the engine — "base engine + regime overlay" pattern.
        if result.accepted:
            # Base floor of 70 applies to ALL regimes — not just bumped ones.
            # Previously the check was `if _bump > 0`, which meant TRENDING_BULLISH/BEARISH
            # signals only needed to clear the engine gate (40) not 70 — allowing weak
            # 41-69 score signals through on the most common regime. Now 70 is universal
            # and bumped regimes (HIGH_VOLATILITY, SIDEWAYS) require even higher.
            _regime_key = str(regime)
            _bump   = _REGIME_SCORE_BUMP.get(_regime_key, 0.0)
            _escore = result.adjusted_score or 0.0
            _emin   = 70.0 + _bump
            if _escore < _emin:
                _log.warning(
                    "signal_scanner.regime_overlay_reject symbol=%s regime=%s "
                    "score=%.1f required=%.1f bump=%.1f",
                    symbol, regime, _escore, _emin, _bump,
                )
                return "regime_score_too_low"

        # ── OI Wall Clearance Gate ────────────────────────────────────────
        # For option buying to reach a 55% target, the underlying needs ~1.5% directional
        # move. If the dominant OI wall in the signal's direction is within 1.5%, price
        # will stall there before generating enough option premium gain.
        # Only applies to stock F&O — index options walls shift with algo flow.
        if result.accepted and not sym.is_index and oc_snap is not None:
            _wall_dir = result.direction
            if _wall_dir == "LONG" and oc_snap.nearest_call_wall_distance_pct is not None:
                if oc_snap.nearest_call_wall_distance_pct < _MIN_OI_WALL_CLEARANCE_PCT:
                    _log.warning(
                        "signal_scanner.wall_gate symbol=%s direction=LONG "
                        "ce_wall=%.1f%% min=%.1f%% — CE wall blocks target",
                        symbol, oc_snap.nearest_call_wall_distance_pct, _MIN_OI_WALL_CLEARANCE_PCT,
                    )
                    return "wall_too_close"
            elif _wall_dir == "SHORT" and oc_snap.nearest_put_wall_distance_pct is not None:
                if oc_snap.nearest_put_wall_distance_pct < _MIN_OI_WALL_CLEARANCE_PCT:
                    _log.warning(
                        "signal_scanner.wall_gate symbol=%s direction=SHORT "
                        "pe_wall=%.1f%% min=%.1f%% — PE wall blocks target",
                        symbol, oc_snap.nearest_put_wall_distance_pct, _MIN_OI_WALL_CLEARANCE_PCT,
                    )
                    return "wall_too_close"

        # ── OBV Direction Confirmation Gate (Trending regime only) ────────
        # In a TRENDING regime, On-Balance Volume must not be flowing against the
        # signal direction. OBV DOWN on a LONG in uptrend = institutional distribution
        # while price is rising — the move is distribution-driven and will reverse
        # before our option reaches the 55% target. In SIDEWAYS regime this is
        # acceptable (mean-reversion logic; price can move against recent OBV).
        if result.accepted and result.direction in ("LONG", "SHORT"):
            from core.domain.enums.market_regime import MarketRegime
            _obv = features.get("obv_trend")
            _is_trending = regime in (MarketRegime.TRENDING_BULLISH, MarketRegime.TRENDING_BEARISH)
            if _is_trending and _obv is not None:
                _obv_against = (
                    (result.direction == "LONG"  and _obv == "DOWN") or
                    (result.direction == "SHORT" and _obv == "UP")
                )
                if _obv_against:
                    _log.warning(
                        "signal_scanner.obv_against_trend symbol=%s direction=%s "
                        "obv=%s regime=%s — distribution against trend direction",
                        symbol, result.direction, _obv, regime,
                    )
                    return "obv_against_trend"

        # ── TRACE 6b: Option contract selection ───────────────────────────
        option_play = None
        if result.accepted and result.direction in ("LONG", "SHORT") and self._option_chain is not None:
            try:
                # Always refresh option chain from Kite before contract selection
                # on accepted signals so that entry/SL/target reflect the current
                # LTP, not a potentially minutes-old DB snapshot.
                try:
                    await self._option_chain.fetch_and_store(symbol)
                    _log.debug("signal_scanner.chain_refreshed symbol=%s", symbol)
                except Exception as _refresh_exc:
                    _log.debug("signal_scanner.chain_refresh_failed symbol=%s: %s", symbol, _refresh_exc)
                chain_data = await self._option_chain.get_latest(symbol)
                if not chain_data or not chain_data.get("entries"):
                    _log.debug("signal_scanner.option_chain_empty symbol=%s", symbol)
                if chain_data and chain_data.get("entries"):
                    # Phase 4: DTE-aware IV percentile gate.
                    # On expiry day (0-DTE), IV percentile is structurally elevated (80-90th pct)
                    # due to theta collapse — applying the same 75 threshold would reject every
                    # valid expiry-day trade. Threshold rises as DTE falls.
                    _iv_pct = chain_data.get("iv_percentile")
                    _near_dte: int | None = None
                    if _iv_pct is not None:
                        _today = datetime.utcnow().date()
                        _dtes = []
                        for _e in chain_data.get("entries", []):
                            _raw = _e.get("expiry")
                            try:
                                if isinstance(_raw, str):
                                    _exp = date.fromisoformat(_raw[:10])
                                elif hasattr(_raw, "year"):
                                    _exp = date(_raw.year, _raw.month, _raw.day)
                                else:
                                    continue
                                _d = (_exp - _today).days
                                if _d >= 0:
                                    _dtes.append(_d)
                            except Exception:
                                pass
                        _near_dte = min(_dtes) if _dtes else None
                        # IV threshold by nearest available DTE
                        if _near_dte == 0:
                            _iv_limit = 95   # expiry day: only block structurally extreme IV
                        elif _near_dte == 1:
                            _iv_limit = 88
                        elif _near_dte in (2, 3):
                            _iv_limit = 80
                        else:
                            _iv_limit = 75   # positional: original threshold
                        if _iv_pct > _iv_limit:
                            _log.warning(
                                "signal_scanner.iv_too_expensive_skip symbol=%s "
                                "iv_percentile=%.1f limit=%d dte=%s",
                                symbol, _iv_pct, _iv_limit, _near_dte,
                            )
                            return "iv_too_expensive"

                    # Expiry day gamma gate: on 0-DTE (expiry day), gamma risk
                    # accelerates sharply after 11:00 IST — time decay destroys
                    # long-option value even on correct directional moves.
                    if _near_dte == 0 and _now_ist >= _dtime(11, 0):
                        _log.warning(
                            "signal_scanner.expiry_day_gamma symbol=%s time=%s",
                            symbol, _now_ist,
                        )
                        return "expiry_day_gamma"

                    _dte_cfg  = self._signal_config.option_dte if self._signal_config else None
                    _risk_cfg = self._signal_config.intraday_risk if self._signal_config else None
                    option_play = self._strike_selector.select(
                        direction=result.direction,
                        underlying_price=features.get("close") or 0.0,
                        chain_entries=chain_data["entries"],
                        min_dte=_dte_cfg.min if _dte_cfg else 0,
                        max_dte=_dte_cfg.max if _dte_cfg else 3,
                        adjusted_score=result.adjusted_score,
                        intraday_risk_cfg=_risk_cfg,
                    )
                    if option_play:
                        _log.info(
                            "signal_scanner.option_play symbol=%s %s %s@%.0f "
                            "entry=%.2f sl=%.2f target=%.2f",
                            symbol, option_play.option_type, option_play.option_symbol,
                            option_play.option_strike,
                            option_play.entry, option_play.sl, option_play.target,
                        )
            except Exception as exc:
                _log.debug("signal_scanner.option_play_failed symbol=%s: %s", symbol, exc)

        # Gate: accepted signals with no option contract are not actionable — skip.
        # Index futures (NIFTY, BANKNIFTY) always retry; equity with no NFO contract
        # should not clutter the signals table.
        if result.accepted and option_play is None:
            _log.warning(
                "signal_scanner.no_contract_skip symbol=%s direction=%s — "
                "no option contract found; signal not saved",
                symbol, result.direction,
            )
            return "no_contract"

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
                option_play=option_play,
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

    async def _fetch_india_vix(self) -> float | None:
        """Fetch India VIX from Kite (NSE:INDIA VIX).

        India VIX feeds IVAnalysisComponent step 1 (VIX structural regime classification)
        and step 4 (VIX > 20 → -2 pts penalty on short-vol signals).
        Returns None if option chain service or provider is unavailable.
        """
        if self._option_chain is None:
            return None
        try:
            provider = getattr(self._option_chain, "_primary", None)
            if provider is None:
                return None
            ltp_map = await provider.get_ltp(["INDIA VIX"])
            val = ltp_map.get("INDIA VIX")
            if val is not None:
                return float(val)
        except Exception as exc:
            _log.debug("india_vix fetch failed: %s", exc)
        return None

    async def _fetch_option_chain_snapshot(
        self, symbol: str, close_price: float
    ) -> "tuple[object | None, float | None, float | None]":
        """Query the option_chain_snapshots table and build what we can from Kite data.

        Returns (OptionChainSnapshot | None, max_pain | None, pcr | None).

        What Kite provides via option chain:
          ✓ PCR (put_OI / call_OI) — from aggregated strike OI
          ✓ Max Pain — calculated from strike OI by OptionChainService
          ✓ Nearest CE OI wall distance — highest-OI call strike above price
          ✓ Nearest PE OI wall distance — highest-OI put strike below price
          ✓ PCR trend — derived from consecutive snapshots (tracked in self._pcr_history)
          ✗ IV / IV percentile — NOT from Kite; requires Black-Scholes (use BB proxy in FeatureSnapshot)
          ✗ IV skew — NOT from Kite; requires IV per strike
          ✗ GEX — NOT from Kite; requires delta/gamma from options model
        """
        if self._option_chain is None:
            return None, None, None

        try:
            data = await self._option_chain.get_latest(symbol)
        except Exception as exc:
            _log.debug("option_chain.get_latest failed symbol=%s: %s", symbol, exc)
            return None, None, None

        if not data:
            return None, None, None

        from core.domain.value_objects.option_chain_snapshot import OptionChainSnapshot

        pcr: float = data.get("pcr") or 0.0
        max_pain: float = data.get("max_pain") or 0.0
        entries: list[dict] = data.get("entries") or []

        # PCR trend: RISING = more put OI building (bullish), FALLING = more call OI (bearish)
        history = self._pcr_history.get(symbol, [])
        if history:
            prev_pcr = history[-1]
            if pcr > prev_pcr * 1.02:
                pcr_trend = "RISING"
            elif pcr < prev_pcr * 0.98:
                pcr_trend = "FALLING"
            else:
                pcr_trend = "STABLE"
        else:
            pcr_trend = "STABLE"
        self._pcr_history[symbol] = [pcr]  # keep last one reading

        # Nearest OI walls: highest-OI call strike above price → resistance
        #                    highest-OI put strike below price  → support
        call_wall_pct: float | None = None
        put_wall_pct:  float | None = None

        if close_price > 0 and entries:
            # CE walls: strikes above current price, sorted by OI desc
            ce_above = [
                e for e in entries
                if e.get("option_type") == "CE"
                and float(e.get("strike") or 0) > close_price
                and (e.get("oi") or 0) > 0
            ]
            if ce_above:
                top_ce = max(ce_above, key=lambda e: e.get("oi") or 0)
                call_wall_pct = ((float(top_ce["strike"]) - close_price) / close_price) * 100.0

            # PE walls: strikes below current price, sorted by OI desc
            pe_below = [
                e for e in entries
                if e.get("option_type") == "PE"
                and float(e.get("strike") or 0) < close_price
                and (e.get("oi") or 0) > 0
            ]
            if pe_below:
                top_pe = max(pe_below, key=lambda e: e.get("oi") or 0)
                put_wall_pct = ((close_price - float(top_pe["strike"])) / close_price) * 100.0

        # IV data from OptionChainService (Black-Scholes computed at fetch_and_store time)
        # iv_percentile is a rolling percentile vs last 252 trading days (None until 5+ days of data)
        iv_percentile: float | None = data.get("iv_percentile")
        iv_skew: float | None = data.get("iv_skew")
        gex_positive: bool | None = data.get("gex_positive")  # True = price-suppressing regime
        gex_strike: float | None = None  # not yet surfaced by get_latest(); available in analysis dict

        snap = OptionChainSnapshot(
            iv_percentile=iv_percentile,
            iv_skew=iv_skew,
            gex_positive=gex_positive,
            gex_strike=gex_strike,
            nearest_call_wall_distance_pct=call_wall_pct,
            nearest_put_wall_distance_pct=put_wall_pct,
            pcr_trend=pcr_trend if history else None,
        )
        return snap, (max_pain or None), (pcr or None)

    def stop(self) -> None:
        self._running = False
