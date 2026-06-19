"""MtfSnapshot — lightweight 5-minute candle indicator bag for MTF overlay.

Phase 14 adds Multi-Timeframe Confirmation as a TrendComponent overlay.
Only the fields needed to determine directional bias are computed —
this is NOT a second FeatureSnapshot; it is a minimal alignment check.

Bias rules (two confirmations required to avoid noise):
  BULLISH  — EMA20 > EMA50  AND  DI+ > DI-
  BEARISH  — EMA20 < EMA50  AND  DI- > DI+
  NEUTRAL  — anything else (partial, conflicting, or missing data)

The adx_rising flag unlocks the +4 bonus (vs +2) in TrendComponent
when the 5m trend is accelerating in the same direction as the 15m signal.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MtfSnapshot:
    """5-minute indicator bag. Populated by SignalScannerService before scoring."""

    adx: float | None = None
    di_plus: float | None = None
    di_minus: float | None = None
    adx_rising: bool = False         # ADX(t) > ADX(t-3) on 5m
    ema_20: float | None = None
    ema_50: float | None = None
    close_price: float | None = None
    vwap: float | None = None        # session-only VWAP on 5m
    volume_ratio: float | None = None  # current 5m bar vol / 20-bar avg
    last_candle_bullish: bool | None = None  # last bar close > open

    def bias(self) -> str:
        """Return 'BULLISH', 'BEARISH', or 'NEUTRAL'.

        Requires BOTH EMA cross AND DI-spread agreement to avoid false
        confirmations from low-volume 5m bars near session open/close.
        """
        ema_bull = (
            self.ema_20 is not None
            and self.ema_50 is not None
            and self.ema_20 > self.ema_50
        )
        ema_bear = (
            self.ema_20 is not None
            and self.ema_50 is not None
            and self.ema_20 < self.ema_50
        )
        di_bull = (
            self.di_plus is not None
            and self.di_minus is not None
            and self.di_plus > self.di_minus
        )
        di_bear = (
            self.di_plus is not None
            and self.di_minus is not None
            and self.di_minus > self.di_plus
        )

        if ema_bull and di_bull:
            return "BULLISH"
        if ema_bear and di_bear:
            return "BEARISH"
        return "NEUTRAL"
