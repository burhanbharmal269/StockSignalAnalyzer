# Recommended Intraday Strategy Mix — Phase 8

**Date:** 2026-06-18  
**Note:** Backtesting numbers below are derived from signal outcome tracking data
in the system. No data has been invented. Sections marked [Pending Data] require
accumulated live signal performance before population.

---

## Priority Strategy Combinations

### 1. EMA Trend + OI Confirmation (Primary)

**Signal criteria:**
- ADX > 25 on 15m (TREND component gate)
- EMA 20 > EMA 50 > EMA 200 (full alignment) for LONG
- Long Build-up (OI ↑ + Price ↑) with OI change > 1.8%
- OFI confluence: PCR ≥ 1.0 for LONG / ≤ 0.9 for SHORT

**Expected score:** 55–75 (TREND up to 20 + OI_BUILDUP up to 28 with bonus)

**Regime weight advantage:** TRENDING_BULLISH — TREND 1.40×, VWAP 1.50×

**Recommended instruments:** NIFTY weekly CE/PE, BANKNIFTY weekly CE/PE

**Backtest data:** [Pending — requires 30+ live signals with outcome tracking]

---

### 2. VWAP Pullback + EMA Trend (High Precision)

**Signal criteria:**
- Price bouncing off VWAP with VWAP deviation sigma in [0.1, 0.35]
- ADX > 20 (moderate trend — don't need strong trend for VWAP pullback)
- Price above EMA 20 for LONG (below for SHORT)
- VWAP Mode B score = 10.0 (max — bounce confirmation)

**Expected score:** 50–65

**Best time window:** 9:30–11:30 IST (VWAP establishing direction), 2:00–2:30 IST (final trend extension)

**Recommended instruments:** NIFTY, BANKNIFTY, liquid large-cap options

**Backtest data:** [Pending]

---

### 3. ORB + Volume Expansion + OI Confirmation (Momentum)

**Signal criteria:**
- First 15m candle establishes range
- Breakout candle: volume ratio > 1.5× (15m bar volume vs 20-bar average)
- OI buildup confirming direction in first 30 minutes
- Best on high-OFI days (PCR confluence)

**Expected score:** 45–60

**Best time window:** 9:15–10:15 IST (opening range)

**Recommended instruments:** BANKNIFTY options (highest intraday volatility), FINNIFTY

**Backtest data:** [Pending — requires tagging first-candle breakout signals separately]

---

## Strategy Mix Allocation (Suggested)

Given ₹1,50,000 capital and intraday option buying:

| Strategy | Allocation | Max Simultaneous Trades | Target Signals/Day |
|---|---|---|---|
| EMA + OI Confirmation | 50% = ₹75,000 | 2–3 lots | 3–5 |
| VWAP Pullback | 30% = ₹45,000 | 1–2 lots | 2–3 |
| Volume Expansion / ORB | 20% = ₹30,000 | 1 lot | 1–2 |

---

## What to Validate First (User Directive)

Per user request: **prioritize validation of ORB + Volume Expansion + OI Confirmation
and EMA Trend + OI Confirmation** on actual historical data before adding complexity.

Steps:
1. Run system in MANUAL mode through 2–3 full market sessions
2. Review signal outcome tracker results (MFE/MAE/30m return)
3. Filter by strategy_type and regime to isolate each combination
4. If win rate > 55% and profit factor > 1.5 for top 2 combinations → expand
5. If win rate < 45% → inspect which component is failing (use score breakdown)
