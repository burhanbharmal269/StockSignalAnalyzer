# 21 — Signal Engine

**Platform:** NSE · Indian Equity FnO  
**Pipeline:** Strategy Layer → Score Engine → Confidence Engine → Risk Engine → Recommendation  
**Version:** 1.0  

---

## Design Goals

> **A signal is not a prediction. It is a structured, reproducible, auditable claim — with a score, a confidence level, a bounded time-to-live, and a deterministic explanation — that the Risk Engine may or may not approve.**

### Core Invariants

| Invariant | Rule |
|-----------|------|
| Determinism | Same inputs → same output, always. No randomness inside the engine. |
| Separation | Score (signal strength) and Confidence (signal reliability) are computed independently. |
| Audit trail | Every score, every penalty, every adjustment is stored with its reason. |
| AI boundary | AI provides sentiment only. AI is forbidden from score computation, confidence calculation, risk decisions, position sizing, or order placement. |
| Reproducibility | The exact weight configuration used (SHA-256 hash) is stored with every signal for later audit. |
| Time-bounded | Every signal has a hard TTL. A stale signal is worthless — never execute an expired signal. |
| Direction primacy | A signal without a clear direction is not a signal. It is noise. |

---

## Pipeline Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           SIGNAL ENGINE PIPELINE                             │
└──────────────────────────────────────────────────────────────────────────────┘

INPUTS:
  Market Tick Data (via Redis cache)
  Option Chain (NSE, ~60s refresh)
  India VIX (NSE, ~60s refresh)
  Computed Features (ADX, EMA, ATR, BB Width, VWAP — post 15-min candle)
  Regime State (from Regime Engine, updates every 15 min)
  AI Sentiment (from IAIProvider, async/decoupled)
  FII/DII Data (EOD, from NSE Bhav Copy)
  Historical Performance DB (signal_performance_stats table)

STAGE 1 ─ STRATEGY LAYER
  Each of 7 scoring components evaluates its indicators independently.
  Each returns: long_score (0–max_weight), short_score (0–max_weight), metadata.

STAGE 2 ─ SCORE ENGINE
  Direction Vote → determines signal direction (LONG / SHORT / NEUTRAL)
  Regime Multipliers → applied from RegimeState
  Score Aggregation → normalized 0–100 composite score
  Score Penalties → up to 5 penalty types applied
  Output: final_score (0–100), direction, direction_conviction

STAGE 3 ─ CONFIDENCE ENGINE
  9-component additive formula
  Historical accuracy lookup by signal fingerprint
  Calibration correction applied
  Output: final_confidence (0–100)

GATE CHECK:
  final_score >= 70 AND final_confidence >= 65 → proceed
  Otherwise: signal labeled NO_SIGNAL, archived, not forwarded to Risk Engine

STAGE 4 ─ RISK ENGINE
  15 pre-trade checks (see Doc 17)
  Position sizing (ATR-based + Fractional Kelly)
  Output: APPROVED / REJECTED / SIZE_MODIFIED

STAGE 5 ─ RECOMMENDATION
  Structured recommendation object assembled
  Signal explanation generated (template-based, deterministic)
  Published to: signal.risk.approved (event bus) + signals table (DB)
  TTL set: min(generated_at + 30 min, 15:15:00 IST today)
```

---

## Stage 1 — Strategy Layer

### Component Output Contract

Every scoring component returns a `ComponentOutput` with this structure:

```
ComponentOutput:
  component_name:         str
  max_weight:             int            (base weight before regime multipliers)
  long_score:             float          (0 to max_weight — evidence for LONG)
  short_score:            float          (0 to max_weight — evidence for SHORT)
  direction:              LONG | SHORT | NEUTRAL
  conviction:             float          (0–1, how confident the component is in its direction)
  data_freshness_seconds: int            (age of the oldest data used)
  key_finding:            str            (one-line finding for explanation generation)
  metadata:               dict           (component-specific values for explanation templates)
  evaluation_timestamp:   datetime
```

A component can express partial evidence for both directions simultaneously. For example, the Option Chain component may produce long_score=12 and short_score=5 in a mixed signal environment — the engine uses both values.

### Component 1 — OI Build-up (Base Weight: 25)

**Purpose:** Identify whether fresh directional positions are being built or existing ones are being unwound.

**OI Quadrant Classification:**

| Quadrant | Price Change | OI Change | Interpretation | Strength |
|----------|-------------|-----------|---------------|---------|
| Long Build-up | ↑ | ↑ | Fresh longs entering | ★★★★★ |
| Short Covering | ↑ | ↓ | Shorts exiting (bullish, but temporary) | ★★★ |
| Short Build-up | ↓ | ↑ | Fresh shorts entering | ★★★★★ |
| Long Unwinding | ↓ | ↓ | Longs exiting (bearish, but temporary) | ★★★ |

**OI Score Formula:**

```
Step 1: Determine OI change percentage
  oi_change_pct = (current_OI − previous_session_OI) / previous_session_OI × 100
  NOTE: OI from NSE feed has 3–5 minute delay. This is expected and not penalized.

Step 2: Determine Price change percentage
  price_change_pct = (current_price − previous_session_close) / previous_session_close × 100

Step 3: Assign quadrant and base score
  Long Build-up: oi_change_pct > +2% AND price_change_pct > +0.3%
    base_oi_score = min(25, oi_change_pct × 1.8 + price_change_pct × 2.0)
    direction = LONG

  Short Build-up: oi_change_pct > +2% AND price_change_pct < −0.3%
    base_oi_score = min(25, oi_change_pct × 1.8 + abs(price_change_pct) × 2.0)
    direction = SHORT

  Short Covering: oi_change_pct < −2% AND price_change_pct > +0.3%
    base_oi_score = min(15, abs(oi_change_pct) × 1.0 + price_change_pct × 1.5)
    direction = LONG (bullish, but weaker signal)

  Long Unwinding: oi_change_pct < −2% AND price_change_pct < −0.3%
    base_oi_score = min(15, abs(oi_change_pct) × 1.0 + abs(price_change_pct) × 1.5)
    direction = SHORT (bearish, but weaker signal)

  Ambiguous: neither threshold met
    base_oi_score = 8 (noise floor)
    direction = NEUTRAL

Step 4: PCR Adjustment
  pcr = total_put_OI / total_call_OI (from option chain)
  If LONG signal:
    pcr < 0.7 (extreme bullishness, contrarian bearish): −2
    pcr 0.7–1.0 (bullish): +2
    pcr 1.0–1.3 (neutral): 0
    pcr > 1.3 (bearish, contrarian bullish): +3
  If SHORT signal: mirror (pcr > 1.3 adds +3 to short)

Step 5: Max Pain Distance Adjustment
  distance_pct = abs(current_price − max_pain_price) / max_pain_price × 100
  If signal direction is TOWARD max pain AND DTE <= 3:
    If distance_pct > 1%: +2 (gravitational pull toward max pain)
  If signal direction is AWAY from max pain AND DTE <= 2:
    −2 (fighting max pain gravity near expiry)

Step 6: FII Futures Net Position (EOD data, prior day)
  If FII net long futures > +5,000 contracts AND signal LONG: +2
  If FII net short futures < −5,000 contracts AND signal SHORT: +2
  Otherwise: 0

Final OI Score = clamp(base_oi_score + PCR_adj + MaxPain_adj + FII_adj, 0, 25)
```

**Key Finding Template:**  
`"{quadrant} detected — OI {oi_dir} {oi_change_pct}% with price {price_dir} {price_change_pct}%. PCR: {pcr}. FII: {fii_text}."`

---

### Component 2 — Trend Following (Base Weight: 20)

**Purpose:** Confirm that a sustained, measurable directional trend exists. **Hard gate: ADX < 20 returns zero contribution.**

**Score Formula:**

```
HARD GATE CHECK:
  If ADX(14) < 20 on the 15-minute timeframe: return long_score=0, short_score=0, direction=NEUTRAL
  This gate CANNOT be overridden by any other condition.

Step 1: ADX Base Score
  ADX 20–25: 8 pts
  ADX 25–28: 12 pts
  ADX 28–32: 16 pts
  ADX 32–36: 18 pts
  ADX > 36: 20 pts (cap at maximum weight)

Step 2: Directional Index (DI+ vs DI−)
  if DI+ > DI−: direction = LONG
  if DI− > DI+: direction = SHORT
  di_spread = abs(DI+ − DI−)
  Di_spread_score:
    di_spread < 5: 0 (too close to call)
    di_spread 5–10: +3
    di_spread 10–15: +5
    di_spread > 15: +7 (strong directional dominance)

Step 3: EMA Alignment (1-hour timeframe)
  For LONG direction:
    EMA(20) > EMA(50) > EMA(200): full alignment → +5
    EMA(20) > EMA(50) only: partial → +2
    EMA(20) > EMA(200) only: partial → +1
    No alignment: 0
  For SHORT direction: mirror (EMA20 < EMA50 < EMA200 = full alignment)

Step 4: Supertrend(10, 3) on 15-minute chart
  Supertrend direction matches signal direction: +3
  Supertrend direction opposes: 0 (not penalized — Supertrend can lag)

Step 5: Multi-Timeframe Confirmation
  Check EMA alignment on: 5-min, 15-min, 1-hour, Daily
  Timeframes aligned with signal direction:
    3 of 4: +3
    2 of 4: +1
    1 of 4: 0

Step 6: Price Momentum Gate
  For LONG: RSI(14) on 15-min between 45–75 (not overbought): +1
  For SHORT: RSI(14) between 25–55 (not oversold): +1
  Outside range: 0 (overbought for long or oversold for short = poor timing)

Final Trend Score = clamp(ADX_base + DI_spread + EMA_align + Supertrend + MTF + momentum_gate, 0, 20)
```

**ADX < 20 in SIDEWAYS regime:** This is expected behavior. Trend component returns 0. The SIDEWAYS regime multiplier on Trend (0.25×) further dampens any residual contribution.

**Key Finding Template:**  
`"ADX {adx_value} with DI{dominant} leading by {di_spread} pts. EMA alignment: {ema_alignment_text}. Supertrend: {supertrend_status}."`

---

### Component 3 — Option Chain Analysis (Base Weight: 20)

**Purpose:** Read the options market's collective intelligence — IV levels, GEX positioning, OI concentration at strikes.

**Score Formula:**

```
Step 1: IV Percentile Score
  iv_percentile = rolling 252-day percentile of current ATM IV
  For LONG signal (expecting upward move):
    iv_pct 0–20%: +6 (cheap options, good for long — buy premium)
    iv_pct 20–40%: +4
    iv_pct 40–60%: +3 (fair value)
    iv_pct 60–75%: +1 (expensive options limit upside for long strategies)
    iv_pct > 75%: 0 (very expensive — wrong instrument for long options)
  For SHORT signal (expecting downward move or short-vol):
    iv_pct 0–30%: +2
    iv_pct 30–55%: +4
    iv_pct 55–70%: +6 (elevated IV — good for selling premium or bear spreads)
    iv_pct > 70%: +8 (high premium available for short strategies)

Step 2: IV Skew Analysis
  call_iv = average IV of OTM calls (5–10% OTM)
  put_iv = average IV of OTM puts (5–10% OTM)
  skew = put_iv − call_iv
  
  For LONG signal: call_skew (skew < 0, calls more expensive): +2 (call demand = bullish)
  For SHORT signal: put_skew (skew > 0, puts more expensive): +2 (put demand = bearish)
  Neutral skew (abs(skew) < 1%): 0

Step 3: GEX (Gamma Exposure) Analysis
  Positive GEX (market makers net long gamma): market makers act as shock absorbers.
    Price is "pinned" toward the GEX concentration strike.
    If GEX strike is above current price AND signal LONG: +2 (price may be pulled up)
    If GEX strike is above current price AND signal SHORT: −1 (market maker resistance)
  Negative GEX (market makers net short gamma): they amplify moves.
    If signal direction = recent price direction: +2 (gamma squeeze potential)
    Otherwise: −1 (amplified against position)

Step 4: OI Wall Proximity
  Identify the nearest significant OI wall (strike with OI > 1.5× average strike OI):
    For LONG signal: nearest call OI wall above current price
      wall_distance_pct = (wall_strike − current_price) / current_price × 100
      Distance < 0.5%: −3 (immediate resistance)
      Distance 0.5–1.0%: 0
      Distance 1.0–2.0%: +2 (clear room to run)
      Distance > 2.0%: +3 (significant room)
    For SHORT signal: nearest put OI wall below current price (mirror logic)

Step 5: PCR Direction Confirmation
  pcr_trend = change in PCR over last 3 data refreshes (15-minute lag)
  For LONG signal:
    PCR declining (call OI building faster than put OI): +2
    PCR stable: 0
    PCR rising sharply: −1
  For SHORT signal: mirror

Final Option Chain Score = clamp(IV_pct + IV_skew + GEX + OI_wall + PCR_trend, 0, 20)
```

**Key Finding Template:**  
`"IV Percentile {iv_pct}%. {skew_text}. GEX: {gex_interpretation}. Nearest {direction} OI wall at {wall_strike} ({wall_distance_pct}% away)."`

---

### Component 4 — Volume Analysis (Base Weight: 15)

**Purpose:** Confirm that price movements are backed by institutional activity, not retail noise.

**Score Formula:**

```
Step 1: Volume Ratio
  volume_ratio = current_bar_volume / rolling_20_bar_average_volume
  volume_ratio < 0.5: 3 pts (thin market — low conviction)
  volume_ratio 0.5–1.0: 6 pts
  volume_ratio 1.0–1.5: 9 pts
  volume_ratio 1.5–2.0: 12 pts
  volume_ratio >= 2.0: 15 pts (significant institutional participation)

Step 2: Volume Divergence Penalty
  A price move on declining volume is suspect.
  If signal LONG AND price made higher high AND current volume < previous bar volume:
    −5 pts (volume divergence — weakening momentum)
  If signal SHORT AND price made lower low AND current volume < previous bar volume:
    −5 pts (volume divergence)
  Note: this is a penalty, applied AFTER the volume ratio score.

Step 3: OBV Confirmation
  OBV (On-Balance Volume) trend calculated over last 10 bars:
  If OBV trend matches signal direction: +2
  If OBV trend opposes: −2
  If OBV flat: 0

Step 4: Cumulative Delta (order-flow proxy)
  delta = aggressive_buys − aggressive_sells (from tick data)
  cumulative_delta over last 30 minutes:
  For LONG signal:
    delta > 0 (buying pressure): +2
    delta < 0 (selling pressure despite long signal): −2
  For SHORT signal: mirror

Step 5: VPOC (Volume Point of Control) Proximity
  VPOC = price level with highest volume traded today (session VWAP variant)
  If current price is within 0.2% of VPOC:
    LONG signal: +1 (support/resistance zone — potential inflection)
    SHORT signal: +1
  Otherwise: 0

Final Volume Score = clamp(volume_ratio_score − divergence_penalty + OBV + delta + VPOC, 0, 15)
```

**Key Finding Template:**  
`"Volume {volume_ratio}× average. {divergence_text}. OBV: {obv_trend}. Cumulative delta: {delta_direction}. VPOC: {vpoc_relation}."`

---

### Component 5 — VWAP Analysis (Base Weight: 10)

**Purpose:** Use VWAP as the equilibrium reference — either as a mean-reversion target (SIDEWAYS regime) or as a trend validation level (TRENDING regime). Mode is determined automatically by the Regime Engine output.

**Mode A — Mean Reversion (active in SIDEWAYS regime):**

```
Entry conditions for LONG (buy the dip to VWAP):
  price_deviation = (current_price − VWAP) / VWAP × 100
  
  price_deviation < −1.5σ AND volume_ratio > 1.5 AND RSI(14) < 35:
    score = 10 (highest conviction mean-reversion setup)
  price_deviation < −1.0σ AND volume_ratio > 1.2 AND RSI(14) < 45:
    score = 7
  price_deviation < −0.5σ AND RSI(14) < 50:
    score = 4
  price_deviation >= 0 (price above VWAP, no long dip opportunity):
    score = 0

For SHORT (sell the spike to VWAP): mirror logic with positive deviations.

Touch Count Degradation:
  Each time price has already touched and bounced off this VWAP level today:
  touch_count = 0: no degradation
  touch_count = 1: score × 0.85 (each subsequent touch is weaker)
  touch_count = 2: score × 0.70
  touch_count >= 3: score × 0.50 (level is exhausted)
```

**Mode B — Trend Confirmation (active in TRENDING regime):**

```
For LONG signal (VWAP as dynamic support in uptrend):
  price_above_VWAP = current_price > VWAP
  price_bouncing_from_VWAP = price approached within 0.2% of VWAP AND reversed upward in last 3 bars
  
  price_above_VWAP AND price_bouncing_from_VWAP: score = 10
  price_above_VWAP only: score = 6 (in trend, above VWAP = baseline confirmation)
  price_below_VWAP AND signal LONG: score = 2 (below VWAP in uptrend = caution)

For SHORT signal: mirror (VWAP as dynamic resistance in downtrend)
```

**Key Finding Template (Mode A):**  
`"Price at −{deviation_sigma}σ below VWAP ({price_distance} pts). Volume {volume_ratio}×. RSI {rsi_val}. {touch_count_text}."`

**Key Finding Template (Mode B):**  
`"Price {above_below} VWAP ({vwap_level}). {bounce_text}. Trend Mode: VWAP acting as {support_resistance}."`

---

### Component 6 — Sentiment Analysis (Base Weight: 5)

**Purpose:** Capture news and social media sentiment as a confidence modifier. **This is the ONLY component that uses an AI provider.** The AI provider is strictly forbidden from influencing score, risk, or order decisions.

**Sentiment Scoring:**

```
Sentiment Source: IAIProvider.analyze_sentiment(symbol, news_context)
Provider priority: OpenAI (gpt-4o-mini) → AnthropicProvider (claude-haiku-4-5) → GeminiProvider → OllamaProvider → NeutralSentimentProvider

Sentiment → Score mapping:
  STRONGLY_BULLISH:
    If signal LONG: 5 pts
    If signal SHORT: 0 pts (negative contribution absorbed in confidence, not score)
  BULLISH:
    If signal LONG: 4 pts
    If signal SHORT: 1 pt
  NEUTRAL: 2.5 pts (regardless of direction — pure uncertainty)
  BEARISH:
    If signal SHORT: 4 pts
    If signal LONG: 1 pt
  STRONGLY_BEARISH:
    If signal SHORT: 5 pts
    If signal LONG: 0 pts

Fallback detection: If NeutralSentimentProvider is used (all primary providers unavailable):
  Score: 2.5 pts (flat/neutral)
  Confidence Engine separately applies −5 to confidence for using fallback provider.
  This is logged as: sentiment_provider = "FALLBACK"
```

**Sentiment Freshness:** Sentiment is computed asynchronously. If the cached sentiment result is > 60 minutes old: treat as NEUTRAL (2.5 pts). Do not block signal generation waiting for sentiment.

**Key Finding Template:**  
`"Sentiment: {sentiment_label} via {provider_name}. Context: {top_news_headline}."`

---

### Component 7 — IV Analysis (Base Weight: 5)

**Purpose:** Assess whether the current IV environment favors buying or selling volatility, and whether IV is directionally supportive.

**Score Formula:**

```
Step 1: India VIX Level Context
  India VIX levels (from Doc 20):
    < 11 (extreme complacency): IV analysis most useful for long-vol positioning
    11–14 (low fear): slightly advantageous for short-vol
    14–18 (normal): neutral — both strategies viable
    18–22 (elevated): short-vol requires caution; long-vol starts making sense
    22–28 (fear): high-vol regime — long-vol clearly advantaged
    > 28 (panic): long-vol or no-vol. Short-vol is capital destruction.

Step 2: IV Rank (IVR)
  IVR = (current_ATM_IV − 52_week_low_IV) / (52_week_high_IV − 52_week_low_IV) × 100
  
  This differs from IV Percentile (which is percentile-based, not range-based).
  Both are tracked. When they diverge significantly (> 20 pts), flag for explanation.

Step 3: HV/IV Ratio
  hv_iv_ratio = historical_volatility_10d / atm_iv
  hv_iv_ratio > 1.2: realized vol > implied vol → options are CHEAP → buy vol
  hv_iv_ratio 0.8–1.2: fairly priced
  hv_iv_ratio < 0.8: realized vol < implied vol → options are EXPENSIVE → sell vol

Step 4: IV Score
  For LONG vol signal (buy premium):
    iv_percentile < 20% AND IVR < 30%: 5 pts
    iv_percentile 20–35%: 3 pts
    iv_percentile 35–50%: 1 pt
    iv_percentile > 50%: 0 pts (too expensive to buy)
    hv_iv_ratio > 1.2: +2 bonus (HV supports vol buying)
  
  For SHORT vol signal (sell premium):
    iv_percentile > 70% AND IVR > 65%: 5 pts
    iv_percentile 55–70%: 3 pts
    iv_percentile 40–55%: 1 pt
    iv_percentile < 40%: 0 pts (too cheap to sell)
    hv_iv_ratio < 0.8: +2 bonus (HV supports vol selling)
    India VIX > 20: −2 (short vol in high-VIX dangerous — structural penalty)

  Note: For directional trades (LONG/SHORT on futures), IV Analysis is a secondary gauge.
  For options-focused strategies, this component carries higher effective weight (via regime multiplier).

Final IV Score = clamp(base_iv_score + bonuses − penalties, 0, 5)
```

**Key Finding Template:**  
`"IV Percentile: {iv_pct}%, IVR: {ivr}%. India VIX: {vix_level} ({vix_label}). HV/IV: {hv_iv_ratio}. Recommendation: {vol_bias}."`

---

### Supporting Components (Confidence Modifiers, Not Score Components)

**Momentum (±5% to confidence, not score):**

```
Momentum indicators: RSI(14), Stochastic RSI, Rate of Change (ROC)
  Momentum confirms signal direction: +5 to confidence
  Momentum neutral: 0
  Momentum diverges (price up but RSI down, or vice versa): −5 to confidence
```

**Breakout (confidence multiplier, not score):**

```
Breakout detection criteria (ALL required):
  Price breaches a defined resistance/support level (20-bar high/low)
  Volume at breakout bar >= 2× 20-bar average volume (MANDATORY gate)
  Candle closes beyond the level (not just a wick)

If breakout confirmed: +5 to confidence
If breakout attempt WITHOUT volume confirmation: −8 to confidence (high false-breakout risk)
If retest-and-hold after breakout: +5 to confidence (highest-probability pattern)

Note: 60–70% of breakouts on NSE fail without volume confirmation.
The mandatory 2× volume gate is not optional.
```

---

## Stage 2 — Score Engine

### Step 1: Direction Voting

Before aggregating scores, the engine determines the signal direction by weighted vote.

```
For each component i (all 7 scoring components):
  if component.direction == LONG: long_votes += component.base_weight
  if component.direction == SHORT: short_votes += component.base_weight
  if component.direction == NEUTRAL: neutral_votes += component.base_weight

total_votes = long_votes + short_votes + neutral_votes  (= 100)

signal_direction:
  if long_votes > short_votes AND long_votes > neutral_votes: LONG
  if short_votes > long_votes AND short_votes > neutral_votes: SHORT
  otherwise: NEUTRAL → signal dies here (no further computation)

direction_conviction = max(long_votes, short_votes) / total_votes
```

**Conviction threshold:** If `direction_conviction < 0.45`, signal is NEUTRAL regardless of which direction leads. A 44% vs 40% split is not a tradeable signal.

### Step 2: Regime Multiplier Application

```
For each component i:
  effective_weight_i = base_weight_i × regime_multiplier_i (from Regime Engine, Doc 20)

These effective weights determine how much each component's score contributes
to the aggregate. The regime does not change individual component scores —
it changes how much weight those scores carry in the final sum.
```

### Step 3: Score Aggregation Formula

```
For signal_direction D (LONG or SHORT):

  For each component i:
    if component_i.direction == D:
      directional_score_i = component_i.long_score (if D=LONG) or component_i.short_score (if D=SHORT)
    if component_i.direction == opposite(D):
      directional_score_i = −(opposing component score) × 0.30  (counter-evidence, partial drag)
    if component_i.direction == NEUTRAL:
      directional_score_i = component_i.long_score × 0.40  (partial credit — uncertain component)

  weighted_numerator = Σ(directional_score_i × effective_weight_i)
  weighted_denominator = Σ(base_weight_i × effective_weight_i)
  
  raw_score = (weighted_numerator / weighted_denominator) × 100
  raw_score = clamp(raw_score, 0, 100)
```

This formulation ensures:
- Counter-directional components create a small drag on the score (−30% of their score)
- Neutral components give partial credit (40% of their evidence)
- The regime multiplier shifts the relative importance of components without inflating the 0–100 range

### Step 4: Score Penalties

Applied sequentially after raw_score is computed. Each penalty reason is stored.

**Penalty 1 — Data Staleness:**
```
For each component i where data_freshness_seconds > 300 (5 minutes):
  raw_score −= 10
  reason logged: "Component {name} data is {age}s old"
Maximum deduction from this penalty: −20 (two stale components = −20, three still −20)
```

**Penalty 2 — Low Direction Conviction:**
```
if direction_conviction < 0.60 AND direction_conviction >= 0.45: raw_score −= 8
if direction_conviction < 0.45: raw_score −= 15
reason logged: "Direction conviction {conviction_pct}% — below threshold"
```

**Penalty 3 — Market Hours:**
```
if market_time in [09:15, 09:30]: raw_score −= 10
  reason: "Opening auction volatility window — elevated noise"
if market_time in [15:15, 15:30]: raw_score −= 20
  reason: "No new FnO entries permitted after 15:15 IST"
  Note: signals generated after 15:15 should be rejected at TTL gate before this.
```

**Penalty 4 — Regime Mismatch:**
```
if signal_direction contradicts regime.direction_layer (e.g., LONG in TRENDING_BEARISH):
  raw_score −= 15
  reason: "Signal direction opposes regime direction layer"
  Note: This is separate from the −20 confidence penalty for regime mismatch.
        Both penalties apply — score penalty + confidence penalty.
```

**Penalty 5 — Expiry Risk:**
```
if DTE == 0: raw_score −= 10
  reason: "0-DTE expiry — gamma risk is extreme"
if DTE == 1 AND signal_hold_time_estimate > (15:30 − current_time):
  raw_score −= 5
  reason: "1-DTE signal may require overnight hold"
```

**Final Score:**

```
adjusted_score = clamp(raw_score − Σ(all penalties), 0, 100)
```

### Step 5: Signal Label Assignment

```
For LONG direction:
  adjusted_score >= 85: label = STRONG_BUY
  adjusted_score 70–84: label = BUY
  adjusted_score 50–69: label = WEAK_BUY (informational only — not executed)
  adjusted_score 35–49: label = NO_SIGNAL
  adjusted_score < 35:  label = DO_NOT_TRADE_LONG

For SHORT direction:
  adjusted_score >= 85: label = STRONG_SELL
  adjusted_score 70–84: label = SELL
  adjusted_score 50–69: label = WEAK_SELL (informational only — not executed)
  adjusted_score 35–49: label = NO_SIGNAL
  adjusted_score < 35:  label = DO_NOT_TRADE_SHORT
```

Only STRONG_BUY, BUY, STRONG_SELL, and SELL proceed to the Confidence Engine. All others are archived.

---

## Stage 3 — Confidence Engine

### Design Principle

Confidence is independent of Score. A high-scoring signal can have low confidence (insufficient historical data, regime mismatch, stale data). A moderately-scored signal can have high confidence (consistent historical accuracy, clean data, regime-aligned).

**Score = signal strength. Confidence = signal reliability.**

### The 9-Component Confidence Formula

```
Final_Confidence = clamp(
  Base_Confidence
  + Win_Rate_Adj
  + Regime_Alignment_Adj
  + Data_Quality_Adj
  + Sentiment_Provider_Adj
  + Momentum_Adj
  + Breakout_Adj
  + Loss_Streak_Adj
  + Historical_Accuracy_Adj
  , 0, 100)
```

### Component Formulas

**Base Confidence:**

```
Base_Confidence = min(60, adjusted_score × 0.60)

At score 70: Base = 42
At score 85: Base = 51
At score 100: Base = 60 (ceiling — score alone cannot give > 60% confidence)

Rationale: A perfect score still needs corroboration from historical accuracy,
           regime alignment, and data quality to reach high confidence.
```

**Win Rate Adjustment:**

```
Source: signal_performance_stats table, filtered by:
  regime = current_regime
  direction = signal_direction
  instrument_class = instrument_class (e.g., INDEX_OPTION, INDEX_FUTURE)
  lookback: last 90 calendar days, minimum 20 signals for statistical validity

historical_win_rate = winning_signals / total_signals for the filtered set

Win rate > 65%: +10
Win rate 55–65%: +5
Win rate 45–55%: 0
Win rate < 45%: −8
Insufficient data (< 20 signals in filter): 0
```

**Regime Alignment Adjustment:**

```
Compare signal_direction to regime.direction_layer (BULLISH / BEARISH / NEUTRAL):

signal_direction == LONG AND direction_layer == BULLISH: +8
signal_direction == SHORT AND direction_layer == BEARISH: +8
signal_direction aligns with direction_layer neutral (SIDEWAYS regime): 0
signal_direction == LONG AND direction_layer == BEARISH: −20
signal_direction == SHORT AND direction_layer == BULLISH: −20
HIGH_VOLATILITY or LOW_VOLATILITY regime (no clear direction): 0 (neither bonus nor penalty)

Note: −20 makes counter-regime trades nearly impossible to execute unless
      score is exceptionally high (>= 85) and historical accuracy compensates.
```

**Data Quality Adjustment:**

```
For each scoring component i:
  if data_freshness_seconds_i 120–300 (2–5 min old): −5
  if data_freshness_seconds_i > 300 (> 5 min old): −10

Maximum deduction: −20 (applied even if 3+ components are stale)

Special case: NSE OI feed is structurally delayed 3–5 minutes.
  OI component staleness up to 5 minutes is NOT penalized.
  OI staleness > 5 minutes beyond the expected 3–5 min delay IS penalized.

If option chain data unavailable entirely: −15 (major signal quality loss)
```

**Sentiment Provider Adjustment:**

```
Provider used for this signal's sentiment computation:
  OpenAI (gpt-4o-mini): 0
  AnthropicProvider (claude-haiku-4-5): 0
  GeminiProvider: 0
  OllamaProvider (local model): −3
  NeutralSentimentProvider (fallback): −5

Reasoning: NeutralSentimentProvider returns NEUTRAL regardless of context.
It contributes no signal intelligence and is a known quality degradation.
```

**Momentum Adjustment:**

```
Derived from supporting Momentum component:
  Momentum confirms signal direction: +5
  Momentum neutral (no clear reading): 0
  Momentum diverges from signal direction: −5

Divergence = price making higher high but RSI making lower high (bearish divergence, penalizes LONG)
             OR price making lower low but RSI making higher low (bullish divergence, penalizes SHORT)
```

**Breakout Adjustment:**

```
Derived from supporting Breakout component:
  Confirmed breakout (breach + 2× volume + close beyond level): +5
  Retest-and-hold after confirmed breakout: +5 (additive)
  Breakout attempt without 2× volume: −8 (false breakout risk is 60–70%)
  No breakout context: 0
```

**Loss Streak Adjustment:**

```
consecutive_losses = count of consecutive losing signals for this specific instrument
in the last 5 trading days (rolling, not calendar week)

adj = max(−15, −3 × consecutive_losses)

Examples:
  0 consecutive losses: 0
  1 loss: −3
  2 losses: −6
  3 losses: −9
  4 losses: −12
  5+ losses: −15 (floor)

This penalizes persistence in failing strategies per instrument,
not the system overall. Other instruments are unaffected.
```

**Historical Accuracy Adjustment:**

```
This is the most nuanced component. It uses the signal fingerprint
to look up historical accuracy of this specific signal pattern.

Signal fingerprint components (must match for lookup):
  1. primary_regime (5 possible values)
  2. score_bucket (STRONG/STANDARD — maps to 85+/70–84)
  3. signal_direction (LONG or SHORT)
  4. top_2_components (sorted by effective contribution — identity of top 2 contributors)
  5. vix_bucket (<14, 14–18, 18–22, >22)

Fingerprint = SHA-256(canonical_json(above_5_fields))

Lookup: signal_performance_stats WHERE fingerprint = ? ORDER BY evaluated_at DESC

accuracy = wins / total WHERE total >= minimum_samples

Adjustment scale:
  accuracy > 70% AND samples >= 30: +8
  accuracy > 70% AND samples 10–29: +4 (less statistical weight)
  accuracy 60–70% AND samples >= 30: +4
  accuracy 60–70% AND samples 10–29: +2
  accuracy 50–60%: 0 (slightly better than coin flip, no adjustment)
  accuracy < 50% AND samples >= 30: −6 (this pattern historically loses)
  accuracy < 50% AND samples 10–29: −3
  samples < 10: 0 (no adjustment — insufficient history)
```

### Confidence Ceiling by Score Band

Even with perfect components, confidence is bounded by signal score:

| Score Band | Maximum Achievable Confidence |
|-----------|------------------------------|
| 85–100 | 100 (uncapped) |
| 70–84 | 92 |
| < 70 | This signal does not reach Confidence Engine (filtered at Score Engine) |

### Confidence Calibration

Theoretical confidence must match empirical win rate. Weekly calibration process:

```
Calibration Check (run every Sunday at 05:00 IST):
  Bucket signals by confidence decile: [65–69, 70–74, 75–79, 80–84, 85–89, 90–100]
  For each bucket:
    predicted_win_rate = midpoint of bucket (e.g., bucket 70–74 → 72%)
    actual_win_rate = wins / total for signals in this bucket (last 90 days)
    calibration_error = abs(predicted_win_rate − actual_win_rate)
  
  If calibration_error > 10% for any bucket:
    Apply calibration multiplier to that bucket's output:
    calibration_factor = actual_win_rate / predicted_win_rate
    calibrated_confidence = raw_confidence × calibration_factor
  
  Calibration factors are stored in config, updated weekly.
  Calibration events are logged in the audit trail.
```

### Confidence Thresholds and Execution Rules

| Confidence | Label | Execution Rule | Position Size Modifier |
|-----------|-------|---------------|----------------------|
| >= 80 | VERY HIGH | Auto-execute | 100% |
| 65–79 | HIGH | Auto-execute | 100% |
| 50–64 | MODERATE | Auto-execute at reduced size | 75% |
| 35–49 | LOW | Skip or require manual confirmation | 50% (if manual override) |
| < 35 | VERY LOW | Never execute | — |

**Execution gate (non-negotiable):**  
`adjusted_score >= 70 AND final_confidence >= 65`

Both conditions must be true. A 90-point score with 60% confidence: **not executed**.  
A 72-point score with 80% confidence: executed (if Risk Engine also approves).

---

## Stage 4 — Risk Engine Interface

The Confidence Engine hands off a `SignalApprovalRequest` to the Risk Engine (see Doc 17 for the full 15-check pre-trade validation). This stage defines what the Signal Engine sends and what it accepts back.

### Signal Approval Request

```
SignalApprovalRequest:
  signal_id:              UUID
  fingerprint:            SHA-256 hash
  instrument:             e.g., "BANKNIFTY"
  instrument_type:        INDEX_FUTURE | INDEX_OPTION | STOCK_FUTURE | STOCK_OPTION
  direction:              LONG | SHORT
  adjusted_score:         int (0–100)
  final_confidence:       int (0–100)
  signal_label:           STRONG_BUY | BUY | STRONG_SELL | SELL
  
  suggested_entry_price:  Decimal (current market price at signal time)
  suggested_stop_loss:    Decimal (ATR-based, computed by PositionSizer)
  suggested_target_1:     Decimal (1:1 R:R from entry)
  suggested_target_2:     Decimal (1:2 R:R from entry)
  suggested_lots:         int (from ATR sizing + Kelly fraction)
  capital_at_risk:        Decimal (in INR)
  risk_reward_ratio:      float
  
  option_details:         (if instrument_type is OPTION)
    strike:               int
    option_type:          CE | PE
    expiry_date:          date
    dte:                  int
    
  regime_at_signal_time:  RegimeState (full regime snapshot)
  weight_config_hash:     SHA-256 of weights.yaml used for this signal
  generated_at:           datetime
  valid_until:            datetime (min of generated_at + 30min, 15:15 IST)
```

### Risk Engine Response

```
APPROVED:
  approved_lots: int (may equal or be less than suggested)
  risk_check_results: list of all 15 checks (all passed)
  approved_at: datetime
  → Signal proceeds to OMS

SIZE_MODIFIED:
  approved_lots: int (reduced by Risk Engine)
  reduction_reason: str (e.g., "net delta limit reached — reducing to maintain delta neutrality")
  risk_check_results: checks passed, one triggered size reduction
  → Signal proceeds to OMS at modified size

REJECTED:
  rejection_reason: str
  rejection_check_id: int (which of the 15 checks triggered)
  → Signal archived with status RISK_REJECTED, not forwarded to OMS
```

---

## Stage 5 — Recommendation

### Signal TTL Enforcement

Before recommendation is finalized:

```
current_time = IST now
market_close_gate = today 15:15:00 IST
ttl_expiry = generated_at + timedelta(minutes=30)
valid_until = min(ttl_expiry, market_close_gate)

if current_time >= valid_until:
  signal status = EXPIRED
  → archived, not forwarded to OMS, not displayed as actionable
  
if current_time < valid_until AND current_time < 09:15:
  signal status = PRE_MARKET (held until market open)
```

### Signal Deduplication

Before assembling the recommendation:

```
Redis deduplication check:
  key = "signal:dedup:{instrument}:{direction}:{weight_config_hash}"
  TTL = 30 minutes

If key exists in Redis:
  → signal labeled DEDUPLICATED
  → archived, not forwarded
  → dedup event logged

If key does not exist:
  → SET key with 30-minute TTL
  → proceed to recommendation assembly
```

Deduplication prevents signal flooding when market conditions create repeated identical signal patterns. The weight config hash ensures that if weights change, deduplication is not falsely triggered.

### Recommendation Object

```
Recommendation:
  ┌─ Identity ─────────────────────────────────────────────────────────────────┐
  │ signal_id:            UUID                                                  │
  │ fingerprint:          SHA-256                                               │
  │ instrument:           "BANKNIFTY"                                           │
  │ recommendation:       STRONG_BUY | BUY | STRONG_SELL | SELL                │
  │ direction:            LONG | SHORT                                          │
  │ score:                78                                                    │
  │ confidence:           71                                                    │
  ├─ Execution ────────────────────────────────────────────────────────────────┤
  │ entry_zone_low:       Decimal (current_price × 0.999)                      │
  │ entry_zone_high:      Decimal (current_price × 1.001)                      │
  │ stop_loss:            Decimal (entry − 1.5 × ATR for LONG)                 │
  │ target_1:             Decimal (entry + 1.0 × (entry − stop_loss))          │
  │ target_2:             Decimal (entry + 2.0 × (entry − stop_loss))          │
  │ risk_reward_ratio:    float (e.g., 1.3)                                    │
  │ approved_lots:        int                                                   │
  │ max_capital_at_risk:  Decimal (INR)                                        │
  ├─ Timing ───────────────────────────────────────────────────────────────────┤
  │ generated_at:         datetime                                              │
  │ valid_until:          datetime (min of +30min, 15:15)                      │
  │ dte:                  int                                                   │
  │ expiry_date:          date                                                  │
  ├─ Context ──────────────────────────────────────────────────────────────────┤
  │ regime:               TRENDING_BULLISH                                      │
  │ regime_confidence:    74                                                    │
  │ regime_duration_bars: 8                                                     │
  │ weight_config_version: "v1.2.3"                                             │
  │ weight_config_hash:   SHA-256                                               │
  ├─ Score Breakdown ──────────────────────────────────────────────────────────┤
  │ oi_build_up:          21.5 / 25  [LONG]                                    │
  │ trend_following:      16.8 / 20  [LONG]                                    │
  │ option_chain:         13.2 / 20  [LONG]                                    │
  │ volume_analysis:       9.5 / 15  [LONG]                                    │
  │ vwap:                  7.3 / 10  [LONG]                                    │
  │ sentiment:             4.0 / 5   [LONG]                                    │
  │ iv_analysis:           2.1 / 5   [NEUTRAL]                                 │
  │ penalties:            −8 (direction_conviction: 52%)                       │
  │ raw_score:             86  →  adjusted_score: 78                           │
  ├─ Confidence Breakdown ─────────────────────────────────────────────────────┤
  │ base:                 +46.8 (78 × 0.60)                                    │
  │ win_rate_adj:         +5 (58% win rate, 34 signals in filter)              │
  │ regime_alignment:     +8 (LONG signal in BULLISH regime)                   │
  │ data_quality:          0 (all fresh)                                       │
  │ sentiment_provider:    0 (OpenAI)                                          │
  │ momentum_adj:         +5 (momentum confirms)                               │
  │ breakout_adj:          0 (no breakout context)                             │
  │ loss_streak_adj:       0 (no consecutive losses)                           │
  │ historical_accuracy:  +4 (62%, 34 samples)                                │
  │ raw: 68.8 → calibrated: 71                                                │
  ├─ Explanation ──────────────────────────────────────────────────────────────┤
  │ [see Explanation section below]                                            │
  ├─ Audit ─────────────────────────────────────────────────────────────────── │
  │ ai_provider:          "OpenAI (gpt-4o-mini)"                               │
  │ ai_sentiment_ms:      245                                                  │
  │ regime_eval_at:       10:30:00 IST                                         │
  │ score_computed_at:    10:32:43 IST                                         │
  │ risk_approved_at:     10:32:45 IST                                         │
  │ ai_restricted_from:   ["OMS", "RiskEngine", "PositionSizer", "KillSwitch"] │
  └────────────────────────────────────────────────────────────────────────────┘
```

---

## Signal Explanation System

Explanations are **deterministic, template-based, and filled entirely from computed indicator values**. No AI generates the trading explanation. AI sentiment is only referenced as a data point, never as a reasoning authority.

### Explanation Structure (5 Sections)

**Section 1 — Signal Summary (always present):**

```
Template:
"{instrument} {direction} · Score {score}/100 · Confidence {confidence}% · {recommendation_label}
Entry: {entry_zone_low}–{entry_zone_high} · Stop: {stop_loss} · Target: {target_1} (T2: {target_2})
R:R {rr_ratio} · Lots: {lots} · Valid until {valid_until}"
```

**Section 2 — Primary Driver (highest effective contribution component):**

Per component templates:

*OI Build-up primary:*
```
"PRIMARY — OI Build-up ({score}/25):
{quadrant} confirmed. Open Interest changed {oi_change_pct}% while price moved {price_change_pct}%.
Pattern: {quadrant_label}. PCR at {pcr} ({pcr_interpretation}).
FII futures: {fii_net} contracts {fii_direction}."
```

*Trend Following primary:*
```
"PRIMARY — Trend ({score}/20):
ADX at {adx} — {trend_strength_label}. DI{plus_minus} leading by {di_spread} points.
EMA alignment on 1H: {ema_alignment_description}.
Supertrend {supertrend_status} on 15-min. MTF: {mtf_count}/4 timeframes aligned."
```

*Option Chain primary:*
```
"PRIMARY — Option Chain ({score}/20):
IV Percentile {iv_pct}% ({iv_context}). IV Rank {ivr}%.
Skew: {skew_description}. GEX: {gex_interpretation}.
Nearest OI wall at {wall_strike} — {wall_distance_pct}% from current price."
```

*Volume primary:*
```
"PRIMARY — Volume ({score}/15):
Current volume {volume_ratio}× 20-bar average — {volume_interpretation}.
{divergence_text}. OBV {obv_trend}. Cumulative delta: {delta_direction}.
VPOC at {vpoc_level}: price {vpoc_relation}."
```

*VWAP primary:*
```
"PRIMARY — VWAP ({score}/10) [{mode_label}]:
{mode_description}. Price {deviation_description}.
{touch_count_text if Mode A}. {bounce_text if Mode B}."
```

**Section 3 — Supporting Evidence (2nd and 3rd ranked contributors):**

Same templates as above, but abbreviated to one line per component using the `key_finding` field from ComponentOutput.

**Section 4 — Regime Context:**

```
Template:
"Regime: {primary_regime} (confidence {regime_confidence}%, active {regime_duration_bars} bars / ~{regime_duration_minutes} min).
{regime_alignment_text}.
{volatility_layer_text}.
Weight adjustments: {top_2_regime_adjustments_summary}."
```

*Alignment texts:*
- Aligned: `"Signal direction ALIGNS with regime — weight multipliers applied in full."`
- Opposed: `"COUNTER-REGIME TRADE — {−20} confidence penalty applied. Requires exceptional score to execute."`
- Neutral: `"Regime does not enforce a directional bias at this time."`

**Section 5 — Risk Factors:**

```
Template:
"Risk Factors:
· India VIX: {vix_level} ({vix_label}) — {vix_risk_text}
· Nearest OI wall: {wall_level} ({wall_direction}), {wall_distance_pct}% away
· DTE: {dte} days{dte_risk_text}
· {event_risk_text if any scheduled event within 3 days}
· {loss_streak_text if consecutive losses > 2}
· {data_staleness_text if any component stale}"
```

*Event risk texts (automatic calendar lookup):*
- RBI within 3 days: `"RBI Monetary Policy in {days} days — confidence reduced, binary event risk."`
- Budget within 7 days: `"Union Budget approaching — elevated volatility. Maximum confidence penalty applied."`
- FOMC within 1 day: `"FOMC tonight (8:30 PM IST) — potential gap risk tomorrow open."`

---

## Signal Lifecycle and State Machine

```
GENERATED
  ↓
DEDUP_CHECK ──→ DEDUPLICATED (archived, not forwarded)
  ↓
SCORE_CHECK ──→ LOW_SCORE (score < 70, archived as NO_SIGNAL)
  ↓
CONFIDENCE_CHECK ──→ LOW_CONFIDENCE (confidence < 65, archived)
  ↓
TTL_CHECK ──→ EXPIRED (valid_until has passed)
  ↓
RISK_PENDING ──→ RISK_REJECTED (reason stored)
  ↓         └──→ RISK_SIZE_MODIFIED
RISK_APPROVED
  ↓
OMS_PENDING
  ↓
SENT_TO_BROKER
  ↓
OPEN (position live, being tracked)
  ├──→ STOP_HIT → CLOSED_LOSS → outcome recorded → performance stats updated
  ├──→ TARGET_1_HIT → PARTIAL_CLOSE or TRAILING_STOP_ACTIVATED
  ├──→ TARGET_2_HIT → CLOSED_WIN → outcome recorded → performance stats updated
  └──→ TIME_EXIT (EOD or DTE deadline) → CLOSED_TIME → outcome recorded
```

Every state transition is:
- Appended to `signal_events` table (append-only, no updates or deletes)
- Published to the event bus (for monitoring dashboards)
- Never deleted (SEBI 2-year retention requirement)

---

## Historical Accuracy System

### Signal Outcome Recording

When a position closes, the following data is written to `signal_performance_stats`:

```
signal_performance_record:
  fingerprint:           SHA-256 (same as signal)
  instrument:            str
  direction:             LONG | SHORT
  regime_at_signal:      str
  score_bucket:          STRONG | STANDARD
  vix_bucket:            str
  top_2_components:      list[str]
  
  outcome:               WIN | LOSS | TIME_EXIT
  entry_price:           Decimal
  exit_price:            Decimal
  pnl_bps:               int (basis points, currency-independent)
  hold_duration_minutes: int
  dte_at_signal:         int
  
  score:                 int
  confidence:            int
  confidence_calibration_error: float (confidence − actual win probability)
  
  recorded_at:           datetime
```

### Performance Analytics Computed from Historical Data

**Rolling win rate:** Recalculated every 60 minutes for the active session.

**Score-to-PnL Curve:** Weekly computation. Groups signals by score decile and computes median PnL per lot. Expected shape: monotonically increasing. Non-monotonic curve is an alert.

**Component Attribution:** For winning signals, which components were strongest? For losing signals, which components misled? Identifies components needing recalibration.

**Regime-conditional accuracy:**

| Regime | Expected Win Rate | Actual Win Rate | Action if Below |
|--------|------------------|----------------|----------------|
| TRENDING_BULLISH | >= 58% | Monitor weekly | Reduce trend multiplier |
| TRENDING_BEARISH | >= 55% | Monitor weekly | Same |
| SIDEWAYS | >= 52% | Monitor weekly | Reduce strategy diversity |
| HIGH_VOLATILITY | >= 45% | Accept lower — high risk | Raise minimum score to 80 |
| LOW_VOLATILITY | >= 50% | Monitor weekly | Standard |

**Confidence Calibration Table (example output):**

| Confidence Band | Predicted Win Rate | Actual Win Rate | Calibration Error | Factor Applied |
|----------------|-------------------|----------------|------------------|---------------|
| 65–74 | 70% | 63% | −7% | ×0.90 |
| 75–84 | 80% | 75% | −5% | ×0.94 |
| 85–94 | 90% | 82% | −8% | ×0.91 |
| 95–100 | 97% | 88% | −9% | ×0.91 |

If all bands show systematic overconfidence, the Base_Confidence formula coefficient (currently 0.60) is reduced. This recalibration requires human review before application.

---

## Signal Thresholds — Master Reference

### Score Thresholds

| Score | Label | Executable | Position Size |
|-------|-------|-----------|--------------|
| >= 85 | STRONG_BUY / STRONG_SELL | Yes (with confidence >= 65) | 100% |
| 70–84 | BUY / SELL | Yes (with confidence >= 65) | 100% |
| 50–69 | WEAK_BUY / WEAK_SELL | No — informational only | — |
| 35–49 | NO_SIGNAL | No | — |
| < 35 | DO_NOT_TRADE | No | — |

### Confidence Thresholds

| Confidence | Label | Action |
|-----------|-------|--------|
| >= 80 | VERY HIGH | Execute at full approved size |
| 65–79 | HIGH | Execute at full approved size |
| 50–64 | MODERATE | Execute at 75% of approved size |
| 35–49 | LOW | Do not execute (or manual confirmation only) |
| < 35 | VERY LOW | Do not execute |

### Execution Gate

Both conditions required simultaneously:

```
EXECUTE if: adjusted_score >= 70 AND final_confidence >= 65
           AND Risk Engine APPROVED
           AND current_time < valid_until
           AND kill_switch == OFF
```

### Confidence Range: Minimum and Maximum

```
Maximum Achievable Confidence (best case):
  Base:               +60 (score 100)
  Win rate:           +10
  Regime:             +8
  Data quality:        0
  Sentiment provider:  0
  Momentum:           +5
  Breakout:           +5
  Loss streak:         0
  Historical accuracy: +8
  MAXIMUM THEORETICAL: 96

Minimum Achievable Confidence (worst case — still positive):
  Base:               +42 (score 70, the minimum to reach confidence engine)
  Win rate:            −8 (< 45% historical win rate)
  Regime:             −20 (counter-regime trade)
  Data quality:       −20 (two stale components)
  Sentiment provider:  −5 (fallback)
  Momentum:            −5 (divergence)
  Breakout:            −8 (false breakout)
  Loss streak:        −15 (5 consecutive losses)
  Historical accuracy:  −6 (< 50% accuracy, 30+ samples)
  RAW: 42 − 87 = −45 → clamped to 0

Consequence: a signal with score 70 that hits every negative condition
gets confidence = 0 and is never executed. The gate is correctly rejecting it.
```

---

## Edge Cases and Override Rules

### Counter-Regime Signals

A signal that opposes the regime (e.g., LONG in TRENDING_BEARISH) faces:
- Score penalty: −15
- Confidence penalty: −20
- Total effective hurdle: need raw_score >= 105 to produce adjusted_score >= 90 (impossible)
- Unless score is 85+ before penalties AND historical accuracy is exceptional

These signals are not blocked by a hard gate — they are blocked by making the math nearly impossible to pass. This preserves the ability to trade exceptional counter-regime setups (e.g., a confirmed reversal) while penalizing casual counter-trend trades.

### Zero-Score Components

If a component returns 0 (e.g., Trend Following when ADX < 20), this is not treated as missing data. It is a legitimate signal that the trend component has nothing to say. Other components are unaffected.

### All-Neutral Outcome

If all 7 components return NEUTRAL direction, Direction Vote produces no winner. Signal is archived with status DIRECTION_UNDECIDED. No score computation. This is expected in extremely low-volatility, directionless markets.

### Conflicting IV and Regime

In HIGH_VOLATILITY regime, IV Percentile is often > 70% (options expensive). This makes the IV Analysis component suggest SHORT_VOL, while the regime makes directional trades dangerous. Both signals are correct for different trade types — the regime multiplier shifts the weight to reflect this, and the recommendation must specify the trade type (directional vs volatility trade) in the explanation.

### Pre-Market Signal Generation

Signals may be generated from 08:00 IST using pre-market data (SGX/Gift Nifty, US futures). These signals:
- Are labeled PRE_MARKET in status
- Have TTL starting from 09:15 IST (market open), not from generation time
- Carry lower base confidence: −10 applied (pre-market data is less reliable)
- Are refreshed at 09:15 IST — if indicators change materially at open, signal is regenerated

---

## Audit and Reproducibility

Every signal record in the database must be fully reproducible. Given the `signal_id`, it must be possible to reconstruct the exact score and confidence by re-running the engine with the stored inputs. This requires:

1. **Weight config hash:** The SHA-256 of the exact `scoring_weights.yaml` used. If weights are updated, signals generated before the update use the old weights for their audit trail.

2. **Input snapshot:** All indicator values at signal generation time (ADX, EMA stack, OI values, PCR, VIX, etc.) are stored in the `signals` table as a JSONB column.

3. **Regime snapshot:** The full `RegimeState` object at signal time is stored.

4. **AI provider response:** The raw AI sentiment response (text + label) is stored. The AI response can vary between calls (non-deterministic), so the actual response used is archived.

5. **Penalty log:** Every penalty applied (type, value, reason) is stored in the audit JSONB.

6. **Confidence breakdown:** All 9 confidence components with their individual values are stored.

**Reproducibility test (weekly):** Pick 10 random historical signals. Re-run the score engine with the stored inputs. If output score differs by > 2 points from stored score: there is a computation bug or a data mutation issue. Alert immediately.

---

## Signal Engine → Event Bus Integration

| Event | Trigger | Stream | Consumers |
|-------|---------|--------|-----------|
| `signal.generated` | Any signal produced (including NO_SIGNAL) | signals.generated | Dashboard, Audit DB |
| `signal.scored` | Score computation complete (score >= 50) | signals.scored | Dashboard |
| `signal.risk.pending` | Signal passed score + confidence gate, sent to Risk Engine | signals.pending | Risk Engine |
| `signal.risk.approved` | Risk Engine approved | signal.risk.approved | OMS (sole consumer) |
| `signal.risk.rejected` | Risk Engine rejected | signals.rejected | Dashboard, Audit DB |
| `signal.expired` | TTL elapsed before execution | signals.expired | Dashboard |
| `signal.deduplicated` | Dedup check suppressed a signal | signals.deduplicated | Monitoring |
| `signal.outcome.recorded` | Position closed, outcome written | signal.outcomes | Performance Analytics |

---

*Cross-references: Doc 17 (Risk Engine — 15 pre-trade checks) · Doc 19 (Strategy Framework — component definitions) · Doc 20 (Market Regime Engine — regime multipliers) · Doc 16 (Signal Scoring Engine — weight config and architecture)*  
*No code in this document. Implementation in application/services/signal_engine.*
