# Regime-Strategy Mapping — Phase 8

**Date**: 2026-06-16

---

## Market Regime Detection (SignalScannerService)

```python
if adx > 30:
    TRENDING_BULLISH (DI+ > DI-)  or  TRENDING_BEARISH (DI- > DI+)
elif bb_width_pct > 0.80:
    HIGH_VOLATILITY
elif adx < 15 and bb_width_pct < 0.30:
    LOW_VOLATILITY
else:
    SIDEWAYS
```

---

## Regime → Strategy Mapping

| Regime | Selected Strategy | Enabled Components | Disabled / Reduced |
|--------|------------------|-------------------|--------------------|
| `TRENDING_BULLISH` | `DIRECTIONAL` | TREND ×1.30, VOLUME ×1.10, VWAP ×1.10 | IV ×0.70 |
| `TRENDING_BEARISH` | `DIRECTIONAL` | TREND ×1.30, VOLUME ×1.10, VWAP ×1.10, OC ×1.10 | — |
| `HIGH_VOLATILITY` | `VOLATILITY` | OC ×1.25, IV ×1.60, SENTIMENT ×1.20 | TREND ×0.60, VWAP ×0.70 |
| `SIDEWAYS` | `MEAN_REVERSION` | VWAP ×1.30 (mean-rev mode), OC ×1.40, IV ×1.40 | TREND ×0.25 |
| `LOW_VOLATILITY` | `BREAKOUT` | OC ×1.10, IV ×1.60 | TREND ×0.70, VOLUME ×0.90 |

---

## VWAP Component Mode Switching

| Regime | Mode | Interpretation |
|--------|------|---------------|
| `SIDEWAYS` | Mode A — Mean Reversion | Price 1.5σ below VWAP → LONG setup |
| `HIGH_VOLATILITY` | Mode A — Mean Reversion | Extended moves expected to reverse |
| `LOW_VOLATILITY` | Mode A — Mean Reversion | Tight range; VWAP acts as magnet |
| `TRENDING_BULLISH` | Mode B — Trend Continuation | Price above VWAP = bullish confirmation |
| `TRENDING_BEARISH` | Mode B — Trend Continuation | Price below VWAP = bearish confirmation |

---

## Regime Distribution Expectation (NSE F&O Universe)

Based on 49k candles stored for 50 F&O stocks (60 days, 15m bars):

| Regime | Expected Frequency | Trading Action |
|--------|------------------|----------------|
| SIDEWAYS | ~60% of observations | Mean-reversion via VWAP |
| TRENDING_BULLISH | ~15% | Directional LONG |
| TRENDING_BEARISH | ~15% | Directional SHORT |
| HIGH_VOLATILITY | ~8% | Volatility strategies (no OC data available) |
| LOW_VOLATILITY | ~2% | Breakout watch |
