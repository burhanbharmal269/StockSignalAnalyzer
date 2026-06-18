# Intraday Strategy Ranking — Phase 7

**Date:** 2026-06-18  
**Scope:** Evaluation of existing strategies for intraday NSE F&O suitability

---

## Existing Strategy Components

The system has 7 scoring components, each contributing to the overall signal score.
The table below rates each for intraday index option suitability.

| Component | Intraday Suitability | Weight (Trending) | Notes |
|---|---|---|---|
| VWAP | ★★★★★ Excellent | 1.50× | #1 intraday indicator. VWAP bounce in trend direction = highest confidence entry |
| TREND (ADX+EMA) | ★★★★☆ Very Good | 1.40× | ADX > 25 on 15m = confirmed momentum. EMAs align quickly intraday |
| OI_BUILDUP | ★★★★☆ Very Good | 1.15× | Fresh OI buildup on index = institutional entry — strong intraday signal |
| VOLUME | ★★★★☆ Very Good | 1.25× | Volume surge on 15m candle = breakout confirmation |
| OPTION_CHAIN | ★★★☆☆ Good | 0.85× | PCR + OI walls useful but 0-DTE chains change rapidly — lag risk |
| IV_ANALYSIS | ★★☆☆☆ Moderate | 0.45× | Less relevant intraday; DTE-aware gate handles IV structurally |
| SENTIMENT | ★☆☆☆☆ Low | 0.40× | NeutralProvider always returns 2.5 pts — noise, not signal |

---

## Strategy Rankings for Intraday Index Options

### Rank 1: EMA Trend + OI Confirmation

**Components:** TREND (ADX + EMA alignment) + OI_BUILDUP (Long/Short buildup)

**Why it works intraday:**
- ADX > 25 on 15m confirms momentum is not noise
- Long Build-up (OI ↑, Price ↑) = institutions initiating fresh longs — not just covering
- OFI confluence bonus (+3 pts) fires when PCR also confirms → strongest signal in system
- Works on NIFTY/BANKNIFTY index options with 0-3 DTE

**Ideal regime:** TRENDING_BULLISH / TRENDING_BEARISH

---

### Rank 2: VWAP Pullback + Regime Filter

**Components:** VWAP (Mode B — bounce in trend direction) + regime classification

**Why it works intraday:**
- VWAP bounce on 15m in trending regime = high-probability reentry with defined risk
- Mode B score 10.0 (max) at bounce point = system gives full weight
- Works best in first 2 hours of session when VWAP is establishing itself
- `bounce_proximity_sigma = 0.35` catches tight pullbacks

**Ideal regime:** TRENDING_BULLISH / TRENDING_BEARISH

---

### Rank 3: Volume Expansion + Momentum

**Components:** VOLUME (vol ratio > 2.0 = max 15 pts) + TREND

**Why it works intraday:**
- Volume ratio > 2× average = institutional participation
- Combined with trend confirmation = breakout quality
- Works on both index and liquid stock options

**Ideal regime:** TRENDING (any direction) or HIGH_VOLATILITY (with vol spike)

---

### Rank 4: OI Build-up + PCR Confluence (OFI)

**Components:** OI_BUILDUP with OFI confluence bonus (Phase: previous session)

**Why it works intraday:**
- Specifically designed to catch dual institutional signal
- Long Build-up + PCR ≥ 1.0 = both futures OI AND options market confirm direction
- +3 pts bonus raises marginal signals above gate

**Ideal regime:** Any (regime-independent — driven by institutional flow data)

---

### Rank 5: ORB (Opening Range Breakout)

**Status:** Not currently a discrete strategy in the system. The existing regime
classifier captures HIGH_VOLATILITY (gap opens) and TRENDING (ORB follow-through)
implicitly. A dedicated ORB strategy layer would require checking first 15m candle
high/low — feasible as a future scoring component without architecture change.

---

## Strategies NOT Suitable for Intraday Options

| Strategy | Reason |
|---|---|
| Mean reversion (SIDEWAYS regime) | Works for selling premium, not buying CE/PE |
| Low volatility iron condor | Requires 7-15 DTE — incompatible with 0-3 DTE |
| Swing OI buildup (weekly) | Multi-day OI accumulation not visible on 15m candles |
