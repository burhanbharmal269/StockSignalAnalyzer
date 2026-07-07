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
import json
import logging
import random
import time
from datetime import UTC, date, datetime, time as _dtime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

# Runtime imports (used in hot path — import once at module load, not per call)
from core.domain.value_objects.overlay_result import OverlayContext, PortfolioContext

if TYPE_CHECKING:
    from core.application.services.data_quality_service import DataQualityService
    from core.application.services.event_calendar_service import EventCalendarService
    from core.application.services.execution_lock_service import ExecutionLockService
    from core.application.services.execution_readiness_service import ExecutionReadinessService
    from core.application.services.futures_oi_service import FuturesOIService
    from core.application.services.indicator_cache_service import IndicatorCacheService
    from core.application.services.market_breadth_service import MarketBreadthService
    from core.application.services.market_context_engine import MarketContextEngine
    from core.application.services.market_data.historical_data_service import HistoricalDataService
    from core.application.services.market_regime_snapshot_service import MarketRegimeSnapshotService
    from core.application.services.market_universe_service import MarketUniverseService
    from core.application.services.option_chain_intelligence_worker import OptionChainIntelligenceWorker
    from core.application.services.option_chain_service import OptionChainService
    from core.application.services.overlay_pipeline import OverlayPipeline
    from core.application.services.portfolio_intelligence_service import PortfolioIntelligenceService
    from core.application.services.risk_manager_service import RiskManagerService
    from core.application.services.scan_metrics_service import ScanMetricsService
    from core.application.services.scanner_replay_service import ScannerReplayService
    from core.application.services.signal_analytics_service import SignalAnalyticsService
    from core.application.services.signal_engine_service import SignalEngineService
    from core.domain.value_objects.market_context_snapshot import MarketContextSnapshot
    from core.infrastructure.config.signal_config import SignalConfig

_log = logging.getLogger(__name__)

_SCAN_INTERVAL_SECS  = 300   # 5 minutes
_IST_OFFSET          = timedelta(hours=5, minutes=30)
_MARKET_OPEN         = (9, 15)
_MARKET_CLOSE        = (15, 30)
_CANDLE_LIMIT        = 200   # bars to fetch per symbol
_MAX_CONCURRENT      = 15    # simultaneous candle fetches (rate-limit Kite API)

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
    """Return the last Tuesday of the current or next month (NSE F&O expiry).

    NSE moved all derivatives expiry from Thursday to Tuesday effective
    1 September 2025 (SEBI circular). Monthly expiry = last Tuesday of month
    for ALL instruments (indices and stocks).
    """
    today = _ist_now().date()
    for month_offset in range(3):
        year = today.year + (today.month + month_offset - 1) // 12
        month = (today.month + month_offset - 1) % 12 + 1
        last_day = date(year, month, 28)
        while last_day.weekday() != 1:  # 1 = Tuesday (Mon=0, Tue=1, ...)
            last_day += timedelta(days=1)
        candidate = last_day
        while True:
            nxt = candidate + timedelta(days=7)
            if nxt.month != month:
                break
            candidate = nxt
        if candidate > today:  # strictly after today — avoid DTE=0 on expiry day
            return candidate
    return today + timedelta(days=30)


def _next_nifty_weekly_expiry() -> date:
    """Return the nearest Tuesday (NIFTY50 weekly option expiry).

    Since Sep 2025, NIFTY50 is the only NSE index with weekly options.
    They expire every Tuesday. BANKNIFTY/FINNIFTY/MIDCPNIFTY have
    monthly-only options (last Tuesday of month) — use _next_monthly_expiry().
    """
    today = _ist_now().date()
    days_ahead = (1 - today.weekday()) % 7  # days until next Tuesday
    if days_ahead == 0:
        days_ahead = 7  # on expiry day itself roll to next week — DTE=0 signals are unviable
    return today + timedelta(days=days_ahead)


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

        # OI change from consecutive candle OI (candle-based fallback for F&O instruments).
        # Kite returns OI=0 for equity/index spot candles; this path is only non-None for
        # instruments that actually carry OI in historical data (rare for spot).
        # The FuturesOIService (populated by the OptionChainPoller) is the primary source.
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


def _compute_5m_features(candles) -> "MtfSnapshot | None":
    """Compute lightweight 5-minute indicator snapshot for MTF overlay.

    Requires ≥55 candles for EMA50 validity. Returns None on any error so
    5m unavailability never blocks signal generation (fail-open design).
    Indicators computed: EMA20, EMA50, ADX, DI+/DI-, ADX rising,
    session VWAP, volume ratio, last candle direction.
    """
    from core.domain.value_objects.mtf_snapshot import MtfSnapshot

    if len(candles) < 55:
        return None
    try:
        import pandas as pd
        import ta

        closes = [float(c.close)  for c in candles]
        highs  = [float(c.high)   for c in candles]
        lows   = [float(c.low)    for c in candles]
        vols   = [float(c.volume) for c in candles]
        df = pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": vols})

        # ADX / DI
        adx_ind   = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
        adx       = float(adx_ind.adx().iloc[-1])
        di_plus   = float(adx_ind.adx_pos().iloc[-1])
        di_minus  = float(adx_ind.adx_neg().iloc[-1])
        adx_ser   = adx_ind.adx().dropna()
        adx_rising = bool(
            len(adx_ser) >= 3 and float(adx_ser.iloc[-1]) > float(adx_ser.iloc[-3])
        )

        # EMAs
        ema_20 = float(ta.trend.EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1])
        ema_50 = (
            float(ta.trend.EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1])
            if len(df) >= 50 else None
        )

        # Session-only VWAP (resets at 09:15 IST — same logic as 15m VWAP)
        _today_ist = _ist_now().date()
        _sess_idx = 0
        for _i, _c in enumerate(candles):
            _ts = getattr(_c, "date", None) or getattr(_c, "timestamp", None)
            if _ts is not None:
                try:
                    _cd = _ts.date() if hasattr(_ts, "date") else _ts
                    if _cd >= _today_ist:
                        _sess_idx = _i
                        break
                except Exception:
                    pass
        df_s = df.iloc[_sess_idx:] if _sess_idx > 0 else df
        _tp  = (df_s["high"] + df_s["low"] + df_s["close"]) / 3
        _vs  = df_s["volume"].sum()
        vwap = float((_tp * df_s["volume"]).sum() / _vs) if _vs > 0 else closes[-1]

        # Volume ratio (current bar vs 20-bar avg)
        _vol_avg  = float(df["volume"].rolling(20).mean().iloc[-1])
        vol_ratio = float(df["volume"].iloc[-1]) / _vol_avg if _vol_avg > 0 else 1.0

        # Last candle direction (close > open = bullish bar)
        _last_open  = float(getattr(candles[-1], "open", closes[-1]))
        last_candle_bullish = closes[-1] > _last_open

        return MtfSnapshot(
            adx=adx        if adx   == adx   else None,
            di_plus=di_plus  if di_plus == di_plus else None,
            di_minus=di_minus if di_minus == di_minus else None,
            adx_rising=adx_rising,
            ema_20=ema_20  if ema_20 == ema_20 else None,
            ema_50=ema_50,
            close_price=closes[-1],
            vwap=vwap,
            volume_ratio=vol_ratio,
            last_candle_bullish=last_candle_bullish,
        )
    except Exception as exc:
        _log.debug("mtf_5m.compute_error: %s", exc)
        return None


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


def _build_signal_request(symbol: str, token: int, lot_size: int, f: dict, regime, strategy, is_index: bool = False, option_chain_snap=None, max_pain: float | None = None, pcr: float | None = None, india_vix: float | None = None, vwap_touch_count: int = 0, mtf_5m=None):
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

    # NIFTY has weekly options every Tuesday; everything else monthly (last Tuesday).
    if is_index and symbol == "NIFTY":
        expiry = _next_nifty_weekly_expiry()
    else:
        expiry = _next_monthly_expiry()
    dte = max((expiry - _ist_now().date()).days, 1)

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
        # Phase 14 MTF: 5-minute candle snapshot for TrendComponent overlay.
        # None when 5m data is unavailable — never blocks signal generation.
        mtf_5m=mtf_5m,
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

    # We trade OPTIONS on the underlying — use "OPTION" so the risk engine applies
    # option-delta math (0.5 × lot_size) instead of futures-delta (1.0 × lot_size).
    # Using "FUTURE" caused large-lot stocks (BANKBARODA 2925, UNIONBANK 4425) to
    # always exceed the NET_DELTA_LIMIT of 2500.
    return SignalRequest(
        instrument_token=token,
        underlying=symbol,
        instrument_class="OPTION",
        expiry_date=expiry,
        strategy_type=strategy,
        asset_type=AssetType.FNO,
        regime=regime,
        score_context=ctx,
        entry_price=entry,
        stop_loss_price=stop,
        target_price=tgt,
        # ATR is a reasonable ATM-option-premium proxy at scan time — the actual
        # contract LTP isn't known until the strike selector runs after risk approval.
        # The risk engine uses this only for lot_risk = premium × lot_size capital check.
        option_premium=atr_d,
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
        risk_manager: "RiskManagerService | None" = None,
        market_context_engine: "MarketContextEngine | None" = None,
        event_calendar_svc: "EventCalendarService | None" = None,
        breadth_svc: "MarketBreadthService | None" = None,
        execution_lock_svc: "ExecutionLockService | None" = None,
        overlay_pipeline: "OverlayPipeline | None" = None,
        portfolio_svc: "PortfolioIntelligenceService | None" = None,
        scan_metrics_svc: "ScanMetricsService | None" = None,
        futures_oi_svc: "FuturesOIService | None" = None,
        # Phase 22 additions
        oc_intel_worker: "OptionChainIntelligenceWorker | None" = None,
        regime_snapshot_svc: "MarketRegimeSnapshotService | None" = None,
        scanner_replay_svc: "ScannerReplayService | None" = None,
        exec_readiness_svc: "ExecutionReadinessService | None" = None,
        indicator_cache_svc: "IndicatorCacheService | None" = None,
    ) -> None:
        from core.application.services.data_quality_service import DataQualityService
        from core.application.services.option_strike_selector import OptionStrikeSelector
        self._universe        = universe_svc
        self._history         = historical_svc
        self._engine          = signal_engine
        self._analytics       = analytics_svc
        self._option_chain    = option_chain_svc
        self._signal_config   = signal_config
        self._risk_manager    = risk_manager
        self._mce             = market_context_engine
        self._event_svc       = event_calendar_svc
        self._breadth_svc     = breadth_svc
        self._exec_lock_svc   = execution_lock_svc
        self._overlay_pipeline = overlay_pipeline
        self._portfolio_svc    = portfolio_svc
        self._scan_metrics     = scan_metrics_svc
        self._futures_oi_svc  = futures_oi_svc
        self._oc_intel_worker  = oc_intel_worker
        self._regime_snapshot_svc = regime_snapshot_svc
        self._scanner_replay_svc  = scanner_replay_svc
        self._exec_readiness_svc  = exec_readiness_svc
        self._indicator_cache_svc = indicator_cache_svc
        self._dq_service      = DataQualityService()
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
        # Phase 21.1 — market context + event overlay state
        # Index regime cache: updated each cycle, used for NEXT cycle's context computation.
        self._index_regime_cache: dict[str, str] = {}
        # VIX history (last 10 readings) for direction detection.
        self._vix_history: list[float] = []
        # Per-symbol regime history (last 5 cycles) for stability overlay.
        self._regime_history: dict[str, list[str]] = {}
        # Last computed market context snapshot (default: NORMAL).
        self._market_ctx: "MarketContextSnapshot | None" = None

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
        _cycle_start = time.monotonic()
        # ── Phase 15: Portfolio risk gate (once per cycle, not per symbol) ────
        if self._risk_manager is not None:
            _risk_allowed, _risk_reason = await self._risk_manager.check()
            if not _risk_allowed:
                _log.warning(
                    "signal_scanner.risk_lock_triggered reason=%s — halting cycle",
                    _risk_reason,
                )
                return {
                    "accepted":     0,
                    "rejected":     0,
                    "gated":        0,
                    "errors":       0,
                    "candidates":   0,
                    "risk_locked":  True,
                    "risk_reason":  _risk_reason,
                }

        # ── Pre-cycle: India VIX (once per cycle, shared across all symbols) ──
        india_vix: float | None = await self._fetch_india_vix()
        if india_vix is not None:
            _log.info("signal_scanner.india_vix vix=%.2f", india_vix)

        # ── Phase 21.1: Market Context + Event Calendar ───────────────────────
        # Compute from last cycle's index regime cache + current VIX + breadth.
        # First cycle uses NORMAL (safe default). Cache updated at end of each cycle.
        market_ctx = await self._compute_market_context(india_vix)
        self._market_ctx = market_ctx

        # Seed upcoming NSE expiry events (idempotent upsert, fast).
        if self._event_svc:
            try:
                await self._event_svc.seed_nse_expiry_events()
            except Exception as _seed_exc:
                _log.debug("signal_scanner.event_seed_failed: %s", _seed_exc)

        # Pre-fetch event cache once per cycle (1 DB query for all 253 symbols).
        event_cache: dict = {}
        if self._event_svc:
            try:
                event_cache = await self._event_svc.get_global_event_cache(_ist_now())
            except Exception as _ec_exc:
                _log.warning(
                    "signal_scanner.event_cache_failed — event overlays disabled this cycle: %s",
                    _ec_exc,
                )

        # Phase 21.2: Pre-fetch portfolio context once per cycle for overlay pipeline.
        portfolio_ctx: "PortfolioContext | None" = None
        if self._portfolio_svc:
            try:
                portfolio_ctx = await self._portfolio_svc.get_scanner_portfolio_context()
            except Exception as _pc_exc:
                _log.warning(
                    "signal_scanner.portfolio_ctx_failed — heat/correlation/sector overlays "
                    "disabled this cycle: %s",
                    _pc_exc,
                )

        # ── TRACE 1: Universe load ────────────────────────────────────
        # get_active_symbols(fo_only=True) returns BOTH index futures (is_fo=True,
        # is_index=True) AND F&O stocks (is_fo=True, is_index=False)
        all_symbols = await self._universe.get_active_symbols(fo_only=True)
        index_futures = [s for s in all_symbols if s.is_index]
        fo_stocks     = [s for s in all_symbols if not s.is_index]

        # Scan ALL F&O symbols every cycle — no batching cap.
        # Indices first, then all stocks (shuffled so no sector gets
        # systematically last when a cycle overruns).
        shuffled_stocks = list(fo_stocks)
        random.shuffle(shuffled_stocks)
        candidates = index_futures + shuffled_stocks

        _log.info(
            "signal_scanner.universe_loaded "
            "total_fo=%d index_futures=%d fo_stocks=%d scanning=%d",
            len(all_symbols),
            len(index_futures),
            len(fo_stocks),
            len(candidates),
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
            "stale_candles",
        })
        gate_counts: dict[str, int] = {}
        symbol_timings: dict[str, float] = {}
        raw_results = await asyncio.gather(
            *[
                self._process_symbol_sem(sym, semaphore, india_vix, market_ctx, event_cache, portfolio_ctx)
                for sym in candidates
            ],
            return_exceptions=True,
        )
        for sym, res in zip(candidates, raw_results):
            if isinstance(res, Exception):
                errors += 1
                _log.warning(
                    "signal_scanner.symbol_exception type=%s msg=%s",
                    type(res).__name__, str(res),
                )
                symbol_timings[sym.symbol] = 0.0
            else:
                outcome, elapsed_ms = res
                symbol_timings[sym.symbol] = elapsed_ms
                if outcome == "accepted":
                    accepted += 1
                elif outcome == "rejected":
                    rejected += 1
                elif outcome in _GATE_OUTCOMES:
                    gated += 1
                    gate_counts[outcome] = gate_counts.get(outcome, 0) + 1
                else:
                    errors += 1

        _cycle_dur = time.monotonic() - _cycle_start

        # P95 / slowest symbol stats
        _timings_vals = sorted(symbol_timings.values()) if symbol_timings else []
        _p95_ms: float | None = None
        if _timings_vals:
            _p95_idx = max(0, int(len(_timings_vals) * 0.95) - 1)
            _p95_ms = _timings_vals[_p95_idx]
        _slowest_sym = max(symbol_timings, key=lambda s: symbol_timings[s], default=None) if symbol_timings else None
        _slowest_ms  = symbol_timings.get(_slowest_sym, 0.0) if _slowest_sym else None

        # Build per-gate breakdown for diagnostics (only show gates that fired)
        _gate_detail = " ".join(f"{g}={n}" for g, n in sorted(gate_counts.items()) if n > 0)
        _log.info(
            "signal_scanner.cycle_summary accepted=%d rejected=%d gated=%d errors=%d "
            "candidates=%d duration_secs=%.1f p95_ms=%.0f slowest=%s gates=[%s]",
            accepted, rejected, gated, errors, len(candidates), _cycle_dur,
            _p95_ms or 0, _slowest_sym or "n/a", _gate_detail,
        )
        # Alert when stale_candles dominates — indicates Kite historical API failure
        _stale = gate_counts.get("stale_candles", 0)
        if _stale > len(candidates) * 0.5:
            _log.warning(
                "signal_scanner.stale_candles_dominant stale=%d/%d — "
                "Kite historical data fetch likely failing; candles are from a prior trading day",
                _stale, len(candidates),
            )

        # Phase 22 §3: classify and store market regime snapshot once per cycle
        _regime_snap: dict | None = None
        if self._regime_snapshot_svc is not None:
            try:
                _breadth_latest = await self._breadth_svc.get_latest() if self._breadth_svc else None
                _bs = (_breadth_latest or {}).get("breadth_score", 0.0)
                _adr = (_breadth_latest or {}).get("advance_decline_ratio", 1.0)
                _nifty_regime = market_ctx.nifty_regime if market_ctx else "NORMAL"
                _event_active = bool(event_cache) if event_cache else False
                _regime_snap = await self._regime_snapshot_svc.classify_and_store(
                    vix=india_vix,
                    nifty_regime=_nifty_regime,
                    breadth_score=_bs,
                    advance_decline_ratio=_adr,
                    nifty_close=None,
                    event_active=_event_active,
                )
            except Exception as _rs_exc:
                _log.debug("signal_scanner.regime_snapshot_failed: %s", _rs_exc)

        # Phase 22 §12: record scan replay snapshot
        if self._scanner_replay_svc is not None:
            try:
                await self._scanner_replay_svc.record(
                    scan_duration_seconds=_cycle_dur,
                    total_candidates=len(candidates),
                    accepted=accepted,
                    rejected=rejected,
                    gated=gated,
                    symbol_results=[
                        {
                            "symbol": sym.symbol,
                            "outcome": (raw_results[i][0] if not isinstance(raw_results[i], Exception) else "error"),
                            "elapsed_ms": symbol_timings.get(sym.symbol, 0.0),
                        }
                        for i, sym in enumerate(candidates)
                    ],
                    gate_summary=gate_counts,
                    market_context={"nifty_regime": market_ctx.nifty_regime if market_ctx else None,
                                    "india_vix": india_vix},
                    regime_snapshot=_regime_snap,
                )
            except Exception as _rp_exc:
                _log.debug("signal_scanner.replay_record_failed: %s", _rp_exc)

        if self._scan_metrics is not None:
            exec_mode: str | None = None
            if self._exec_lock_svc is not None:
                try:
                    exec_mode = (await self._exec_lock_svc.get_mode()).value
                except Exception:
                    pass
            # Simple health score: 100 - error_rate_pct - stale_pct
            _total = len(candidates) or 1
            _health = max(0.0, 100.0 - (errors / _total * 50) - (_stale / _total * 30))
            await self._scan_metrics.record(
                scan_duration_seconds=round(_cycle_dur, 2),
                symbols_scanned=len(candidates),
                symbols_failed=errors,
                signals_generated=accepted,
                signals_rejected=rejected,
                signals_gated=gated,
                india_vix=india_vix,
                market_context=market_ctx.nifty_regime if market_ctx else None,
                execution_mode=exec_mode,
                gate_failures=gate_counts if gate_counts else None,
                symbol_timings=symbol_timings if symbol_timings else None,
                p95_symbol_time_ms=_p95_ms,
                slowest_symbol=_slowest_sym,
                slowest_symbol_ms=_slowest_ms,
                health_score=round(_health, 1),
                regime_snapshot=_regime_snap,
            )

        return {
            "accepted":   accepted,
            "rejected":   rejected,
            "gated":      gated,
            "errors":     errors,
            "candidates": len(candidates),
        }

    async def _process_symbol_sem(
        self,
        sym,
        semaphore: asyncio.Semaphore,
        india_vix: float | None = None,
        market_ctx: "MarketContextSnapshot | None" = None,
        event_cache: dict | None = None,
        portfolio_ctx: "PortfolioContext | None" = None,
    ) -> tuple[str, float]:
        """Returns (outcome, elapsed_ms). Applies 30-second per-symbol timeout."""
        _t0 = time.monotonic()
        async with semaphore:
            try:
                outcome = await asyncio.wait_for(
                    self._process_symbol(
                        sym, india_vix=india_vix, market_ctx=market_ctx,
                        event_cache=event_cache or {}, portfolio_ctx=portfolio_ctx,
                    ),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                _log.warning("signal_scanner.symbol_timeout symbol=%s", sym.symbol)
                outcome = "rejected"
        return outcome, round((time.monotonic() - _t0) * 1000, 1)

    async def _process_symbol(
        self,
        sym,
        india_vix: float | None = None,
        market_ctx: "MarketContextSnapshot | None" = None,
        event_cache: dict | None = None,
        portfolio_ctx: "PortfolioContext | None" = None,
    ) -> str:
        """Process one universe symbol through the full pipeline. Returns 'accepted'/'rejected'/'error'."""
        symbol   = sym.symbol
        sym_type = "INDEX" if sym.is_index else "STOCK"

        # ── Time-of-day hard gates (before any I/O) ───────────────────
        # Opening volatility (9:15-9:30 IST): first 15 min = price discovery chaos,
        # IV is dislocated, option spreads wide — no new entries.
        # Closing volatility (≥14:30 IST): a 55% option premium target needs ~2 hours
        # for the underlying to make a 1.5-2% move; signals after 14:30 have < 1 hour
        # and cannot realistically reach target before the 15:20 forced-exit.
        # Raised from 15:00 → 14:30 to ensure all published signals have viable time window.
        _now_ist = _ist_now().time()
        if _dtime(9, 15) <= _now_ist < _dtime(9, 30):
            return "opening_volatility"
        if _now_ist >= _dtime(14, 30):
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
            _log.warning("signal_scanner.candle_fetch_failed symbol=%s: %s", symbol, _fe)

        try:
            candles = await self._history.get_latest(symbol, "15m", _CANDLE_LIMIT)
        except Exception as _cl_exc:
            _log.warning("signal_scanner.candle_read_failed symbol=%s: %s", symbol, _cl_exc)
            return "rejected"
        if len(candles) < 20:
            _log.debug(
                "signal_scanner.skip symbol=%s reason=insufficient_candles count=%d",
                symbol, len(candles),
            )
            return "rejected"

        # ── Candle staleness gate ─────────────────────────────────────
        # Intraday option signals MUST be based on today's price action.
        # If fetch_and_store fails silently (Kite 403/timeout), we could be
        # running on data from a prior trading day — completely wrong for
        # ATM strike selection and momentum reading.
        # Gate: latest candle must be from today (IST). During market hours
        # a 15m candle is at most 15 min old; we also allow up to 45 min
        # to handle the 9:15-9:30 opening window and transient feed delays.
        _lc = candles[-1]
        _lc_ts_raw = getattr(_lc, "ts", None) or getattr(_lc, "date", None) or getattr(_lc, "timestamp", None)
        if _lc_ts_raw is not None:
            try:
                _lc_aware = _lc_ts_raw if getattr(_lc_ts_raw, "tzinfo", None) else _lc_ts_raw.replace(tzinfo=UTC)
                _lc_date_ist = (_lc_aware + _IST_OFFSET).date()
                _today_ist   = _ist_now().date()
                _lc_age_min  = (datetime.now(UTC) - _lc_aware).total_seconds() / 60
                if _lc_date_ist < _today_ist:
                    _log.warning(
                        "signal_scanner.stale_candles symbol=%s last_candle=%s today=%s age_min=%.0f — skipping",
                        symbol, _lc_date_ist, _today_ist, _lc_age_min,
                    )
                    return "stale_candles"
                if _lc_age_min > 45:
                    _log.warning(
                        "signal_scanner.stale_candles symbol=%s last_candle_age_min=%.0f > 45 — skipping",
                        symbol, _lc_age_min,
                    )
                    return "stale_candles"
            except Exception:
                pass  # if we can't parse timestamp, proceed and let scoring decide

        # ── TRACE 3: Feature computation ──────────────────────────────
        features = _compute_features(candles)
        if not features:
            _log.debug("signal_scanner.skip symbol=%s reason=feature_compute_failed", symbol)
            return "rejected"

        # For index instruments, the hv_iv_ratio is computed using the BB-width percentile
        # as an IV proxy (a rank, not an absolute value). This makes the ratio structurally
        # low for indices (NIFTY IV ≈ 10-15%; BB percentile ≈ 30-50% → ratio always ≪ 0.8)
        # causing a permanent "options expensive" flag that has no meaning for indices.
        # Null it out so the IV_ANALYSIS component skips the HV/IV bonus step for indices.
        if sym.is_index:
            features["hv_iv_ratio"] = None

        # Phase 21: override oi_change_pct with Futures OI cache (primary source).
        # Candle OI is always 0 for equity/index spot — the cache gives real sequential change.
        # Fail-open: if cache unavailable (not yet warmed, stale, FUT not found), the
        # candle-derived value (also None for spot) passes through unchanged — scanner continues.
        if self._futures_oi_svc is not None:
            _fut_snap = self._futures_oi_svc.get_cached(symbol)
            if _fut_snap is not None and _fut_snap.oi_change_pct is not None:
                features["oi_change_pct"] = _fut_snap.oi_change_pct
                _log.debug(
                    "signal_scanner.futures_oi symbol=%s oi=%d change_pct=%.2f direction=%s",
                    symbol, _fut_snap.oi, _fut_snap.oi_change_pct, _fut_snap.oi_direction,
                )

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

        # ── Phase 14: 5-minute MTF snapshot (fail-open — never blocks) ──
        # Fetch gap-filled 5m candles for the same symbol and compute a
        # lightweight MtfSnapshot (EMA20/50, ADX/DI, VWAP). The result
        # is stored in FeatureSnapshot.mtf_5m and in the features dict for
        # analytics. Missing 5m data yields mtf_5m=None; TrendComponent and
        # ConfidenceEngine both treat None as "no MTF adjustment".
        mtf_5m = None
        try:
            await self._history.fetch_and_store(symbol, "5m")
        except Exception as _fe5:
            _log.debug("signal_scanner.mtf_5m_fetch_failed symbol=%s: %s", symbol, _fe5)
        try:
            _candles_5m = await self._history.get_latest(symbol, "5m", 80)
            mtf_5m = _compute_5m_features(_candles_5m)
        except Exception as _ce5:
            _log.debug("signal_scanner.mtf_5m_compute_failed symbol=%s: %s", symbol, _ce5)

        # Compute MTF alignment for analytics (pre-engine; stored in features dict).
        # The actual score bonus is applied by TrendComponent — this is for attribution.
        if mtf_5m is not None:
            _bias_5m    = mtf_5m.bias()
            _15m_bull   = (features.get("di_plus", 0) or 0) > (features.get("di_minus", 0) or 0)
            _aligned_5m = (_15m_bull and _bias_5m == "BULLISH") or (not _15m_bull and _bias_5m == "BEARISH")
            _conflict_5m = (_15m_bull and _bias_5m == "BEARISH") or (not _15m_bull and _bias_5m == "BULLISH")
            features["mtf_alignment"] = _bias_5m
            features["mtf_score_bonus"] = (4.0 if mtf_5m.adx_rising else 2.0) if _aligned_5m else (-3.0 if _conflict_5m else 0.0)
            features["mtf_confidence_bonus"] = 5.0 if _aligned_5m else (-5.0 if _conflict_5m else 0.0)
            _log.info(
                "signal_scanner.mtf symbol=%s bias_5m=%s aligned=%s score_bonus=%.0f",
                symbol, _bias_5m, _aligned_5m, features["mtf_score_bonus"],
            )
        else:
            features["mtf_alignment"] = None
            features["mtf_score_bonus"] = None
            features["mtf_confidence_bonus"] = None

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

        # ── Phase 15: Data Quality Score (monitoring-only, never gates signals) ─
        try:
            from datetime import timezone as _tz
            _oc_age: float | None = None
            if oc_snap is not None:
                _oc_ts = oc_snap.snapshot_timestamp
                if _oc_ts.tzinfo is None:
                    _oc_ts = _oc_ts.replace(tzinfo=UTC)
                _oc_age = (datetime.now(UTC) - _oc_ts).total_seconds() / 60.0

            _last_candle_age: float | None = None
            if candles:
                _lc_ts = getattr(candles[-1], "ts", None) or getattr(candles[-1], "date", None) or getattr(candles[-1], "timestamp", None)
                if _lc_ts is not None and hasattr(_lc_ts, "hour"):
                    # candle timestamp is a datetime; compute age in minutes
                    _lc_aware = _lc_ts if getattr(_lc_ts, "tzinfo", None) else _lc_ts.replace(tzinfo=UTC)
                    _last_candle_age = (datetime.now(UTC) - _lc_aware).total_seconds() / 60.0

            # has_oi: prefer FuturesOIService (real data); fall back to candle-derived
            # oi_change_pct (always None for spot, so DQ penalises correctly when cache cold).
            _has_oi = (
                self._futures_oi_svc.has_data(symbol)
                if self._futures_oi_svc is not None
                else features.get("oi_change_pct") is not None
            )
            _dq_report = self._dq_service.compute(
                option_chain_age_minutes=_oc_age,
                has_oi=_has_oi,
                has_5m_candles=mtf_5m is not None,
                has_vix=india_vix is not None,
                has_gex=oc_snap is not None and oc_snap.gex_positive is not None,
                underlying_candle_age_minutes=_last_candle_age,
            )
            features["data_quality_score"] = _dq_report.score
            features["missing_sources"]    = _dq_report.missing_sources_json()
            _log.debug(
                "signal_scanner.data_quality symbol=%s score=%d missing=%s",
                symbol, _dq_report.score, _dq_report.missing_sources,
            )
        except Exception as _dq_exc:
            _log.debug("signal_scanner.data_quality_failed symbol=%s: %s", symbol, _dq_exc)
            features["data_quality_score"] = None
            features["missing_sources"]    = None

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
            mtf_5m=mtf_5m,
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
        try:
            result = await self._engine.process(req)
        except Exception as _eng_exc:
            _log.error(
                "signal_scanner.engine_failed symbol=%s type=%s: %s",
                symbol, type(_eng_exc).__name__, _eng_exc,
            )
            return "rejected"
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
        # Warn when an accepted signal has no option chain snapshot — OI wall gate
        # was skipped, which means the signal passed without wall clearance validation.
        if result.accepted and oc_snap is None:
            _log.warning(
                "signal_scanner.no_oc_snapshot symbol=%s direction=%s score=%.1f "
                "— OI wall + GEX checks skipped; proceeding on technicals only",
                symbol, result.direction, result.adjusted_score or 0.0,
            )

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
        # The engine already persisted the signal as RISK_APPROVED, so we must write
        # the analytics record here so the signal isn't orphaned (no analytics = shows
        # in UI as RISK_APPROVED with no option data, which is misleading).
        if result.accepted and option_play is None:
            _log.warning(
                "signal_scanner.no_contract_skip symbol=%s direction=%s — "
                "no option contract found; signal gated post-engine",
                symbol, result.direction,
            )
            if self._analytics is not None:
                try:
                    await self._analytics.record(
                        symbol_name=symbol,
                        exchange="NSE",
                        is_index=sym.is_index,
                        sector=getattr(sym, "sector", None),
                        request=req,
                        result=result,
                        features=features,
                        option_play=None,
                        overlay={"rejection_gate": "no_contract"},
                    )
                except Exception as _ae:
                    _log.debug("signal_scanner.no_contract_analytics_failed symbol=%s: %s", symbol, _ae)
            return "no_contract"

        # ── Phase 21.2: Unified Overlay Pipeline ────────────────────────────────
        # Runs AFTER all gates; only builds attribution, never rejects signals.
        # Index regime cache updated here so the NEXT cycle's market context
        # computation uses current index regimes (one-cycle lag prevents whipsaw).
        if sym.is_index:
            self._index_regime_cache[symbol] = str(regime)

        # Regime history READ before append (pipeline uses pre-append state).
        _regime_hist_snapshot = list(self._regime_history.get(symbol, []))

        _pctx = portfolio_ctx if portfolio_ctx is not None else PortfolioContext.empty()
        _ov_ctx = OverlayContext(
            symbol=symbol,
            is_index=sym.is_index,
            regime=str(regime),
            direction=result.direction or "NEUTRAL",
            engine_confidence=result.final_confidence or 0.0,
            engine_score=result.adjusted_score or 0.0,
            market_ctx=market_ctx,
            event_cache=event_cache or {},
            regime_history=_regime_hist_snapshot,
            ist_time=_now_ist,
            sector=getattr(sym, "sector", None),
            portfolio=_pctx,
        )

        # Lazy-create pipeline if not wired (safe default for backward compat).
        _pipeline = self._overlay_pipeline
        if _pipeline is None:
            from core.application.services.overlay_pipeline import OverlayPipeline
            _pipeline = OverlayPipeline()

        _ov_result = _pipeline.run(_ov_ctx)
        attribution: dict = _ov_result.attribution

        # Update regime history AFTER pipeline has read the pre-append snapshot.
        _hist = self._regime_history.setdefault(symbol, [])
        _hist.append(str(regime))
        if len(_hist) > 5:
            _hist.pop(0)

        # ── Phase 25 §2: Experiment A/B assignment — analytics only, never gates ──
        _ab_assignment: dict = {}
        if result.accepted and option_play is not None:
            try:
                from container import ApplicationContainer as _AC25
                _exp_svc = _AC25.experiment_service()
                _exp_id, _group = await _exp_svc.assign_signal(signal.signal_id)
                if _exp_id:
                    _ab_assignment = {"experiment_id": _exp_id, "ab_group": _group}
            except Exception as _ab_exc:
                _log.debug("signal_scanner.ab_assignment_failed symbol=%s: %s", symbol, _ab_exc)

        # ── Phase 24 §1+2: Expected Move Engine — analytics only, never gates ──
        _expected_move: dict = {}
        if result.accepted and option_play is not None:
            try:
                from core.application.services.expected_move_engine import ExpectedMoveEngine
                _close    = features.get("close") or req.entry_price or 0.0
                _atr      = features.get("atr") or 0.0
                _atr_pct  = (_atr / _close * 100) if _close > 0 else 0.0
                _atr_rat  = features.get("atr_ratio") or 1.0
                _iv_pct   = features.get("iv_percentile_proxy")
                _dte      = None
                if option_play.option_expiry:
                    from datetime import date as _dt_date
                    _exp = (option_play.option_expiry
                            if isinstance(option_play.option_expiry, _dt_date)
                            else _dt_date.fromisoformat(option_play.option_expiry[:10]))
                    _dte = (_exp - _dt_date.today()).days
                _em = ExpectedMoveEngine().compute(
                    atr_pct=_atr_pct,
                    india_vix=india_vix,
                    iv_percentile=_iv_pct,
                    delta=None,
                    gamma=None,
                    dte=_dte,
                    underlying_price=float(_close),
                    option_entry=float(option_play.entry),
                    configured_target_pct=getattr(option_play, "_configured_target_pct", 0.55),
                    configured_sl_pct=getattr(option_play, "_configured_sl_pct", 0.25),
                    regime=str(regime),
                    atr_ratio=float(_atr_rat),
                )
                _expected_move = {
                    "expected_underlying_move_pct": _em.expected_underlying_move_pct,
                    "expected_option_move_pct":     _em.expected_option_move_pct,
                    "expected_holding_minutes":     _em.expected_holding_minutes,
                    "reach_prob_json":              _em.reach_prob_json,
                    "recommended_target_pct":       _em.recommended_target_pct,
                    "recommended_stop_pct":         _em.recommended_stop_pct,
                    "recommended_holding_minutes":  _em.recommended_holding_minutes,
                    "target_confidence":            _em.target_confidence,
                }
            except Exception as _eme_exc:
                _log.debug("signal_scanner.expected_move_failed symbol=%s: %s", symbol, _eme_exc)

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
                overlay={**attribution, **_expected_move, **_ab_assignment},
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

    # ------------------------------------------------------------------
    # Phase 21.1 helpers — market context + regime stability overlay
    # ------------------------------------------------------------------

    async def _compute_market_context(
        self, india_vix: float | None
    ) -> "MarketContextSnapshot":
        """Compute market context using last cycle's index regime cache + VIX + breadth."""
        from core.domain.value_objects.market_context_snapshot import MarketContextSnapshot

        # Always update VIX history regardless of whether MCE is wired,
        # so _is_vix_rising() returns correct results even when MCE is absent.
        if india_vix is not None:
            self._vix_history.append(india_vix)
            if len(self._vix_history) > 10:
                self._vix_history.pop(0)

        if self._mce is None:
            return MarketContextSnapshot.normal()

        breadth = None
        if self._breadth_svc:
            try:
                breadth = await self._breadth_svc.get_latest()
            except Exception:
                pass

        try:
            snap = await self._mce.compute(
                index_regimes=self._index_regime_cache.copy(),
                vix=india_vix,
                vix_rising=self._is_vix_rising(india_vix),
                breadth=breadth,
            )
        except Exception as exc:
            _log.warning("signal_scanner.market_context_failed: %s", exc)
            return MarketContextSnapshot.normal()

        # PANIC → auto execution paused; operator must re-enable manually.
        if snap.level == "PANIC" and self._exec_lock_svc:
            try:
                state = await self._exec_lock_svc.get_state()
                if state.execution_mode != "MANUAL":
                    await self._exec_lock_svc.set_execution_mode("MANUAL", "market_context_engine")
                    _log.critical(
                        "signal_scanner.PANIC_MODE — auto execution paused "
                        "(VIX/regime/breadth): %s", snap.reason
                    )
            except Exception:
                _log.warning("signal_scanner.panic_lock_failed")

        return snap

    def _is_vix_rising(self, vix: float | None) -> bool:
        """Return True when current VIX is above the rolling average of last 3 readings."""
        if vix is None or len(self._vix_history) < 2:
            return False
        recent = self._vix_history[-3:]
        return vix > (sum(recent) / len(recent))

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

        # Phase 22 §1: Layer in Redis OC intel (call_wall, put_wall, liquidity, atm_iv)
        # Redis cache is warmer/more recent than DB snapshot; supplement DB-derived values.
        if self._oc_intel_worker is not None:
            try:
                _intel = await self._oc_intel_worker.get_cached(symbol)
                if _intel:
                    if call_wall_pct is None and _intel.get("resistance_strike") and close_price > 0:
                        _rs = float(_intel["resistance_strike"])
                        call_wall_pct = ((_rs - close_price) / close_price * 100) if _rs > close_price else call_wall_pct
                    if put_wall_pct is None and _intel.get("support_strike") and close_price > 0:
                        _ss = float(_intel["support_strike"])
                        put_wall_pct = ((close_price - _ss) / close_price * 100) if _ss < close_price else put_wall_pct
                    if iv_percentile is None and _intel.get("atm_iv"):
                        iv_percentile = float(_intel["atm_iv"])
                    if max_pain == 0.0 and _intel.get("max_pain"):
                        max_pain = float(_intel["max_pain"])
                    if pcr == 0.0 and _intel.get("pcr"):
                        pcr = float(_intel["pcr"])
            except Exception as _ic_exc:
                _log.debug("signal_scanner.oc_intel_read_failed symbol=%s: %s", symbol, _ic_exc)

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
