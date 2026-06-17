# 19 — FnO Strategy Framework

**Platform:** NSE NFO · Indian FnO  
**Instruments:** NIFTY · BANKNIFTY · FINNIFTY · MIDCPNIFTY  
**Philosophy:** Multi-factor institutional scoring, not any single indicator  
**Version:** 1.0  

---

## Design Principles

This framework is built around one foundational truth about Indian FnO:

> **Price follows money. Money leaves fingerprints in Open Interest, Options chain flow, and Volume.**  
> RSI and MACD measure price. OI, Option Chain, and Volume measure conviction.  
> Measure conviction first. Use price as confirmation.

### What This Framework Is NOT

| Avoid | Why |
|-------|-----|
| Pure RSI strategy | RSI is a symptom, not a cause. High RSI in an up-trend is normal, not overbought |
| Pure MACD strategy | MACD is a lagging average of averages — enters too late in fast FnO moves |
| Candlestick-only | Single patterns without volume/OI context have < 52% win rate in live Indian FnO |
| AI-generated trades | AI provides context, never the decision. Forbidden from trade execution by architecture design |
| Breakout without volume | 60–70% of breakouts in NIFTY/BANKNIFTY are false. Volume is the gate |

### NSE FnO Context

Every strategy in this document is calibrated for:
- **Trading window:** 09:15–15:30 IST (avoid first 15 min for entry, avoid last 5 min for new positions)
- **Liquidity peaks:** 09:15–10:30 IST and 14:00–15:30 IST
- **Expiry cadence:** NIFTY=Thursday, BANKNIFTY=Wednesday, FINNIFTY=Tuesday, MIDCPNIFTY=Monday
- **OI data delay:** 3–5 minutes from NSE feed (factor into signal latency)
- **Lot sizes:** NIFTY 50 · BANKNIFTY 15 · FINNIFTY 40 · MIDCPNIFTY 75
- **India VIX:** The primary fear/greed gauge — drives all IV-related strategy weights

---

## Master Scoring Matrix

All strategies contribute to a composite signal score (0–100):

| Strategy Component | Max Score | Role | Category |
|--------------------|-----------|------|----------|
| OI Build-up Analysis | **25** | Primary conviction signal | Core |
| Trend Following | **20** | Directional bias filter | Core |
| Option Chain Analysis | **20** | Smart money positioning | Core |
| Volume Analysis | **15** | Conviction confirmation | Core |
| VWAP Analysis | **10** | Intraday institutional anchor | Core |
| Sentiment (News/FII) | **5** | Macro alignment | Supporting |
| IV Analysis | **5** | Volatility regime filter | Supporting |
| **Total** | **100** | | |

### Signal Thresholds

| Score Range | Signal | Action |
|-------------|--------|--------|
| 85–100 | **STRONG BUY / STRONG SELL** | Full position size per risk rules |
| 70–84 | **BUY / SELL** | Standard position size |
| 50–69 | **NEUTRAL** | No new positions |
| 35–49 | **WEAK SELL / WEAK BUY** | Consider existing position reduction |
| Below 35 | **STRONG SELL / STRONG BUY** | Full exit of existing positions |

> **Minimum confidence to execute:** 65% (enforced by Risk Engine — see Doc 17)  
> **Direction:** LONG score + SHORT score are computed independently. Use whichever is higher.  
> A score of 72 LONG + 68 SHORT = LONG signal. Neither overrides risk engine checks.

---

## Market Regime Classification (Pre-Condition Gate)

**Market Regime is computed BEFORE any strategy score.** Each strategy applies regime-specific weight multipliers. Without regime classification, strategy weights are meaningless.

### Regime Definitions

| Regime | ADX | EMA Structure | India VIX | Strategy Weights |
|--------|-----|---------------|-----------|-----------------|
| TRENDING\_BULLISH | > 25 | EMA20 > EMA50 > EMA200 | < 18 | Trend↑ VWAP-Trend↑ OI↑ |
| TRENDING\_BEARISH | > 25 | EMA20 < EMA50 < EMA200 | 15–25 | Trend↑ OI↑ IV slightly↑ |
| SIDEWAYS | < 20 | EMAs entangled | < 16 | VWAP-Reversion↑ IV-Sell↑ OI(PCR) |
| HIGH\_VOLATILITY | Any | Any | > 22 | IV↑ OI caution Breakout↓ |
| LOW\_VOLATILITY | < 20 | Any | < 13 | Breakout↑ IV-Buy↑ Momentum neutral |

### Regime Weight Multipliers

When the Scoring Engine applies weights, it multiplies the base weight by a regime factor:

```
TRENDING_BULLISH:
  OI Build-up:     1.2×  (long build-up extremely reliable in trends)
  Trend:           1.3×  (primary signal)
  Option Chain:    1.0×
  Volume:          1.1×
  VWAP (trend):    1.1×
  IV:              0.7×  (IV less relevant in directional trends)

SIDEWAYS:
  OI Build-up:     1.0×  (PCR and max pain most useful)
  Trend:           0.3×  (trend signals unreliable — ADX gate enforces near-zero)
  Option Chain:    1.4×  (option chain is primary in rangebound)
  Volume:          1.0×
  VWAP (reversion):1.3×
  IV:              1.4×  (short vol strategies effective)

HIGH_VOLATILITY:
  OI Build-up:     0.8×  (OI shifts too fast to rely on)
  Trend:           0.7×
  Option Chain:    1.2×
  Volume:          1.0×
  VWAP:            0.8×  (VWAP deviations extreme)
  IV:              1.6×  (dominant signal)
```

---

## Strategy 1: OI Build-up Analysis

**Role in Scoring:** Core · Maximum 25 points  
**Data Source:** NSE FO OI feed (3–5 min delay) · Kite tick stream  
**India-Specific:** Most powerful signal for Indian FnO — tracks institutional conviction

### Why OI Build-up is Primary in India

Unlike equity markets where price discovery is primary, Indian FnO is dominated by:
- FII (Foreign Institutional Investors) — largest futures participants
- Domestic Prop Desks — use futures for directional plays
- Retail option buyers — create OI imbalances that smart money exploits
- PCR (Put-Call Ratio) is watched by every institutional desk

OI does not lie. Prices can be manipulated short-term; OI requires actual capital commitment.

### Inputs

**Futures OI:**
- Current futures OI vs previous close OI (absolute and % change)
- OI change in last 30 minutes (intraday OI momentum)
- Futures basis (spot–futures spread): expanding premium = bullish accumulation
- Rollover data during expiry week (near vs next month OI)

**Options OI:**
- CE and PE OI at ATM strike, ATM±1, ATM±2, ATM±5
- Change in CE OI vs PE OI over last 60 minutes
- PCR (Put-Call Ratio) at index level: total PE OI / total CE OI
- PCR change direction: rising PCR = bullish, falling PCR = bearish
- Highest OI strikes across all expiries (natural support/resistance walls)
- Max Pain level: weighted average of OI × (strike distance from current price)

**FII/DII Data (EOD, used as next-day bias):**
- FII Net Futures position (COT-equivalent from NSE daily bulletin)
- FII index options position (net delta approximation)
- Change in FII net long/short position vs previous 5-day average

### The Four OI Interpretations (Mandatory Classification)

Every futures OI signal must be classified into one of four quadrants:

| Quadrant | Price | OI | Interpretation | Signal Strength |
|----------|-------|-----|----------------|-----------------|
| **Long Build-up** | UP | UP | Fresh longs entering — most bullish | ★★★★★ |
| **Short Covering** | UP | DOWN | Shorts exiting — bullish but temporary | ★★★ |
| **Short Build-up** | DOWN | UP | Fresh shorts entering — most bearish | ★★★★★ |
| **Long Unwinding** | DOWN | DOWN | Longs exiting — bearish but decelerating | ★★★ |

Long Build-up and Short Build-up generate the highest-confidence signals. Short Covering and Long Unwinding generate lower-confidence signals (fade with caution after the covering is exhausted).

### Conditions

**LONG Signal (OI confirms bullish):**
1. Futures: Long Build-up detected — OI change >= +3% in rolling 30-minute window AND price up >= 0.3%
2. PCR (Index): > 0.8 and rising OR sustained above 1.0 (puts being sold = floor established)
3. CE OI at current ATM+2% strike: NOT aggressively increasing (no heavy writing against the move)
4. PE OI at current ATM: stable or increasing (put sellers confident = support floor)
5. Max Pain: current price not more than 2×ATR above max pain level (not dangerously extended)
6. FII net: not more than −5,000 contracts net short (not extreme bearish institutional position)
7. Highest PE OI strike is below current price by >= 0.5% (acts as support floor)

**SHORT Signal (OI confirms bearish):**  
Mirror of above with Short Build-up, PCR falling, CE OI increasing defensively, PE OI wall above.

**EXPIRY WEEK EXCEPTION (DTE 0–2):**
- Max Pain becomes the dominant sub-input (weight 60% of OI score)
- Futures OI signal weight reduces (rollover noise dominates)
- PCR signal becomes unreliable (positional unwinding creates false readings)
- Reduce OI score maximum to 15 points when DTE <= 2

### Strength Score Breakdown (0–25 points)

| Scenario | Points |
|----------|--------|
| Long/Short Build-up confirmed + PCR aligned + OI wall below/above + FII neutral/aligned | 22–25 |
| Long/Short Build-up confirmed + PCR aligned (no FII data yet) | 17–21 |
| Short Covering/Long Unwinding with PCR aligned | 12–16 |
| Only one of: OI build-up OR PCR signal (not both) | 7–11 |
| OI flat, PCR neutral (50/50) | 3–6 |
| No OI data available (stale > 5 min) | 0 (INSUFFICIENT_DATA) |

### Weaknesses

- OI data has a 3–5 minute publication delay from NSE — signal is inherently lagging
- During major news events (RBI policy, Budget), OI shifts are noise-driven (panic/euphoria)
- Short covering moves are violent, fast, and exhausted within 1–3 candles — hard to ride
- Max Pain is a theoretical model; in strong trends, markets ignore it until very close to expiry
- FII data is published EOD — cannot use for intraday signal; only as overnight bias
- PCR interpretation is context-dependent: PCR of 1.5 is bullish in a rising market but signals panic top in a falling market
- Rollover week (last 3 days of expiry): OI signals are heavily distorted

### Ideal Market Regime

| Regime | OI Signal Quality | Notes |
|--------|-------------------|-------|
| TRENDING_BULLISH / BEARISH | Excellent | Long/Short Build-up most reliable |
| SIDEWAYS | Good | PCR and Max Pain more important than futures OI |
| HIGH_VOLATILITY | Fair | OI shifts too rapidly; reduce confidence |
| LOW_VOLATILITY | Good | Accumulation visible early |

### Historical Validation Requirements

1. **Minimum data:** 6 months of intraday OI data (at 5-minute intervals) — minimum 500 OI observations per instrument
2. **Signal classification accuracy:** Correctly classify Long Build-up vs Short Covering in at least 85% of cases using automated rules before backtesting
3. **Instrument separation:** NIFTY and BANKNIFTY must be backtested independently — OI dynamics differ significantly (BANKNIFTY has far fewer participants, OI shifts faster)
4. **Expiry-week separate backtesting:** DTE 7+ vs DTE 3–6 vs DTE 0–2 must have separate win rate and P&L statistics
5. **PCR threshold tuning:** Test PCR thresholds of 0.7, 0.8, 0.9, 1.0, 1.2 — find the threshold that gives > 55% directional accuracy for each instrument
6. **Max Pain validation:** Validate Max Pain accuracy on expiry day close: measure average distance between final closing price and Max Pain level across 100+ expiry days
7. **FII signal lag test:** Test FII net position as a 1-day forward-looking indicator; measure information coefficient (IC) against next-day futures returns
8. **Required performance:** Long Build-up signal win rate > 55% · Profit factor > 1.4 · Max 6 consecutive losses per signal type

---

## Strategy 2: Trend Following

**Role in Scoring:** Core · Maximum 20 points  
**Regime Gate:** ADX < 20 → weight = 0 (trend signals are meaningless in choppy markets)  
**India-Specific:** Must account for gap openings at 9:15 AM which can invalidate overnight trends instantly

### Why Trend is Core (Not Supporting)

Indian institutional participants — mutual funds, insurance companies, FIIs — take large directional positions that sustain trends for days to weeks. Individual intraday trends in NIFTY/BANKNIFTY can be 150–500 points in a single session. Capturing 30–40% of a sustained trend with proper entries gives exceptional R:R.

The danger: BANKNIFTY can make a 300-point move and a 300-point reversal in the same day. **ADX is the mandatory gate.**

### Inputs

**Primary Trend Indicators:**
- EMA(20), EMA(50), EMA(200) on multiple timeframes (15m for intraday, daily for bias)
- Supertrend(10, 3) — ATR-based trend direction, most responsive indicator for FnO intraday
- ADX(14) with DI+, DI- — MANDATORY gate: if ADX < 20, no trend signal generated
- Higher Highs / Higher Lows structure on 15-minute chart (structural trend confirmation)

**Trend Strength Indicators:**
- EMA slope: rate of change of EMA(20) over 5 bars
- Price distance from EMA(200): normalized by ATR — extreme distance = reversion risk
- Futures basis behavior: premium expanding = institutional accumulation, contraction = distribution
- Relative strength vs Nifty 50: if stock/BANKNIFTY leading Nifty, trend is sector-specific and stronger

**Multi-Timeframe Framework (MTF):**

| Timeframe | EMA Used | Role |
|-----------|----------|------|
| Daily | EMA 200 | Macro trend bias (institutional bias) |
| 1-Hour | EMA 50 | Primary trend (swing direction) |
| 15-Minute | EMA 20 | Tactical trend (entry timing) |
| 5-Minute | EMA 9 | Micro entry signal |

**Trend signal requires alignment on at least 2 of the 3 upper timeframes.**

**Indian Market-Specific Inputs:**
- Pre-market SGX Nifty / Gift Nifty trend: confirms or denies overnight direction
- Nifty Advance-Decline ratio: > 1.3 for up days, < 0.7 for down days (breadth confirmation)
- India VIX trend: rising VIX in an up-trend = warning; falling VIX in up-trend = healthy

### Conditions

**BULLISH TREND Signal:**
1. ADX(14) >= 25 on primary timeframe (15m or 1h) — HARD GATE
2. DI+ > DI- by >= 5 points (directional conviction, not just trend)
3. Price > EMA(20) > EMA(50) on entry timeframe (full EMA alignment)
4. Supertrend indicator: Green (bullish) on 15m timeframe
5. No major resistance within 0.5×ATR above current price (room to move)
6. Nifty 50 also in uptrend OR instrument is relative strength leader (not laggard)
7. Entry candle: price has pulled back to EMA(20) and is bouncing (not chasing a parabolic move)
8. Futures basis: premium stable or expanding (not contracting while price rises)

**BEARISH TREND Signal (mirror of above with reverse conditions)**

**Trend Signal Invalidation (immediate exit / weight = 0):**
- ADX drops below 20 (trend has ended, choppy now)
- Price closes below EMA(50) on 15m for 2 consecutive candles
- Supertrend flips to bearish in a bullish trend
- India VIX spikes > 10% intraday (panic event, trend signal unreliable)

**Gap Opening Protocol (09:15–09:30 rule):**
- Gap up > 0.5% AND price remains above previous day's high after 15 minutes → trend signal eligible
- Gap down > 0.5% AND price remains below previous day's low after 15 minutes → bearish trend signal eligible
- Gap fill scenario (price reverses gap direction within 30 min) → NO trend signal; wait for new direction

### Strength Score Breakdown (0–20 points)

| Scenario | Points |
|----------|--------|
| ADX > 30 + all EMAs aligned + Supertrend + MTF alignment (3 TFs) + Nifty breadth confirming | 18–20 |
| ADX 25–30 + all EMAs aligned + Supertrend + 2 TFs aligned | 13–17 |
| ADX 20–25 + primary EMAs aligned + Supertrend but MTF mixed | 8–12 |
| ADX > 20 but EMAs misaligned or Supertrend opposite | 3–7 |
| ADX < 20 (choppy) | 0 (regime gate: no signal generated) |
| Counter-trend (price against EMA alignment) | 0–4 |

### Weaknesses

- Gap openings at 9:15 AM frequently invalidate overnight trends — no position should be carried overnight based on trend alone
- BANKNIFTY trends can reverse 300+ points in 15 minutes on macro news — trend signals become useless
- EMAs are lagging by definition — in fast FnO moves, the signal comes when 30–40% of the move is already done
- Near expiry (DTE 0–3), option premium decay dominates; trend-following directional plays get destroyed by theta even when direction is correct
- Global factors (US Fed, global risk-off events) override domestic technical trends instantly
- Low-ADX markets generate false trend signals — the ADX gate is the ONLY reliable filter

### Ideal Market Regime

| Regime | Trend Signal Quality |
|--------|---------------------|
| TRENDING_BULLISH / BEARISH | Excellent — primary signal |
| SIDEWAYS | Disabled (ADX gate enforces 0 weight) |
| HIGH_VOLATILITY | Fair — trends exist but violently interrupted |
| LOW_VOLATILITY | Poor — low ADX, no trend, signal not generated |

### Historical Validation Requirements

1. **Walk-forward:** 3-month in-sample, 1-month out-of-sample · Minimum 6 cycles
2. **ADX threshold sensitivity:** Backtest separately with ADX gates at 20, 22, 25, 28, 30 — find optimal gate per instrument
3. **Gap scenario isolation:** Separately track performance on: gap-up days, gap-down days, flat opens — trend strategy may work only on flat opens
4. **Expiry week exclusion:** Track P&L of trend signals when DTE <= 3 — if negative, disable trend signals in expiry week
5. **MTF alignment test:** Measure win rate improvement from requiring 2-TF vs 3-TF alignment
6. **EMA selection test:** Backtest EMA(9,20,50), EMA(20,50,200), EMA(13,34,89) — use instrument-specific optimal set
7. **Minimum performance:** Win rate > 50% (lower is acceptable with proper R:R), Profit factor > 1.5, Sharpe > 0.8 in trending regimes
8. **Maximum adverse excursion (MAE):** Establish expected MAE per signal for stop-loss calibration

---

## Strategy 3: Option Chain Analysis

**Role in Scoring:** Core · Maximum 20 points  
**Data Source:** Option chain (hybrid: Kite WebSocket per-strike + NSE REST full chain every 60s)  
**India-Specific:** India VIX, IV Skew, Gamma Exposure — most underused signals by retail traders

### Why Option Chain is Core

Every large participant who manages risk hedges in options. The option chain is the aggregate book of every hedging and speculative position. It reveals:
- Where institutional money has placed large bets (highest OI strikes = walls)
- Whether the smart money expects a big move (IV expansion/contraction)
- Directional bias of option buyers vs sellers (IV Skew)
- Where dealer hedging creates mechanical support/resistance (Gamma Exposure zones)

### Inputs

**IV (Implied Volatility) Surface:**
- ATM IV: current IV at the at-the-money strike
- IV Percentile: (days in past year where IV was lower / 252) × 100 — where are we in the annual IV range?
- IV Rank: (current IV − 52W Low) / (52W High − 52W Low) × 100
- IV Skew: (OTM25 Put IV − OTM25 Call IV) — positive skew = put protection demand (bearish fear)
- IV term structure: front-month ATM IV vs next-month ATM IV ratio (contango or backwardation)
- IV change in last 30 minutes: expansion or contraction direction
- IV Premium over Realized Volatility: (30d IV − 30d RV) — positive = options expensive

**Option Chain Structure:**
- Highest CE OI strike across all expiries: natural resistance wall
- Highest PE OI strike across all expiries: natural support wall
- Strike-specific OI changes: writing activity vs fresh buying at each strike
- Put-Call OI ratio at ATM±5 strikes: local directional bias
- Bid-ask spread at target strike: liquidity check (reject if spread > 1% of premium)
- Change in OI at ATM ± 2 strikes in last 30 minutes: fresh positioning

**Gamma Exposure (GEX) — Advanced:**
- Net dealer gamma at each strike: dealers are short gamma (they must delta-hedge)
- When price approaches a high positive GEX strike, dealers buy (supports price)
- When price moves away from high GEX zone, dealers sell (accelerates move)
- Gamma flip level: the strike where dealer gamma switches sign — magnetic price level

**India VIX:**
- Current India VIX level
- India VIX 10-day SMA: trend of fear
- India VIX percentile (historical context)
- India VIX rate of change intraday: sudden > 10% spike = risk-off, reduce all option-buying signals

### Conditions

**BULLISH Option Chain Signal:**
1. Highest PE OI strike is below current price, providing a visible support floor
2. Highest CE OI strike is above current price by >= 1% (room to move up before hitting wall)
3. IV Skew: negative or neutral (demand for calls not being overwhelmed by put protection)
4. IV Percentile: below 50% (options not extremely expensive — buying strategy is viable)
5. ATM IV stable or declining in last 30 min (no panic premium being priced in)
6. CE OI at ATM: stable or reducing (call writers not aggressively shorting the upside)
7. India VIX: below 20 and not in uptrend
8. Bid-ask spread at target strike: <= 0.5% of premium (adequate liquidity)

**BEARISH Option Chain Signal (mirror)**

**SELL VOLATILITY Signal (for Iron Condor / Short Strangle):**
1. IV Percentile > 70% (top 30% of annual IV range) — options are expensive
2. No major event within 7 trading days (RBI, Budget, FOMC, elections, quarterly results)
3. IV Premium (IV − 30d RV) > 5% (statistical edge for option seller)
4. Sideways regime confirmed (ADX < 20, range-bound)
5. Days to expiry: 7–14 days (ideal Theta/Gamma ratio for short vol)

**BUY VOLATILITY Signal (for Long Straddle):**
1. IV Percentile < 20% (bottom quintile — options are historically cheap)
2. Identified catalyst within 3–5 days (event-driven expansion)
3. IV Skew compressed (unusually flat — complacency signal)
4. India VIX at multi-month low

### Strength Score Breakdown (0–20 points)

| Scenario | Points |
|----------|--------|
| IV setup aligned (percentile correct for strategy) + OI walls confirm + IV Skew aligned + GEX supportive | 18–20 |
| IV setup + OI walls confirmed (no GEX data) | 13–17 |
| OI walls confirmed but IV is neutral (no clear vol regime) | 8–12 |
| IV signal present but OI walls contradicting | 5–8 |
| IV extreme but major event risk exists | 3–6 |
| Option chain data stale > 90 seconds | 0 (INSUFFICIENT_DATA) |

### IV Regime Decision Matrix

| IV Percentile | No Event in 7d | Event in 3d | Preferred Strategy |
|---------------|---------------|-------------|-------------------|
| < 20% | Neutral | Buy Vol (Straddle) | Long options |
| 20–50% | Normal directional | Avoid event play | Directional options |
| 50–70% | Normal directional | Neutral/avoid | Directional options |
| > 70% | Sell Vol | Do NOT sell before event | Short options (no event) |
| > 85% | Strong sell vol | Do NOT trade new positions | Cash / small hedge only |

### Weaknesses

- IV crush post-event: buying options before events and holding through them results in losses even if direction is correct
- Option chain data refreshes every 60 seconds (REST) — data is always slightly stale
- Gamma risk near expiry: a small adverse price move creates massive losses in short-option positions
- India VIX measures 30-day expected volatility — does not predict intraday volatility spikes
- Max OI strikes can shift intraday as writers roll positions — a "wall" can disappear
- GEX calculations require bid-ask mid prices and accurate delta values — estimation errors compound
- Liquidity: strikes beyond ATM±5 have wide spreads in Indian FnO — signal valid only for liquid strikes

### Ideal Market Regime

| Regime | Option Chain Application |
|--------|-------------------------|
| TRENDING | OI walls as momentum targets; avoid selling options |
| SIDEWAYS | Sell Vol strategies; range defined by OI walls |
| HIGH_VOLATILITY | IV signals dominant; directional option signals unreliable |
| LOW_VOLATILITY | OI walls as breakout triggers; Buy Vol if event approaching |

### Historical Validation Requirements

1. **IV data span:** Minimum 2 years — must include both low-IV (2020 post-crash recovery) and high-IV (election volatility, COVID spike) periods
2. **IV Percentile calibration:** Compute on rolling 252-day window, not static historical period
3. **OI wall effectiveness:** Backtest: when price approaches the highest OI CE strike, what % of times does it reverse? Target >= 60% reversal rate for "wall" to be considered significant
4. **Event IV behavior:** Separate backtest for: day of event, day before event, day after event — IV behavior is fundamentally different on these days
5. **Expiry-week IV:** IV behavior changes dramatically in last 3 DTE — separate model required
6. **Instrument-specific IV:** NIFTY and BANKNIFTY have different IV levels (BANKNIFTY typically 5–10 pts higher IV) — no cross-instrument IV comparison
7. **Skew model validation:** Measure IV Skew prediction of next-day direction — IC (information coefficient) target > 0.05 for inclusion
8. **Short vol strategy requirements:** Expected value positive over 100+ trades · Maximum margin breach scenario tested · No short-vol positions held over news events

---

## Strategy 4: Volume Analysis

**Role in Scoring:** Core · Maximum 15 points  
**Philosophy:** Volume is the engine that powers price movement. Price without volume is noise.

### Why Volume is Core in Indian FnO

Indian FnO markets are deeply affected by institutional block trades, large lot purchases, and algorithmic execution. Volume spikes:
- Confirm breakouts vs false breakouts
- Confirm trend strength vs exhaustion
- Identify distribution tops and accumulation bottoms
- Provide early warning of institutional activity before it's visible in price

### Inputs

**Volume Metrics:**
- Current volume vs 20-period average volume (volume ratio)
- Volume profile: intraday VPOC (Volume Point of Control — price with highest volume)
- Volume at bid vs volume at ask (tape reading approximation)
- Large lot detection: orders > 200 lots in a single candle
- Cumulative Delta: running sum of (buy volume − sell volume) per bar
- OBV (On-Balance Volume): cumulative directional volume trend
- Volume dry-up before breakout: 3+ bars with volume < 0.5× average (coiling)

**Futures-Specific Volume:**
- Futures volume vs spot volume ratio: high futures/spot = institutional activity
- Volume spike timing: opening volume (09:15–09:30), lunch spike, expiry-day volume surge

**India-Specific:**
- FII vs DII net buy/sell volumes (EOD from NSE — used as next-day bias)
- Block deal activity in underlying stocks
- Nifty breadth: total NSE volume trending (not just single instrument)

### Conditions

**Volume CONFIRMS a directional signal:**
1. Breakout candle volume >= 2.0× the 20-period average (primary confirmation)
2. Volume trend: last 3 candles have increasing volume with the move (accumulation)
3. OBV slope: positive in last 5 bars for LONG, negative for SHORT
4. Cumulative Delta: positive (more buy volume than sell volume) for LONG
5. Volume-weighted price action: VWAP is rising with price (not diverging)
6. No volume divergence: price making new highs on declining volume = bearish divergence (warning, reduce score)

**Volume REJECTS a signal (score reduction):**
- Breakout on below-average volume: −5 points
- Price divergence with OBV: −3 points (price up, OBV flat or down = distribution)
- Volume spike on bearish candle in bullish trend: −2 points (selling pressure)

**Volume DRY-UP (pre-breakout setup):**
- 3+ consecutive candles with volume < 0.5× average: coiling, explosive move imminent
- Combined with tight price range (< 0.2× ATR): breakout setup
- Volume dry-up itself scores 5 points on the Volume sub-score as a setup indicator

### Strength Score Breakdown (0–15 points)

| Scenario | Points |
|----------|--------|
| Volume >= 2× average + OBV aligned + Cumulative Delta confirms + no divergence | 13–15 |
| Volume 1.5–2× average + OBV aligned + no divergence | 9–12 |
| Volume 1.2–1.5× average OR only OBV confirmation | 5–8 |
| Volume average (no spike) but OBV trending | 3–4 |
| Volume divergence (price up, OBV down) | −5 (penalty, reduces other scores) |
| Volume data stale or unavailable | 0 |

### Weaknesses

- Volume data from Kite WebSocket has minor delays and occasional gaps
- BANKNIFTY has disproportionately high volume in the first 15 minutes — this inflates averages and makes later-day signals look low-volume even when they're actually significant
- Algo trading creates synthetic volume spikes that do not represent real conviction
- Lunch-hour (12:30–14:00) volume is structurally low — volume signals are less reliable in this window
- Expiry day volume is structurally extreme — all volume metrics require recalibration
- OBV can diverge during corporate actions (dividend, bonus) — requires clean adjusted data

### Ideal Market Regime

Volume analysis is useful in ALL regimes but interpretation changes:
- **Trending:** Volume expansion confirms trend continuation; volume dry-up warns of trend exhaustion
- **Sideways:** Volume spike at range boundaries confirms support/resistance holds or breaks
- **High-Volatility:** Volume spikes are massive and frequent — require higher threshold (3× average instead of 2×)

### Historical Validation Requirements

1. **Volume threshold sensitivity:** Test 1.5×, 2×, 2.5×, 3× average thresholds — find the threshold where false signals < 40%
2. **OBV information coefficient:** Measure OBV slope vs next-candle return correlation — IC target > 0.04
3. **Volume divergence effectiveness:** When volume divergence is detected, measure reversal probability within 5 bars — target > 60% for divergence signal to be included
4. **Time-of-day adjustment:** Build separate volume averages for: 09:15–10:00, 10:00–12:00, 12:00–14:00, 14:00–15:30 — avoid comparing opening volume to afternoon average
5. **Expiry day exclusion study:** Volume signals on expiry day vs non-expiry — if win rate < 50% on expiry, exclude volume signals on expiry day

---

## Strategy 5: VWAP Analysis

**Role in Scoring:** Core · Maximum 10 points  
**Context:** Intraday only · Session VWAP resets at 09:15 IST every day  
**Dual Use:** Mean-reversion (sideways regime) AND trend confirmation (trending regime)

### Why VWAP is Core

VWAP is the single most important intraday level for institutional execution:
- Mutual funds benchmark against VWAP for order quality
- Algo traders use VWAP crossing as trend signal
- Market makers maintain inventory around VWAP
- Price repeatedly gravitates toward VWAP within a session — it is the fairest price

### Inputs

**VWAP Structure:**
- VWAP: running session VWAP (cumulative sum of volume×price / cumulative volume from 09:15)
- VWAP ±1σ band: volume-weighted standard deviation band
- VWAP ±2σ band: extreme deviation bands
- VWAP slope: rate of change over last 30 minutes (positive = institutional buying, negative = selling)
- Previous Day VWAP (DVWAP): used as weekly support/resistance reference
- VWAP touch count: how many times price has tested VWAP today (decreasing bounce probability)

**Volume Profile:**
- VPOC (Volume Point of Control): price level with highest volume today
- Value Area High (VAH): 70% of volume above this
- Value Area Low (VAL): 70% of volume below this
- Price acceptance vs rejection at VWAP: does price close above VWAP or immediately reject?

**Time Context:**
- First 30 minutes VWAP is not statistically meaningful (insufficient volume for anchoring)
- Optimal VWAP trading window: 10:00–14:30 IST
- Avoid VWAP trades in last 15 minutes (close-related distortions)

### Two VWAP Modes

**MODE A — VWAP Mean-Reversion (SIDEWAYS regime)**

Conditions for LONG:
1. Price has touched −1σ VWAP band (or lower) — enters value zone
2. Price has NOT breached −2σ (if breached, trend may have broken, mean-rev fails)
3. Volume spike at the VWAP test: >= 2.5× average on the touch candle (institutional buying at value)
4. RSI(5) on 5-minute chart: <= 30 (micro-oversold confirmation)
5. VWAP slope: not aggressively negative (if VWAP is steeply declining, avoid long)
6. Time filter: signal only between 10:00 and 14:30 IST
7. VWAP touch count for the day: <= 3 (after 4+ touches, VWAP support is weakening)
8. Target: VWAP itself · Stop: at −2σ band · R:R must be >= 1.5

**MODE B — VWAP Trend Confirmation (TRENDING regime)**

Conditions for LONG:
1. Price is firmly above VWAP for >= 3 consecutive 5-minute candles
2. On pullback to VWAP, price bounces with a bullish candle (hammer, engulfing) with volume > average
3. VWAP slope: positive and stable
4. Previous day VWAP is below today's VWAP (trend continuation bias)
5. Target: distance proportional to ATR · Stop: below VWAP by 0.3×ATR

### Strength Score Breakdown (0–10 points)

| Scenario | Points |
|----------|--------|
| Mode A: Price at −1σ + volume spike + RSI oversold + time window valid + touch count <= 2 | 9–10 |
| Mode A: Price at −1σ + volume spike (RSI borderline) | 7–8 |
| Mode B: Clean VWAP retest with bouncing volume + VWAP slope positive | 7–9 |
| Mode B: Price above VWAP but no clear retest (price just hovering above) | 4–6 |
| Price straddling VWAP (crossing repeatedly) | 1–3 |
| First 30 minutes (VWAP not established) | 0 |
| VWAP touch count >= 5 for the day | 0–2 (VWAP support is broken) |

### Weaknesses

- VWAP resets daily — no memory of multi-day trends
- Not applicable to positional or swing trades (only intraday)
- In strong trending days, VWAP is rarely reached — Mode A produces zero signals
- BANKNIFTY can deviate 3–4σ from VWAP on high-news days — extreme deviations are not mean-reverting, they are trend continuation
- High VWAP touch count within a session signals weakness — the 5th touch of a VWAP level rarely holds
- VWAP is a well-known level — smart money front-runs it, making exact VWAP touch entries riskier

### Ideal Market Regime

| Regime | VWAP Mode | Notes |
|--------|-----------|-------|
| SIDEWAYS | Mode A (mean-reversion) | Best environment |
| HIGH_VOLATILITY | Mode A with higher threshold (3σ) | Deviations are larger |
| TRENDING_BULLISH | Mode B (trend confirmation) | Only long trades |
| TRENDING_BEARISH | Mode B (trend confirmation) | Only short trades |
| LOW_VOLATILITY | Mode A (weak signals) | Deviations too small, R:R poor |

### Historical Validation Requirements

1. **Time-of-day segmentation:** Separate win rates for: pre-10:00, 10:00–12:00, 12:00–14:00, 14:00–15:15 — strategy likely performs best in 10:00–14:00 window
2. **σ band calibration:** Test entry at −0.5σ, −1σ, −1.5σ, −2σ — find the band with best R:R combination (not just win rate)
3. **Volume spike threshold:** Test 2×, 2.5×, 3× average volume at VWAP touch — find the threshold that eliminates > 50% of false signals
4. **Touch count degradation:** Measure win rate for 1st, 2nd, 3rd, 4th touch of VWAP — quantify at which touch count the signal becomes statistically insignificant
5. **Day-of-week analysis:** Thursday (NIFTY expiry) and Wednesday (BANKNIFTY expiry) have different VWAP behavior — model separately
6. **R:R enforcement:** Mode A requires minimum R:R of 1.5 — reject any VWAP setup where target distance is less than 1.5× stop distance

---

## Strategy 6: Momentum Strategy

**Role in Scoring:** Supporting (adds confidence, not core score)  
**Integration:** Momentum signals improve confidence score but do not directly add points to the composite score — they act as a tiebreaker and filter  
**Caution:** NEVER use momentum indicators in isolation for FnO entry decisions

### Philosophy

Momentum is an output of OI build-up and volume accumulation, not an independent predictor. When momentum confirms what OI and Volume are already saying, it provides additional confidence. When momentum contradicts OI, discard the momentum signal.

> RSI and MACD are symptoms. OI and Volume are causes. Treat symptoms only after diagnosing causes.

### Inputs

- Rate of Change (ROC): 5-bar ROC and 10-bar ROC on the primary timeframe
- RSI(14): in context of trend, not standalone
- MACD histogram: direction and acceleration, not absolute value
- Price momentum: percentage move from session open
- Futures basis change: expanding premium = momentum in futures, not just spot
- Relative momentum: instrument vs Nifty 50 (is it leading or lagging the index?)
- Momentum breadth: how many constituents of Nifty 50 are also trending the same direction (breadth confirmation)

### Conditions

**Momentum CONFIRMS a bullish directional signal:**
1. ROC(5) > 0 AND ROC(10) > 0 (multi-period momentum aligned)
2. RSI(14): between 55–72 (above 50 = bullish but not overbought; above 72 in India FnO = reversion risk begins)
3. MACD histogram: positive and rising for at least 2 consecutive bars
4. Price has not made a vertical parabolic move (last 3 bars combined < 2×ATR — measured move, not exhaustion)
5. Relative momentum: instrument is outperforming Nifty 50 on the same timeframe

**Momentum WARNS against over-extension:**
- RSI > 78 on 5m or 15m: momentum exhaustion risk — reduce confidence score
- MACD histogram declining while price still rising: negative divergence — strong warning
- ROC(1) > 2×ATR in single bar: potential exhaustion spike — do not enter

### Confidence Score Impact (not direct points — modifies confidence %)

| Scenario | Confidence Adjustment |
|----------|-----------------------|
| Full momentum confirmation (all 5 conditions) | +5% confidence |
| Partial confirmation (3 of 5 conditions) | +2% confidence |
| Momentum neutral (mixed signals) | 0 |
| RSI > 78 or negative divergence | −5% confidence |
| Parabolic exhaustion candle | −8% confidence |

### Weaknesses

- RSI overbought in a strong trend can stay "overbought" for hours — classic amateur mistake is shorting on RSI > 70 in BANKNIFTY
- MACD is a lagging indicator of a lagging indicator — in fast FnO moves, MACD has already turned by the time most of the move is complete
- Momentum is correlated with trend — it adds less independent information when trend score is already high
- Mean-reversion bias of Indian retail participants: high RSI attracts counter-traders, creating self-fulfilling RSI reversion in narrow-range instruments

### Ideal Market Regime

- **TRENDING:** Momentum is moderately useful as confirmation
- **SIDEWAYS:** Momentum signals are extremely noisy — do not use
- **HIGH_VOLATILITY:** Momentum spikes but reverses immediately — dangerous

### Historical Validation Requirements

1. **Standalone vs combined:** Backtest momentum signals standalone first — if standalone win rate < 50%, it adds no standalone predictive value; use only as a filter
2. **RSI threshold analysis:** Map RSI levels to forward return probability at different ADX levels — find the RSI zone that actually predicts returns (it may not be the textbook overbought/oversold levels)
3. **Divergence effectiveness:** Measure MACD divergence prediction accuracy over 100+ occurrences — target > 60% for divergence signal to reduce confidence score
4. **Regime-conditional IC:** Measure information coefficient of momentum signals separately for each regime — momentum may have IC > 0.05 in trending regimes but IC < 0 in sideways

---

## Strategy 7: Volatility (IV Analysis)

**Role in Scoring:** Supporting · Maximum 5 points (direct)  
**Extended Role:** Determines option strategy selection (directional vs non-directional)  
**India-Specific:** India VIX is the primary input, not just implied volatility from option chain

### Philosophy

IV analysis answers the most important structural question before every options trade:

> **Are you buying expensive insurance or selling cheap insurance?**  
> Buying expensive options destroys edge. Selling options before news destroys accounts.  
> IV regime determines which options strategy is structurally advantaged.

### Inputs

**India VIX:**
- Current India VIX level and 10-day SMA
- India VIX percentile (1-year rolling)
- India VIX intraday rate of change: sudden spike > 10% = reduce all scores by 20%
- India VIX below 13: historically low fear → buy volatility (complacency zone)
- India VIX above 22: high fear → sell volatility (premium collection zone)

**Option Chain IV:**
- ATM IV for nearest expiry
- IV Percentile (option-chain level, as computed in Strategy 3)
- IV Premium over 30d Realized Volatility
- IV term structure: front vs back month IV spread

**Event Calendar:**
- RBI Monetary Policy: 6 per year (scheduled)
- Union Budget: once per year (usually February)
- FOMC meetings: 8 per year (global IV impact)
- US CPI releases: monthly (global risk on/off)
- Quarterly results for major NIFTY 50 constituents
- State and National elections

### Conditions

**IV SELL signal (sell volatility — collect premium):**
1. IV Percentile > 70% (historical context: options are expensive)
2. No event within 7 calendar days (event risk would cause IV to stay elevated or spike further)
3. IV Premium (IV − 30d RV) > 5% (statistical edge demonstrably positive)
4. Regime: SIDEWAYS (low directional risk — theta collection strategy)
5. Days to expiry: 7–21 days (optimal Theta/Gamma ratio — close to 14 DTE for Iron Condor)

**IV BUY signal (buy volatility — own the move):**
1. IV Percentile < 20%
2. Identified catalyst within 3–5 calendar days
3. India VIX at 3-month low
4. IV Skew compressed (unusually low skew = market not pricing tail risk)
5. Days to expiry: 5–15 days before event

**IV NEUTRAL (no IV-based edge):**
- IV Percentile 20–70%: no structural advantage for either buying or selling
- No signal generated; IV sub-score = 3/5 (base score for normal IV conditions)

### Strength Score Breakdown (0–5 points)

| Scenario | Points |
|----------|--------|
| Clear IV sell setup: IV Percentile > 70% + no event + sideways regime + DTE 7–21 | 4–5 |
| Clear IV buy setup: IV Percentile < 20% + event approaching + DTE 5–15 | 4–5 |
| Moderate IV extreme (60–70% or 20–30%) | 2–3 |
| IV normal range (30–60%): base rate | 3 |
| IV spike during event (VIX > 25 intraday): uncertainty too high | 0–1 |
| Event approaching but IV already elevated (double-risk): | 0 (no trade) |

### India VIX Level Guide

| VIX Level | Market Condition | FnO Strategy Preference |
|-----------|-----------------|------------------------|
| < 11 | Extreme complacency | Long Vol (buy options before catalyst) |
| 11–14 | Low fear | Normal directional trades; consider long vol |
| 14–18 | Normal | Standard directional trades |
| 18–22 | Elevated anxiety | Reduce position size; prefer selling OTM options |
| 22–28 | Fear zone | Short volatility strategies; hedged positions |
| > 28 | Panic | Do NOT sell naked options; hedged only; reduce size |
| > 35 | Extreme panic | All new trades require hedge; existing positions review |

### Weaknesses

- India VIX measures NIFTY 50 options volatility only — BANKNIFTY IV has no equivalent VIX index
- Selling options during high IV can be extremely profitable until a Black Swan event — risk of ruin is real without proper position sizing (Kelly Criterion)
- IV can remain elevated for weeks (elections, global recession fears) — short vol strategies run negative carry during sustained high-IV periods
- Event dates shift unexpectedly (RBI emergency meetings, geopolitical events) — event calendar must be maintained in real-time
- Realized volatility after events is not always higher than implied (IV overestimates realized vol on average — this is the vol premium)

### Ideal Market Regime

| VIX Level | Regime | Optimal Strategy |
|-----------|--------|-----------------|
| < 14 | LOW_VOLATILITY + Sideways | Long Straddle before catalyst |
| 14–18 | Normal | Directional options (calls or puts) |
| 18–22 | HIGH_VOLATILITY early | Iron Condor, reduce deltas |
| > 22 | HIGH_VOLATILITY | Short Strangle / Iron Condor (with defined risk) |
| > 28 | Extreme | Cash or heavily hedged only |

### Historical Validation Requirements

1. **VIX data:** Minimum 3 years (must include: COVID crash 2020, 2019 elections, 2020–2021 recovery, 2022 global selloff, 2024 election uncertainty)
2. **IV Percentile window:** Always compute on rolling 1-year (252 days) — static historical period is not comparable across years
3. **Event-specific backtest:** Separately backtest IV trades around: RBI days, Budget days, FOMC days, election results — each has different IV behavior
4. **Short vol scenario testing:** Mandatory stress test: what happens to short vol positions if India VIX doubles in 3 days? Calculate maximum loss and ensure it stays within portfolio drawdown limits
5. **Vol premium measurement:** Compute historical mean of (IV − next 30d realized vol) for each instrument — this is the theoretical edge for option sellers
6. **DTE sensitivity:** Separate P&L by DTE brackets: 7–10, 10–14, 14–21, 21–30 — find the DTE window with best risk-adjusted return for short vol strategies

---

## Strategy 8: Breakout Strategy

**Role:** Supporting strategy — adds confidence when breakout is genuine  
**Weight Impact:** Not a direct scoring component; acts as a confirmation multiplier  
**Warning:** 60–70% of breakouts in Indian FnO are false — this strategy MUST be combined with volume and OI confirmation

### Inputs

**Key Level Identification:**
- Previous Day High (PDH) and Previous Day Low (PDL) — most important intraday breakout levels
- Previous Week High (PWH) and Previous Week Low (PWL) — medium-term breakout levels
- Round numbers: Nifty 18,000 / 18,500 / 19,000 / 19,500 / 20,000 etc. — psychological barriers
- OI-based levels: highest CE OI strike = resistance; highest PE OI strike = support
- 52-week high/low: extreme breakout levels with high institutional attention

**Breakout Quality Indicators:**
- Volume on breakout candle vs 20-period average (MANDATORY — 2× minimum)
- Consolidation before breakout: number of bars with < 0.3× ATR range (coiling)
- Candle close position: must CLOSE above resistance (not just intraday spike through)
- Retest behavior: after initial breakout, does price come back to test the level and hold?
- ATR expansion: is the range expanding (breakout) or contracting (false move)?

**Breakout Types (in order of reliability):**

| Type | Description | Reliability |
|------|-------------|-------------|
| Consolidation breakout | Tight range (3+ bars) then expansion | ★★★★★ |
| Opening Range Breakout (ORB 30m) | First 30-min high/low break after 10:00 | ★★★★ |
| Key level (PDH/PDL) | Previous session's extreme | ★★★ |
| Round number | Psychological level (19000, 19500) | ★★ |
| Intraday resistance | Level touched 2+ times today | ★★ |

### Conditions

**VALID BULLISH BREAKOUT (all required):**
1. Price closes a 5-minute candle above the resistance level (close, not just touch)
2. Breakout volume >= 2× 20-period average on the break candle
3. ATR on the break candle > previous 5-bar average ATR (range is expanding, not contracting)
4. India VIX is not spiking > 10% intraday (panic environment invalidates all breakouts)
5. OI at the resistance strike: CE OI NOT increasing significantly (no fresh call writing against the move)

**FALSE BREAKOUT FILTERS (any one present = reject signal):**
- Break candle closes INSIDE the resistance level (wick through, body does not close above)
- Volume on break candle is BELOW 20-period average
- RSI(14) > 78 at breakout (overbought + breakout = reversal risk, not continuation)
- DTE <= 2 (max pain gravitational pull near expiry overpowers breakouts)
- VIX spike > 10% intraday: chaos market, breakouts reverse violently
- Time of day: after 14:45 IST (low probability of sustained breakout continuation)

**RETEST CONFIRMATION (optional but highest probability):**
- After initial breakout, price pulls back to the broken level
- Price bounces off the former resistance (now acting as support) with volume >= 1.5× average
- This retest entry is the HIGHEST probability entry — more reliable than the initial break

### Confidence Score Impact

| Scenario | Confidence Adjustment |
|----------|-----------------------|
| Consolidation breakout + 2× volume + OI confirmation + no resistance above | +8% confidence |
| PDH/PDL breakout + volume confirmed | +5% confidence |
| Retest confirmation after clean breakout | +10% confidence |
| Breakout on sub-average volume | −5% confidence |
| Breakout near max pain on expiry week | −8% confidence |

### Weaknesses

- False breakout rate is structurally high (60–70%) — this strategy loses money standalone
- Smart money fades PDH/PDL levels because they are too well known — retail buys the breakout, institutions sell it
- BANKNIFTY gaps through key levels overnight (SGX Nifty), making intraday breakout levels meaningless
- Round numbers in NIFTY are heavily defended by institutional option writers (call/put sellers at those strikes) — require significant momentum to overcome

### Ideal Market Regime

- **LOW_VOLATILITY transitioning to HIGH_VOLATILITY:** Best — consolidation breakouts with IV expansion
- **TRENDING:** Good for key-level breakouts
- **SIDEWAYS:** Worst — ranges are the norm, breakouts reverse
- **HIGH_VOLATILITY:** Chaotic — breakouts overshoot but reverse violently

### Historical Validation Requirements

1. **False breakout tracking:** Build a false breakout classifier — price closes above level then returns below within 3 bars. Measure false breakout rate by type (PDH vs round number vs OI level)
2. **Volume threshold optimization:** Compare 1.5×, 2×, 2.5× average — find the volume threshold that reduces false breakout rate to < 35% while preserving enough signals
3. **Retest entry validation:** Measure if retest entries produce better win rate and R:R than initial breakout entries — if retest is significantly better, use retest as primary entry
4. **Minimum required R:R:** Given lower win rate, breakout strategy must target minimum R:R of 2:1
5. **Level quality ranking:** Rank breakout levels by historical reliability (consolidation > ORB > PDH > round number) and apply different volume thresholds per level type

---

## Combined Signal Pipeline

### How Strategies Combine into a Final Score

```
Step 1: Market Regime Classification
  → Determines weight multipliers for each strategy component

Step 2: Individual Component Scores
  OI Build-up:     0–25 pts (×regime multiplier)
  Trend Following: 0–20 pts (×regime multiplier, 0 if ADX < 20)
  Option Chain:    0–20 pts (×regime multiplier)
  Volume Analysis: 0–15 pts (×regime multiplier)
  VWAP Analysis:   0–10 pts (×regime multiplier)
  Sentiment:       0–5  pts (×regime multiplier)
  IV Analysis:     0–5  pts (×regime multiplier)

Step 3: Data Completeness Check
  → If total available data < 60% of components: INSUFFICIENT_DATA rejection
  → Missing components: redistribute weight proportionally to available components

Step 4: Raw Score (0–100)
  → Sum of all weighted component scores

Step 5: Confidence Score (0–100, separate from raw score)
  Base:            score × 0.60
  Win rate adj:    +5 if strategy win rate > 55% on similar setups
  Regime adj:      -20 if signal direction contradicts current regime
  Data adj:        -10 if any core component is using stale data (>5 min)
  Sentiment adj:   -5 if sentiment is fallback (NeutralSentimentProvider)
  Momentum adj:    +5 if momentum confirms, -5 if divergence detected
  Loss streak adj: min(0, -3 × consecutive_losses), floor at -15

Step 6: Composite Signal
  Direction:       LONG or SHORT (higher scoring direction wins)
  Score:           0–100 (from Step 4)
  Confidence:      0–100 (from Step 5)
  
  Execute only if: Score >= 70 AND Confidence >= 65

Step 7: Risk Engine Gate (15 pre-trade checks)
  → Described in Doc 17 — Portfolio Risk Engine
  → No trade occurs without risk engine approval
```

---

## NSE FnO Time-Based Rules

### Time-of-Day Trading Rules

| Time Window | Rule | Reason |
|-------------|------|--------|
| 09:15–09:30 | No new positions | Gap-fill uncertainty; VWAP not established; OI data too fresh |
| 09:30–10:30 | High opportunity; enter on trend + OI confirmation | Best liquidity, clearest directional signals |
| 10:30–12:30 | Continue existing positions; new entries on strong setups only | Trend established or choppy; evaluate regime |
| 12:30–13:30 | Avoid new entries (lunch-hour low volume) | Volume drops 50–70%; VWAP signals unreliable |
| 13:30–14:30 | Resume entries on reversal of morning trend or continuation | Second session begins; re-evaluate regime |
| 14:30–15:15 | Strong opportunity window (closing momentum) | Institutional order execution, position squaring |
| 15:15–15:30 | Close all intraday positions; no new entries | Close-related volatility; unpredictable last-minute moves |

### Expiry Week Rules

| DTE | Adjustment |
|-----|------------|
| DTE >= 7 | Normal strategy weights apply |
| DTE 4–6 | Reduce position size by 25%; increase confidence threshold to 70 |
| DTE 2–3 | Reduce position size by 50%; max pain becomes dominant (OI weight shifts to max pain); avoid directional breakouts |
| DTE 1 | Only close/roll existing positions; no new directional entries unless score >= 85 |
| DTE 0 (expiry day) | Only trade with explicit expiry day strategy; extreme gamma risk; no position after 15:00 |

### India-Specific Risk Events (Automatic Score Reduction)

When these events occur or are within 24 hours:
- **RBI Monetary Policy announcement:** −20 on all confidence scores until announcement, no short-vol positions
- **Union Budget:** −30 on all confidence scores day before, +normal after release
- **FOMC meeting:** −10 on all confidence scores (global IV impact on India VIX)
- **Election results:** −40 on all confidence scores; resume after first hour of normal trading post-result
- **US CPI release (8:30 PM IST previous night):** +5 or −5 to next-day sentiment score based on direction

---

## Portfolio-Level Correlation Rules

### Signal Independence Requirements

Not all signals that look independent actually are. Correlated signals lead to false confidence.

| Strategy A | Strategy B | Correlation | Action |
|------------|------------|-------------|--------|
| OI Build-up | Volume Analysis | Medium (0.4) | Include both; they measure different things |
| Trend Following | Momentum | High (0.65) | Momentum adds < 5% independent value when trend is already confirmed; use as tiebreaker only |
| Option Chain | OI Build-up | Medium-high (0.55) | Both use OI data but different dimensions; include both with awareness |
| VWAP | Trend Following | Medium (0.5) | Both trend-oriented; ensure VWAP weight is not double-counting trend |
| IV Analysis | Option Chain | High (0.7) | IV is embedded in option chain analysis; IV score should only add for extreme IV regimes |
| Breakout | Volume | High (0.6) | A valid breakout requires volume; breakout adds confidence only when volume score is already high |

### Cross-Position Correlation Management

- NIFTY and BANKNIFTY positions have correlation ~0.75 — holding both doubles risk, not confidence
- A NIFTY LONG + BANKNIFTY SHORT position has effectively neutralized each other on macro risk
- Maximum 2 simultaneous positions with underlying correlation > 0.6 allowed (enforced by Risk Engine)

---

## V1 Implementation Priority

### Phase 1 — Minimum Viable Signal (build first)

1. **OI Build-up:** Long/Short Build-up classification from futures OI (25 pts) — build first
2. **Trend Following:** EMA alignment + Supertrend + ADX gate (20 pts) — build second
3. **Volume Analysis:** Volume ratio + OBV (15 pts) — build third
4. **VWAP:** Session VWAP ± bands (10 pts) — build fourth
5. **Option Chain (basic):** Highest OI strikes as support/resistance only (10 pts initially)

**V1 Total achievable score: 80 points** — sufficient to generate LONG/SHORT signals

### Phase 2 — Full Option Chain + IV

6. **Option Chain (full):** IV surface, IV Skew, GEX, full PCR (20 pts) — replace Phase 1 basic version
7. **IV Analysis:** IV Percentile, India VIX regime, vol strategy selection (5 pts)
8. **Sentiment:** News sentiment via AI provider (5 pts)

**V2 Total: 100 points** — all thresholds fully calibrated

### Phase 3 — Advanced Signals

9. Breakout confidence multiplier
10. Momentum confidence adjustment  
11. FII flow integration (EOD)
12. Gamma Exposure (GEX) calculation
13. Max Pain real-time tracking
14. Multi-expiry OI analysis (not just nearest expiry)

---

## Historical Validation Master Requirements

### Backtesting Standards for the Full Framework

1. **Data requirement:** Minimum 2 years of intraday 1-minute OHLCV + OI data, 2 years of option chain snapshots at 1-minute intervals, 2 years of India VIX data
2. **Walk-forward protocol:** 6-month in-sample training, 2-month out-of-sample validation, roll forward by 1 month, minimum 12 cycles
3. **Regime-conditional backtesting:** Never report aggregate win rate across all regimes — always report per-regime performance separately (a strategy can be profitable in trending but unprofitable overall due to sideways losses)
4. **Expiry-period isolation:** Mandatory separate reporting for DTE 7+, DTE 3–6, DTE 0–2
5. **Transaction costs:** Include all costs: brokerage (₹20/order flat), STT (0.1% on sell side for options), exchange fees, SEBI turnover fee, GST — net of costs, not gross
6. **Slippage model:** Use historical bid-ask spreads from option chain data to simulate realistic fills — market order slippage in BANKNIFTY options can be ₹2–5 per unit on ATM strikes
7. **Minimum statistical significance:** Each strategy component must have at least 200 independent signals in backtest — fewer signals = insufficient statistical power
8. **Overfitting prevention:** Limit free parameters to maximum 3 per strategy component; use cross-validated optimization; report out-of-sample performance prominently
9. **Performance minimum thresholds (net of costs):**
   - Overall Profit Factor: >= 1.4
   - Overall Sharpe Ratio: >= 0.8
   - Maximum consecutive losses: <= 8
   - Maximum drawdown: <= 15% of capital
   - Win rate: >= 50% (lower acceptable only with Profit Factor > 1.6)
   - Calmar Ratio (Annual Return / Max Drawdown): >= 1.0
10. **Monte Carlo simulation:** Run 1,000 random shuffles of trade sequence — confirm that the strategy's observed performance is not due to lucky ordering of wins/losses
11. **Live paper trading validation:** Before going live, paper trade the full strategy for minimum 3 months — live market data often reveals edge decay not visible in historical backtest

---

*Document authored from first principles for institutional-grade Indian FnO trading.*  
*Cross-references: Doc 16 (Signal Scoring Engine) · Doc 17 (Portfolio Risk Engine) · Doc 04 (Signal Flow Diagram)*  
*No code in this document. Implementation details in application service layer.*
