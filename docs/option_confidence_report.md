# Option Confidence Scoring Report — Phase 10

**Date:** 2026-06-18

---

## Current Confidence Model

Confidence is computed by `ConfidenceEngineService` using `ConfidenceCalculator`.
It is separate from the raw/adjusted score and incorporates:

- Component consistency (agreement across components)
- Historical win rate for this signal's strategy+regime combination
- Data completeness (how many of 7 components had data vs. were unavailable)
- Direction conviction (how strongly one direction dominated the other)

The signal's `confidence` field (0.0–1.0) is displayed in the dashboard.

---

## Confidence Components for Intraday

| Component | Weight | Intraday Relevance |
|---|---|---|
| Trend Score | High | ADX + EMA alignment on 15m directly predicts momentum duration |
| Volume Score | High | Volume surge at entry = institutional participation = follow-through |
| OI Score | High | Fresh OI buildup = new positions, not unwinding |
| Liquidity Score | Medium | OI-based; proxy only — no bid-ask data |
| Regime Score | Medium | Regime alignment (TRENDING regime for momentum plays) |
| News Score | Low | NeutralSentimentProvider = neutral always |
| Historical Win Rate | High (future) | Requires accumulated live signal data — grows over time |

---

## Confidence Display in Dashboard

Added to `signals-view.tsx`:

- **≥ 65%**: Green — high confidence
- **50–64%**: Amber — moderate confidence  
- **< 50%**: Gray — low confidence

---

## Interpretation Guide

| Score | Confidence | Action |
|---|---|---|
| ≥ 65, Conf ≥ 65% | Grade A, High | Full position sizing per risk model |
| ≥ 65, Conf 50-64% | Grade A, Moderate | Consider half-size entry |
| 40-64, Conf ≥ 50% | Grade B | Tight SL, smaller lot |
| < 65, Conf < 50% | Weak | Pass — wait for better setup |

---

## Future Enhancement: Options-Specific Confidence

Intraday option confidence should ideally incorporate:

1. **Gamma exposure**: GEX data already exists in `OptionChainSnapshot.net_gex`.
   Positive GEX = market makers long gamma = resistance to large moves. Negative GEX
   = dealers short gamma = moves can accelerate. Negative GEX + LONG signal = higher
   confidence for CE buying.

2. **IV trend**: IV expanding = good to buy CE/PE; IV contracting = IV crush risk.
   Not currently tracked per-symbol (would require OptionChainSnapshot schema extension).

3. **PCR trend direction**: `pcr_trend` field in OptionChainSnapshot already tracked.
   `RISING` PCR during LONG signal = institutions buying put protection = bullish.
