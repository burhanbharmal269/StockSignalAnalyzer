# 20 — Market Regime Engine

**Platform:** NSE · Indian Equity FnO  
**Primary Reference:** Nifty 50 Index (regime anchor for all instruments)  
**Secondary Reference:** India VIX (fear/volatility dimension)  
**Version:** 1.0  

---

## Design Philosophy

> **Every strategy weight in this platform is conditional on regime.**  
> A signal that is correct in TRENDING_BULLISH is destructive in SIDEWAYS.  
> Regime classification is not an input to the signal — it IS the foundation.

### Why Indian Markets Need a Custom Regime Engine

Indian FnO markets behave differently from US markets in three structural ways:

**1. India VIX is the Primary Volatility Gauge**  
Unlike US markets (where VIX futures exist and are tradeable), India VIX is a single index with no futures. VIX behavior in India is dominated by: election uncertainty, RBI policy surprises, FII flows, and global risk-off events. India VIX above 20 is a structurally different market from India VIX below 15.

**2. FII Dominance Creates Regime-Defining Flows**  
FIIs hold ~20–22% of Nifty 50 float. When FIIs exit, regimes shift within days, not weeks. A high-conviction bearish regime in India is almost always accompanied by sustained FII selling. Tracking FII net positions is regime intelligence that has no equivalent in most other markets.

**3. Expiry-Driven Volatility is Calendar-Predictable**  
Every Wednesday (BANKNIFTY), Thursday (NIFTY), Tuesday (FINNIFTY), Monday (MIDCPNIFTY) carries structural high-volatility risk due to expiry. The regime engine must account for this predictable volatility cycle.

### What the Regime Engine Produces

The Regime Engine outputs:

```
RegimeState:
  primary_regime:   TRENDING_BULLISH | TRENDING_BEARISH | SIDEWAYS | HIGH_VOLATILITY | LOW_VOLATILITY
  regime_confidence: 0–100 (how certain we are about this regime)
  secondary_regime:  Any of the 5 (may co-exist with primary at lower confidence)
  volatility_layer:  HIGH | NORMAL | LOW (independent of directional regime)
  direction_layer:   BULLISH | BEARISH | NEUTRAL (independent of volatility)
  regime_duration:   How many bars this regime has been active
  transition_signal: TRUE if regime change is likely within next 3 bars
  detected_at:       Timestamp
```

---

## Two-Layer Architecture

The regime engine does not classify a single dimension — it classifies two independent dimensions and combines them into a final regime label.

```
LAYER 1: TREND / DIRECTION LAYER
  Input: ADX, EMA alignment, Supertrend, Higher High/Lower Low structure
  Output: BULLISH | BEARISH | NEUTRAL

LAYER 2: VOLATILITY LAYER
  Input: India VIX, ATR ratio, Bollinger Band Width, IV Percentile
  Output: HIGH | NORMAL | LOW

COMBINATION → FINAL REGIME:
  BULLISH + NORMAL/HIGH   → TRENDING_BULLISH
  BEARISH + NORMAL/HIGH   → TRENDING_BEARISH
  NEUTRAL + NORMAL        → SIDEWAYS
  ANY  + HIGH (VIX > 22)  → HIGH_VOLATILITY (primary if VIX > 22 AND no strong trend)
  ANY  + LOW (VIX < 13)   → LOW_VOLATILITY (primary if VIX < 13 AND no strong trend)
  BULLISH + HIGH          → TRENDING_BULLISH (primary) + HIGH_VOLATILITY (secondary modifier)
  BEARISH + HIGH          → TRENDING_BEARISH (primary) + HIGH_VOLATILITY (secondary modifier)
```

### Resolution Priority

When primary layers conflict, this priority order resolves the final regime label:

1. **VIX > 28:** Always HIGH_VOLATILITY regardless of trend — panic markets override all
2. **VIX > 22 + ADX < 25:** HIGH_VOLATILITY (no trend strong enough to override)
3. **VIX > 22 + ADX > 25:** TRENDING (direction) as primary, HIGH_VOLATILITY as secondary modifier
4. **VIX < 13 + ADX < 25:** LOW_VOLATILITY (complacency phase)
5. **VIX < 13 + ADX > 25:** LOW_VOLATILITY as primary (slow melt-up needs different handling)
6. **VIX 13–22 + ADX > 25 + DI+ > DI-:** TRENDING_BULLISH
7. **VIX 13–22 + ADX > 25 + DI- > DI+:** TRENDING_BEARISH
8. **VIX 13–22 + ADX < 20:** SIDEWAYS

---

## Input Data Sources

### Price and Trend Data

| Indicator | Timeframe | Source | Computation |
|-----------|-----------|--------|-------------|
| ADX(14) with DI+, DI− | 15-min (intraday) + 1H (bias) | Kite tick → computed | Standard Wilder ADX |
| EMA(20), EMA(50), EMA(200) | 1H + Daily | Kite OHLCV | Standard EMA |
| Supertrend(10, 3) | 15-min | Kite OHLCV | ATR-based Supertrend |
| ATR(14) | 15-min | Kite OHLCV | Wilder ATR |
| ATR 20-period SMA | 15-min | Computed | SMA of ATR values |
| ATR Ratio | 15-min | Computed | ATR(current) / ATR_SMA(20) |
| Bollinger Band Width | 1H | Computed | (Upper − Lower) / Middle × 100 |
| BB Width Percentile | 1H | Computed | Rolling 252-day percentile of BB Width |
| Higher High / Lower Low | Daily | Computed | Swing point detection on daily close |
| VWAP | Session (intraday) | Kite tick | Session-cumulative |

### Volatility Data

| Indicator | Source | Update Frequency | Notes |
|-----------|--------|-----------------|-------|
| India VIX | NSE (IDataProvider.get_quote) | Every 60 seconds | Primary volatility gauge |
| India VIX 10-day SMA | Computed | Daily | Trend of fear |
| India VIX Percentile (1-year) | Computed | Daily (07:40 IST) | Rolling 252-day percentile |
| India VIX Intraday Change % | Computed | Real-time | (Current / Open − 1) × 100 |
| IV Percentile (Option Chain) | NSE Option Chain | Every 60 seconds | ATM IV vs 1-year rolling |
| Historical Volatility 10d | Computed | After each candle close | 10-day realized daily vol |
| HV/IV Ratio | Computed | Every 60 seconds | HV10 / ATM IV |

### Market Breadth Data

| Indicator | Source | Update Frequency | Notes |
|-----------|--------|-----------------|-------|
| NSE Advance-Decline Ratio | NSE Market Data | Every 30 seconds | Total advances / Total declines |
| Nifty 50 Above 200 DMA % | NSE Constituent Data | Daily (07:40 IST) | % of Nifty 50 stocks > 200 DMA |
| FII Net Futures Position | NSE Bhav Copy (EOD) | Daily 06:00 IST | Long − Short contracts |
| FII Net Options Delta | NSE EOD Bhav | Daily | Approximate from CE − PE open interest |
| NIFTY vs BANKNIFTY Divergence | Computed | Every 15 min | Relative return: BANKNIFTY − NIFTY |
| SGX/Gift Nifty pre-market | IDataProvider | Pre-open (08:00–09:14 IST) | Overnight gap indicator |

### Data Refresh Schedule

| Data Type | Refresh Trigger |
|-----------|----------------|
| Trend indicators (ADX, EMA, ATR) | After each 15-minute candle close |
| India VIX | Every 60 seconds (market hours) |
| Option chain (IV, OI) | Every 60 seconds |
| Advance-Decline ratio | Every 30 seconds |
| FII positions | Daily at 06:00 IST (previous day EOD) |
| BB Width Percentile | Daily at 07:45 IST |
| Regime re-evaluation | Every 15 minutes (post-candle close) |

---

## Regime 1: TRENDING_BULLISH

**Definition:** A sustained directional upward move with measurable momentum and breadth, in an environment of controlled fear.

### Conditions

**Hard Gates (ALL must be true for confidence > 50):**
- ADX(14) >= 25 on 15-minute timeframe
- DI+ > DI− by >= 5 points
- Price > EMA(20) on 1-hour timeframe
- India VIX < 20 (trending bull markets rarely sustain above 20 VIX)

**Supporting Conditions (each adds to confidence):**
- EMA(20) > EMA(50) > EMA(200) on 1-hour chart (full alignment)
- Supertrend(10,3) bullish on 15-minute chart
- Nifty 50 making Higher Highs and Higher Lows on daily chart (last 5 sessions)
- Advance-Decline ratio > 1.2 (rally is broad, not narrow)
- Nifty 50 Above 200 DMA % >= 60% (most Nifty stocks in uptrend)
- Futures basis: premium stable or expanding over last 60 minutes
- FII net buying on 3+ consecutive days (sustained accumulation)

### Confidence Calculation (0–100)

If any Hard Gate is violated → maximum confidence = 30.

If all Hard Gates pass, confidence starts at 40 and points are added:

| Component | Measurement | Points Awarded |
|-----------|-------------|---------------|
| ADX level | 25–28 | +8 |
| ADX level | 28–32 | +13 |
| ADX level | > 32 | +18 |
| EMA alignment | All 3 aligned (20>50>200) | +15 |
| EMA alignment | Only 20>50 aligned | +7 |
| DI+ spread | DI+ − DI− = 5–10 | +5 |
| DI+ spread | DI+ − DI− > 10 | +10 |
| Supertrend | Bullish (15m) | +8 |
| India VIX | < 14 | +8 |
| India VIX | 14–16 | +5 |
| India VIX | 16–18 | +3 |
| India VIX | 18–20 | +0 |
| A-D Ratio | > 1.5 | +8 |
| A-D Ratio | 1.2–1.5 | +4 |
| Nifty 50 Above 200 DMA | >= 70% | +5 |
| Nifty 50 Above 200 DMA | 60–70% | +3 |
| FII net buying | 3+ consecutive days | +4 |
| Futures basis | Expanding premium | +3 |
| Higher High / Higher Low | Both confirmed on daily | +6 |

**Maximum achievable: 100**  
**Useful threshold: >= 60 to declare TRENDING_BULLISH as active primary regime**

### Scoring Impact on Signal Engine

When TRENDING_BULLISH is active at confidence >= 60:

| Strategy Component | Base Weight | Multiplier | Effective Weight | Reason |
|-------------------|-------------|-----------|-----------------|--------|
| OI Build-up | 25 | **1.20×** | 30 | Long build-up most reliable in trends |
| Trend Following | 20 | **1.30×** | 26 | Primary signal — amplify |
| Option Chain | 20 | **1.00×** | 20 | Normal weight |
| Volume Analysis | 15 | **1.10×** | 16.5 | Volume trend more meaningful |
| VWAP (Trend Mode) | 10 | **1.10×** | 11 | Trend confirmation, not reversion |
| Sentiment | 5 | **1.00×** | 5 | Normal weight |
| IV Analysis | 5 | **0.70×** | 3.5 | IV less dominant in directional trends |

> All weights are normalized to sum to 100 after multipliers are applied.  
> VWAP operates in **TREND MODE** (bounce off VWAP = entry signal) — not mean-reversion mode.

**Regime Mismatch Penalty:**  
Any SHORT signal generated in TRENDING_BULLISH regime receives a −20 confidence penalty (counter-trend trade — requires very high score to overcome).

---

## Regime 2: TRENDING_BEARISH

**Definition:** A sustained directional downward move with building bearish momentum, typically accompanied by rising fear (VIX) and FII selling.

### Conditions

**Hard Gates (ALL must be true for confidence > 50):**
- ADX(14) >= 25 on 15-minute timeframe
- DI− > DI+ by >= 5 points
- Price < EMA(20) on 1-hour timeframe

> Note: India VIX gate is NOT applied here. Bear markets frequently have VIX > 20.  
> If VIX > 22 AND ADX > 25 bearish: TRENDING_BEARISH is primary, HIGH_VOLATILITY is secondary modifier.

**Supporting Conditions:**
- EMA(20) < EMA(50) < EMA(200) on 1-hour chart (full bear alignment)
- Supertrend(10,3) bearish on 15-minute chart
- Nifty 50 making Lower Highs and Lower Lows on daily chart
- Advance-Decline ratio < 0.8 (broad selling, not isolated)
- Nifty 50 Above 200 DMA % <= 40% (most Nifty stocks in downtrend)
- Futures basis: discount developing or premium shrinking
- FII net selling on 3+ consecutive days
- India VIX rising intraday (fear building into the move)

### Confidence Calculation (0–100)

If any Hard Gate is violated → maximum confidence = 30.

If all Hard Gates pass, confidence starts at 40:

| Component | Measurement | Points |
|-----------|-------------|--------|
| ADX level | 25–28 | +8 |
| ADX level | 28–32 | +13 |
| ADX level | > 32 | +18 |
| EMA alignment | All 3 bear-aligned (20<50<200) | +15 |
| EMA alignment | Only 20<50 | +7 |
| DI− spread | DI− − DI+ = 5–10 | +5 |
| DI− spread | DI− − DI+ > 10 | +10 |
| Supertrend | Bearish (15m) | +8 |
| India VIX | Rising and > 18 | +5 |
| India VIX | Rising and > 22 | +8 |
| A-D Ratio | < 0.7 | +8 |
| A-D Ratio | 0.7–0.8 | +4 |
| FII net selling | 3+ consecutive days | +6 |
| Futures basis | Discount or shrinking premium | +4 |
| Lower High / Lower Low | Both confirmed on daily | +6 |

### Scoring Impact on Signal Engine

When TRENDING_BEARISH is active at confidence >= 60:

| Strategy Component | Base Weight | Multiplier | Effective Weight | Reason |
|-------------------|-------------|-----------|-----------------|--------|
| OI Build-up | 25 | **1.20×** | 30 | Short build-up most reliable in downtrends |
| Trend Following | 20 | **1.30×** | 26 | Primary signal for SHORT trades |
| Option Chain | 20 | **1.10×** | 22 | Put OI analysis more important in bear |
| Volume Analysis | 15 | **1.10×** | 16.5 | Volume surge on down moves = capitulation clue |
| VWAP (Trend Mode) | 10 | **1.10×** | 11 | Resistance at VWAP in downtrend |
| Sentiment | 5 | **1.20×** | 6 | Negative sentiment carries more weight in bear |
| IV Analysis | 5 | **1.10×** | 5.5 | IV rising = amplify short signals |

**Regime Mismatch Penalty:**  
Any LONG signal in TRENDING_BEARISH receives −20 confidence penalty.

---

## Regime 3: SIDEWAYS

**Definition:** A market without directional conviction — price oscillates within a bounded range, ADX is low, and no sustained trend exists. The most common regime in Indian markets (~40–50% of trading days).

### Conditions

**Hard Gate:**
- ADX(14) < 22 on 15-minute timeframe (if ADX >= 22, regime confidence is capped at 35)

**Supporting Conditions:**
- EMA(20) and EMA(50) are entangled: separation < 0.3% of price
- Bollinger Band Width in the lower 40th percentile of its 1-year range (bands are contracting)
- Price has traded between the same support and resistance for >= 5 sessions (range established)
- ATR Ratio < 0.9 (current ATR below recent average — contracting volatility)
- Advance-Decline ratio oscillating near 1.0 (no sustained breadth in either direction)
- India VIX stable — not spiking, not collapsing (range: 14–20)
- Option chain: PCR oscillating between 0.8–1.2 (no strong directional option flow)

### Range Detection Algorithm

A market is classified as SIDEWAYS when a definable price range exists:

```
Sideways Range Detection:
  Step 1: Identify last 3 significant swing highs and swing lows on 1H chart
  Step 2: Compute range_high = average of 3 swing highs
  Step 3: Compute range_low = average of 3 swing lows
  Step 4: Range width = (range_high - range_low) / midpoint
  Step 5: If range_width < 3% AND price has tested both sides >= 2 times: CONFIRMED RANGE
  Step 6: Range midpoint = equilibrium price (mean-reversion target)
  Step 7: Range age: number of sessions since range first established
```

### Confidence Calculation (0–100)

| Component | Measurement | Points |
|-----------|-------------|--------|
| ADX | < 15 | +30 |
| ADX | 15–18 | +22 |
| ADX | 18–22 | +12 |
| ADX | >= 22 | +0 (cap at 35) |
| BB Width Percentile | < 20th percentile | +20 |
| BB Width Percentile | 20–35th percentile | +12 |
| BB Width Percentile | 35–50th percentile | +6 |
| Range confirmation | Both sides tested >= 2 times | +15 |
| Range confirmation | Both sides tested once | +8 |
| ATR Ratio | < 0.7 | +12 |
| ATR Ratio | 0.7–0.9 | +7 |
| Range duration | > 10 sessions | +10 |
| Range duration | 5–10 sessions | +6 |
| Range duration | 2–5 sessions | +3 |
| A-D Ratio | Between 0.9–1.1 | +5 |
| India VIX | Stable (< ±10% in 5 days) | +5 |
| PCR | Between 0.8–1.2 | +3 |

**Maximum: 100**  
**Useful threshold: >= 55 to declare SIDEWAYS as active**

### Scoring Impact on Signal Engine

When SIDEWAYS is active at confidence >= 55:

| Strategy Component | Base Weight | Multiplier | Effective Weight | Reason |
|-------------------|-------------|-----------|-----------------|--------|
| OI Build-up | 25 | **1.00×** | 25 | PCR and Max Pain more important than futures OI |
| Trend Following | 20 | **0.25×** | 5 | ADX gate makes trend signals nearly useless |
| Option Chain | 20 | **1.40×** | 28 | Option chain is primary in range-bound — OI walls, PCR |
| Volume Analysis | 15 | **1.00×** | 15 | Volume at range boundaries is key |
| VWAP (Reversion Mode) | 10 | **1.30×** | 13 | Mean-reversion — VWAP is magnetic |
| Sentiment | 5 | **1.00×** | 5 | Normal weight |
| IV Analysis | 5 | **1.40×** | 7 | Short volatility strategies are structurally advantaged |

> VWAP operates in **MEAN-REVERSION MODE** in SIDEWAYS regime.  
> Trend following signals receive zero confidence from regime (not rejected — just near-zero weight).

**Sideways Regime Entry Discipline:**  
Only trade from range boundaries — not from the middle. Minimum score to generate a signal is raised to **75** (vs 70 normally) to filter out mid-range noise.

---

## Regime 4: HIGH_VOLATILITY

**Definition:** A market where fear, uncertainty, or an event has caused abnormally large intraday price ranges, elevated India VIX, and expanded option premiums. Directional conviction may exist but is frequently interrupted.

### Conditions

**Hard Gate:**
- India VIX > 20 OR ATR Ratio > 1.5 (at least one must be true)

**Sub-classification:** HIGH_VOLATILITY has three sub-types that affect strategy differently:

| Sub-Type | Definition | Trading Approach |
|----------|------------|-----------------|
| VOLATILE_UP | High VIX + bullish trend still intact (ADX > 20, DI+ > DI−) | Reduced size; buy on VIX spikes (dip into fear) |
| VOLATILE_DOWN | High VIX + bearish trend (ADX > 20, DI− > DI+) | Reduce size sharply; sell rallies; protective puts |
| VOLATILE_CHOP | High VIX + no clear trend (ADX < 20) | Pure HIGH_VOLATILITY regime; avoid directional bets |

**Supporting Conditions:**
- India VIX > 22: adds significantly to confidence
- ATR of the last 5 candles > 2× the ATR average of last 20 candles (intraday range is abnormal)
- IV Percentile > 65% in option chain (option market pricing elevated uncertainty)
- Intraday swings: price range of the session > 2× the average daily range
- VIX rate of change intraday > +10% in a single session (fear is accelerating)
- Advance-Decline ratio < 0.6 OR > 2.0 (extreme breadth — panic or euphoria)
- India VIX spike triggered: a single-day VIX move > 15%

### Typical HIGH_VOLATILITY Triggers in India

| Trigger | Typical VIX Impact | Duration |
|---------|--------------------|----------|
| RBI emergency rate decision | +15–25% VIX spike | 1–2 days |
| Global risk-off (US recession fear, war) | +20–40% VIX | 3–10 days |
| India election uncertainty | Sustained elevated VIX | Weeks |
| Budget disappointment | +10–20% VIX | 2–3 days |
| NBFC/banking crisis (domestic) | +15–30% VIX | Days to weeks |
| US Fed hawkish surprise | +10–15% VIX next day | 1–3 days |
| Pandemic/black swan | +50–100% VIX | Weeks |

### Confidence Calculation (0–100)

| Component | Measurement | Points |
|-----------|-------------|--------|
| India VIX | 20–22 | +15 |
| India VIX | 22–25 | +25 |
| India VIX | 25–28 | +35 |
| India VIX | > 28 | +45 |
| ATR Ratio | 1.2–1.5 | +10 |
| ATR Ratio | 1.5–2.0 | +18 |
| ATR Ratio | > 2.0 | +25 |
| IV Percentile | 65–75% | +10 |
| IV Percentile | 75–85% | +15 |
| IV Percentile | > 85% | +20 |
| VIX intraday spike | > 10% single-day | +8 |
| Intraday range | > 2× normal | +7 |
| A-D Ratio | < 0.6 or > 2.0 (extreme) | +5 |

**Maximum: 100**  
**Useful threshold: >= 50 to declare HIGH_VOLATILITY as active**  
**Emergency threshold: >= 80 → activate defensive protocols (position size halved)**

### Scoring Impact on Signal Engine

When HIGH_VOLATILITY is active at confidence >= 50:

| Strategy Component | Base Weight | Multiplier | Effective Weight | Reason |
|-------------------|-------------|-----------|-----------------|--------|
| OI Build-up | 25 | **0.80×** | 20 | OI shifts too rapidly to be reliable |
| Trend Following | 20 | **0.60×** | 12 | Trends interrupted frequently; ADX unreliable |
| Option Chain | 20 | **1.25×** | 25 | IV surface is the primary intelligence source |
| Volume Analysis | 15 | **1.00×** | 15 | Volume still useful for capitulation detection |
| VWAP | 10 | **0.70×** | 7 | VWAP deviations are extreme and not mean-reverting |
| Sentiment | 5 | **1.20×** | 6 | News sentiment more predictive during fear events |
| IV Analysis | 5 | **1.60×** | 8 | Most important signal in this regime |

**HIGH_VOLATILITY Risk Overrides:**
- Position size reduced to 50% of normal (Risk Engine enforcement)
- Minimum score to execute raised to **80** (higher bar for new positions)
- Stop-loss widened to 2.0× ATR (normal is 1.5× ATR)
- No new short-volatility (option selling) positions
- Existing short-volatility positions: flag for review

---

## Regime 5: LOW_VOLATILITY

**Definition:** A market in a compressed, quiet state — fear is absent, directional conviction is low, and prices move in small, predictable ranges. The classic "compressed spring" — often a precursor to a large move.

### Conditions

**Hard Gate:**
- India VIX < 14 AND ATR Ratio < 0.8 (both should be true for high confidence)

**Supporting Conditions:**
- India VIX < 13: significantly low fear — complacency is building
- Bollinger Band Width in the bottom 20th percentile of its 1-year range (extreme compression)
- ATR Ratio < 0.7: current intraday ranges are 30% below recent average
- Daily range of last 5 sessions < 0.6% of index level
- IV Percentile < 20% in option chain (options historically cheap)
- Volume declining or at multi-week low
- ADX < 20 (no trend — just drift)
- HV/IV Ratio < 0.8: realized vol is less than implied vol (option seller's market, but options are cheap too)

### LOW_VOLATILITY Alert — Breakout Implication

LOW_VOLATILITY regimes do not last indefinitely. They must be monitored for the "volatility expansion" signal that precedes a major move:

```
LOW_VOLATILITY → BREAKOUT_IMMINENT signal:
  Trigger conditions (any 2 of 3):
    - BB Width begins expanding after compression (first bar above 20th percentile after being below)
    - India VIX up-ticking 3+ consecutive days from the low
    - Volume expanding: last 3 bars each higher than previous
  
  When BREAKOUT_IMMINENT:
    - Flag to Breakout Strategy: increase breakout score weight
    - Increase position size to 120% of normal (for confirmed breakout)
    - Monitor closely for ADX to cross 20 (regime transition trigger)
```

### Confidence Calculation (0–100)

| Component | Measurement | Points |
|-----------|-------------|--------|
| India VIX | < 11 | +35 |
| India VIX | 11–12 | +28 |
| India VIX | 12–13 | +20 |
| India VIX | 13–14 | +10 |
| India VIX | >= 14 | +0 (cap at 35) |
| ATR Ratio | < 0.5 | +25 |
| ATR Ratio | 0.5–0.6 | +18 |
| ATR Ratio | 0.6–0.7 | +12 |
| ATR Ratio | 0.7–0.8 | +6 |
| BB Width Percentile | < 10th percentile | +20 |
| BB Width Percentile | 10–20th percentile | +14 |
| BB Width Percentile | 20–30th percentile | +8 |
| IV Percentile | < 15% | +10 |
| IV Percentile | 15–20% | +6 |
| Volume below 20d avg | Volume < 0.75× avg | +7 |
| Daily range | < 0.5% of index | +3 |

**Maximum: 100**  
**Useful threshold: >= 55 to declare LOW_VOLATILITY as active**

### Scoring Impact on Signal Engine

When LOW_VOLATILITY is active at confidence >= 55:

| Strategy Component | Base Weight | Multiplier | Effective Weight | Reason |
|-------------------|-------------|-----------|-----------------|--------|
| OI Build-up | 25 | **0.90×** | 22.5 | OI accumulation starts early in low-vol phase |
| Trend Following | 20 | **0.70×** | 14 | ADX likely low, trend signals weak |
| Option Chain | 20 | **1.10×** | 22 | OI wall analysis still valid; IV cheap → buy options |
| Volume Analysis | 15 | **0.90×** | 13.5 | Volume dry-up is expected — low vol = low volume |
| VWAP | 10 | **0.80×** | 8 | Deviations too small to be meaningful |
| Sentiment | 5 | **1.00×** | 5 | Normal weight |
| IV Analysis | 5 | **1.60×** | 8 | Buy vol signals are structurally best in low-vol |

**LOW_VOLATILITY Strategy Preference:**
- Long Straddle / Long Strangle: structurally advantaged (cheap options)
- Avoid short-volatility strategies (selling cheap options has no edge)
- Breakout strategies are primed: monitor for expansion signals

---

## Composite Regime Matrix

The following matrix shows how primary and secondary regimes interact and what the combined effect is on strategy weights:

| Primary Regime | Secondary Regime | Combined Behavior | Position Size |
|---------------|-----------------|-------------------|---------------|
| TRENDING_BULLISH | None | Amplify LONG signals, penalize SHORT | 100% |
| TRENDING_BULLISH | HIGH_VOLATILITY | Bullish but with wider stops; monitor for reversal | 70% |
| TRENDING_BULLISH | LOW_VOLATILITY | Slow melt-up; small positions but hold longer | 90% |
| TRENDING_BEARISH | None | Amplify SHORT signals, penalize LONG | 100% |
| TRENDING_BEARISH | HIGH_VOLATILITY | Most aggressive short opportunity; risk of violent rally | 70% |
| SIDEWAYS | None | Mean-reversion strategies only; range defined | 100% |
| SIDEWAYS | HIGH_VOLATILITY | Chop with fear; extremely dangerous — no new positions | 50% |
| SIDEWAYS | LOW_VOLATILITY | Classic coil; breakout position building is appropriate | 100% |
| HIGH_VOLATILITY | None | Fear-driven; defensive posture | 50% |
| LOW_VOLATILITY | None | Complacency; small positions, watch for expansion | 80% |

---

## Regime Transition Logic

### Transition Rules

A regime change must be CONFIRMED, not just triggered, to prevent constant switching (whipsawing). A regime must persist for a minimum number of bars before it can transition:

| Transition | Minimum Bars Required | Confirmation Needed |
|------------|----------------------|---------------------|
| SIDEWAYS → TRENDING | 3 consecutive 15-min bars with ADX > 22 | ADX > 25 + Supertrend aligned |
| TRENDING → SIDEWAYS | 5 consecutive 15-min bars with ADX < 20 | EMA entanglement confirmed |
| ANY → HIGH_VOLATILITY | 1 bar with VIX > 22 OR ATR Ratio > 2.0 (immediate) | No confirmation needed — safety first |
| HIGH_VOLATILITY → ANY | 3 consecutive days VIX < 20 AND ATR ratio < 1.2 | Requires both conditions simultaneously |
| TRENDING → opposite TRENDING | Must pass through SIDEWAYS | Cannot flip directly from BULL to BEAR |
| LOW_VOLATILITY → ANY | BB Width expansion + ADX crossing 20 | One of two conditions |
| ANY → LOW_VOLATILITY | 5 consecutive days VIX < 14 + ATR ratio < 0.8 | Both conditions required |

### Regime Change Event

When a regime transition is confirmed, the system publishes `features.regime.detected` to the Event Bus:

```
Regime Change Event payload:
  previous_regime: SIDEWAYS
  new_regime: TRENDING_BULLISH
  confidence: 72
  transition_bar_count: 3
  key_trigger: "ADX crossed 25 with DI+ > DI−"
  detected_at: timestamp
```

On receipt of this event:
- All open stale signals (generated under the old regime) are INVALIDATED (not filled)
- Strategy weight multipliers update immediately
- Kill Switch evaluates: is the new regime a risk event?
- Dashboard displays regime change notification

### Regime Stability Score

Beyond just reporting the current regime, the engine reports how STABLE the regime is:

```
Stability Score = (regime_duration_bars / required_minimum_bars) × (confidence / 100)

Interpretation:
  >= 0.8: Very stable — regime has been consistent for a long time with high confidence
  0.5–0.8: Stable — normal operating condition
  0.3–0.5: Moderately stable — monitor for transition
  < 0.3: Unstable — regime just started or confidence low; use baseline weights
```

When stability < 0.3: apply **no regime multipliers** (use baseline weights only). This prevents incorrect multipliers from being applied during uncertain periods.

---

## Multi-Timeframe Regime Alignment

The regime engine computes regimes on two timeframes simultaneously. These must be aligned for high-confidence signals.

### Daily Regime (Macro Bias)

- Computed from: 1-Hour and Daily candles
- Update frequency: Daily at 07:45 IST (post-instrument refresh) + after 15:30 IST close
- Purpose: Sets the macro directional bias for the entire session
- Instruments: Nifty 50 only (index-level macro view)

**Daily Regime provides:**
- Direction for the day (BULLISH / BEARISH / NEUTRAL)
- FII flow context (from previous day's EOD data)
- Whether we are in a multi-week trend or range

### Intraday Regime (Tactical)

- Computed from: 5-minute and 15-minute candles
- Update frequency: After every 15-minute candle close
- Purpose: Real-time regime for signal generation within the session
- Instruments: Nifty 50 + individual instrument (e.g., BANKNIFTY can have its own intraday regime)

### Alignment Logic

| Daily Regime | Intraday Regime | Combined Interpretation | Confidence Adjustment |
|-------------|----------------|------------------------|----------------------|
| TRENDING_BULLISH | TRENDING_BULLISH | Strong alignment — highest conviction | +10 to signal confidence |
| TRENDING_BULLISH | SIDEWAYS | Intraday consolidation within bull trend — normal | No adjustment |
| TRENDING_BULLISH | TRENDING_BEARISH | Counter-trend day — reduce confidence sharply | −15 to signal confidence |
| SIDEWAYS | SIDEWAYS | Confirmed range — best for mean-reversion | +5 to signal confidence |
| SIDEWAYS | TRENDING_BULLISH | Intraday breakout attempt — watch volume | No adjustment; apply breakout filter |
| HIGH_VOLATILITY | Any | High-vol overrides intraday for position sizing | Position size rules apply |
| TRENDING_BEARISH | TRENDING_BULLISH | Bear market rally — trade cautiously long | −10 to LONG confidence |

---

## India-Specific Regime Adjustments

### Pre-Market Regime Bias (08:00–09:14 IST)

Before the market opens, a preliminary regime bias is computed from available data:

| Input | Bullish Signal | Bearish Signal | Weight |
|-------|---------------|---------------|--------|
| SGX/Gift Nifty | > +0.5% premium | < −0.5% discount | 30% |
| US Futures direction | S&P500 futures up | S&P500 futures down | 25% |
| Crude oil | Falling (India imports) | Rising sharply | 15% |
| DXY (Dollar Index) | Weakening | Strengthening | 15% |
| Previous day India VIX close | < 16 | > 20 | 15% |

Pre-market bias is used only as a starting hint — it is overridden within 30 minutes of market open as real price data arrives.

### Scheduled Event Regime Overrides

These calendar events trigger mandatory regime adjustments:

| Event | Pre-Event (Day before) | Day of Event | Post-Event |
|-------|------------------------|--------------|------------|
| RBI Monetary Policy | Force SIDEWAYS confidence +20; disable trend signals | HIGH_VOLATILITY activated regardless of VIX | Normal regime resumes within 60 min of announcement |
| Union Budget | HIGH_VOLATILITY from previous close; all signals paused | HIGH_VOLATILITY; only trade post-announcement direction | Normal regime resumes within 90 min |
| FOMC Meeting (8:30 PM IST) | No special pre-market adjustment | VIX watch; if India VIX spikes next open: HIGH_VOL | Monitor for carry-through |
| State/National Elections | Sustained HIGH_VOLATILITY throughout election period | Same | Normal only after clear result |
| Quarterly Results (Nifty heavyweights) | No regime change | Monitor for gap + volatility | Normal |

### BANKNIFTY vs NIFTY Regime Divergence

BANKNIFTY can be in a different intraday regime from NIFTY. This divergence itself is a signal:

| Scenario | Interpretation | Strategy Adjustment |
|----------|---------------|---------------------|
| BANKNIFTY trending up, NIFTY sideways | Banking sector leadership — BANKNIFTY signals are higher confidence | Normal |
| BANKNIFTY trending down, NIFTY sideways | Banking stress — broad market likely to follow; reduce LONG confidence | −5 to NIFTY LONG confidence |
| BANKNIFTY high-vol, NIFTY normal-vol | Isolated banking event (NPA news, RBI action) | HIGH_VOL only for BANKNIFTY instruments |
| Both trending same direction | Full alignment — highest confidence setup | +5 to signal confidence |

---

## Regime Confidence → Weight Smoothing

A sudden regime change from SIDEWAYS to TRENDING_BULLISH should not instantly apply full multipliers. Weight transitions should be smooth:

**Smooth Transition Formula:**  
Effective multiplier = (previous multiplier × (1 − α)) + (new multiplier × α)  
Where α = min(1.0, stability_score × regime_confidence / 100)

This means:
- At first bar of new regime (stability = 0): effective multiplier = previous (no change yet)
- At 3 bars in with 70% confidence: α ≈ 0.40 (40% transition to new weights)
- At 10 bars in with 90% confidence: α ≈ 0.90 (nearly full transition)
- Full transition requires sustained regime + high confidence

---

## Complete Regime × Strategy Weight Matrix

The master reference for all strategy component effective weights under each regime:

| Strategy Component | Base | TREND_BULL | TREND_BEAR | SIDEWAYS | HIGH_VOL | LOW_VOL |
|-------------------|------|-----------|-----------|---------|---------|--------|
| OI Build-up | 25 | **30** (1.2×) | **30** (1.2×) | **25** (1.0×) | **20** (0.8×) | **22.5** (0.9×) |
| Trend Following | 20 | **26** (1.3×) | **26** (1.3×) | **5** (0.25×) | **12** (0.6×) | **14** (0.7×) |
| Option Chain | 20 | **20** (1.0×) | **22** (1.1×) | **28** (1.4×) | **25** (1.25×) | **22** (1.1×) |
| Volume Analysis | 15 | **16.5** (1.1×) | **16.5** (1.1×) | **15** (1.0×) | **15** (1.0×) | **13.5** (0.9×) |
| VWAP | 10 | **11** (1.1×) | **11** (1.1×) | **13** (1.3×) | **7** (0.7×) | **8** (0.8×) |
| Sentiment | 5 | **5** (1.0×) | **6** (1.2×) | **5** (1.0×) | **6** (1.2×) | **5** (1.0×) |
| IV Analysis | 5 | **3.5** (0.7×) | **5.5** (1.1×) | **7** (1.4×) | **8** (1.6×) | **8** (1.6×) |
| **Total (after normalize)** | **100** | **100** | **100** | **100** | **100** | **100** |

> Values shown before normalization (illustration of relative weighting).  
> Actual computation: each component's contribution = score × effective_weight; final score normalized to 0–100.

---

## Regime Confidence → Strategy Execution Gate

Regime confidence directly controls whether multipliers are applied at all:

| Regime Confidence | Action |
|------------------|--------|
| >= 80 | Apply full regime multipliers |
| 60–79 | Apply 75% of multipliers (blend toward baseline) |
| 45–59 | Apply 40% of multipliers |
| < 45 | Apply no multipliers — use baseline weights |

---

## Historical Validation Requirements

### Data Requirements

1. **Minimum backtest period:** 4 years of intraday 15-minute OHLCV for Nifty 50 + India VIX daily + NSE Advance-Decline daily
2. **Must include:** At least one of each: bull market phase, bear market phase, consolidation phase, extreme high-VIX event (COVID = March 2020), extreme low-VIX period
3. **Option chain history:** 2 years minimum (for IV Percentile calibration)

### Regime Classification Validation

1. **Regime labeling:** Manually label regimes on historical data for at least 200 trading days (ground truth)
2. **Classification accuracy:** The engine's regime output must match manual labels with >= 75% accuracy
3. **Transition accuracy:** Regime transitions detected within ±2 days of actual regime change (based on manual labeling)
4. **False positive rate:** HIGH_VOLATILITY regime should not be triggered on more than 5% of days where India VIX was < 18

### Regime-Conditional Strategy Performance

5. **Strategy P&L by regime:** Backtest each strategy component separately within each regime — confirm that applying regime multipliers improves Sharpe ratio vs flat weights by >= 10%
6. **Regime duration distribution:** Measure average duration of each regime in the backtest period — if any regime averages < 3 bars, the detection sensitivity needs to be reduced
7. **Transition false signals:** Measure how many times the engine oscillated between two regimes within a 3-bar window — target < 15% oscillation rate

### Calibration Tests

8. **ADX threshold test:** Backtest ADX gate values of 20, 22, 25, 28 for TRENDING vs SIDEWAYS boundary — find the ADX level that best separates profitable trend-following from unprofitable sideways trend-following
9. **VIX threshold test:** Backtest VIX boundaries of 18, 20, 22, 24 for HIGH_VOLATILITY gate
10. **Weight multiplier optimization:** For each regime, test multiplier ranges ±0.2 around the baseline values — confirm that the chosen multipliers produce the best out-of-sample Sharpe ratio
11. **Smoothing factor α:** Test α values of 0.2, 0.4, 0.6, 0.8 — find the smoothing that minimizes whipsaw while maintaining responsiveness

### Operational Validation

12. **Latency:** Regime re-evaluation after each 15-minute candle must complete within 500ms (regime is one of the first computations in the signal pipeline)
13. **Regime staleness:** If market data is unavailable for > 15 minutes during market hours, system must fall back to the last known regime with reduced confidence (− 20)
14. **Pre-market accuracy:** Validate pre-market bias model: measure how often the pre-market bias correctly predicted the first 60-minute direction of the session (target > 55%)

---

## Summary: Regime Engine in the Signal Pipeline

```
Market Data Tick
      ↓
[Feature Engineering] — computes ADX, EMA, ATR, BB Width, VWAP
      ↓
[India VIX Update] — every 60 seconds
      ↓
[Regime Engine] — runs after each 15-min candle close
      ↓
  Layer 1: Trend Layer (ADX + EMA + Supertrend + Breadth)
  Layer 2: Volatility Layer (VIX + ATR Ratio + BB Width + IV Percentile)
  Resolution: Primary regime, Secondary, Confidence, Stability
      ↓
[Event Bus] → features.regime.detected published
      ↓
[Strategy Scoring Engine] — applies regime multipliers to base weights
      ↓
[Signal Generation] — score computed with regime-adjusted weights
      ↓
[Risk Engine] — checks regime for position sizing rules
      ↓
[OMS] — executes approved signal
```

The regime engine is the **single most critical component** in the platform — it determines the rules of the game before any strategy is evaluated.

---

*Cross-references: Doc 16 (Signal Scoring Engine — weight system) · Doc 17 (Risk Engine — position sizing by regime) · Doc 19 (Strategy Framework — component definitions)*  
*No code in this document. Implementation in application/services/regime_engine.*
