# 16 — Signal Scoring Engine

## Purpose

Define the complete architecture for converting multi-strategy evaluations into a final, explainable, regime-aware signal with a score, confidence, direction, and actionable FnO instrument recommendation. This document covers the scoring model, weight management, regime-conditional weighting, multi-timeframe alignment, signal deduplication, TTL, confidence engine, and the full signal state lifecycle.

> **⚠ AUTHORITATIVE WEIGHT SYSTEM:** The V1 weight system is defined in `docs/19_STRATEGY_FRAMEWORK.md` and `docs/21_SIGNAL_ENGINE.md`. Those documents supersede the weight tables in this document. The weights and confidence formula in this document have been updated to match. Any prior version of this document showing PRICE_ACTION=15, REGIME=10 as separate score components, or Sentiment=10/IV=10, is **deprecated**. See the audit note at the end of this document.

---

## Architectural Position

```
StrategyEvaluator ──► [ScoringEngine] ──► ConfidenceEngine ──► RiskEngine ──► OMS
                             ▲
             ┌───────────────┼───────────────────┐
             │               │                   │
      RegimeEngine    SentimentCache      HistoricalAccuracy
                                          (StrategyPerformanceRepo)
```

The ScoringEngine is a pure functional component: given strategy scores, a regime, a cached sentiment score, and a weight configuration, it produces a `ScoredSignal`. Its only side effects are writing to the database and the event bus.

---

## Score Component Contracts

Each component that contributes to the final signal score implements `IScoreComponent`.

```
IScoreComponent:
    component_name:   str    (unique key in score breakdown JSONB)
    max_contribution: int    (maximum points this component can contribute)
    evaluate(context: ScoreContext) -> ComponentScore
```

```
ComponentScore:
    component_name:     str
    raw_score:          float    (0.0 to 1.0, normalized internal score)
    contribution:       float    (raw_score × effective_weight)
    weight_used:        float    (actual weight applied; regime-adjusted)
    base_weight:        float    (default weight from configuration)
    signals:            list[str]  (evidence strings, e.g., "RSI=72, above 70 threshold")
    is_available:       bool     (False if data was missing; contribution = 0)
    data_freshness_ms:  int      (age of the data used, for latency monitoring)
```

```
ScoreContext:
    symbol:           str
    direction:        SignalDirection    (BULLISH, BEARISH)
    timeframes:       dict[Timeframe, FeatureSet]
    regime:           MarketRegime
    sentiment_result: SentimentResult | None
    option_chain:     OptionChainSnapshot | None
    timestamp:        datetime
```

---

## Score Components

### Trend Score (TrendScoreComponent)

Measures directional momentum across multiple timeframes.

**Inputs:**
- EMA alignment (EMA9 > EMA21 > EMA50 for bullish)
- MACD histogram direction and magnitude
- ADX (trend strength; ADX < 20 penalizes score even if direction is correct)
- SuperTrend direction
- Price position relative to VWAP

**Multi-timeframe alignment bonus:**
- 15m + 1h + Daily all agree: full score
- 2 of 3 agree: 70% of score
- Only 1 agrees: 30% of score

### Volume Score (VolumeScoreComponent)

Confirms the move with participation.

**Inputs:**
- Relative Volume vs 20-day average (> 2× → high contribution)
- Volume spike on breakout candle
- Delivery percentage (for equity swing, Phase 2)
- Buy vs sell volume imbalance from market depth

### OI Score (OIScoreComponent)

Open Interest build-up is a primary signal for FnO direction.

**Inputs:**
- OI change in the direction of the call: Put OI addition + Call OI unwinding = bullish
- PCR (Put-Call Ratio): PCR > 1.2 is generally bullish for underlying
- Max Pain distance: price moving away from Max Pain in the signal direction adds score
- OI concentration at strikes near current price
- Change in OI at ATM strike vs OTM strikes

This component has zero contribution for Phase 2 equity swing trading (non-FnO).

### IV Score (IVScoreComponent)

Implied Volatility conditions affect option premium quality and strategy selection.

**Inputs:**
- IV Rank (current IV vs 52-week range)
- IV Percentile
- IV skew: Call IV vs Put IV differential
- IV term structure: near vs far-expiry IV

**Scoring logic:**
- IV Rank < 30: high score for option buying strategies
- IV Rank > 70: low score for buying; high score for selling strategies
- The engine must know whether the contemplated position is net long or short options

### Price Action Score (PriceActionScoreComponent)

Structure of price relative to key levels.

**Inputs:**
- Distance from support/resistance
- Recent candle patterns (engulfing, pin bar, inside bar on high volume)
- Breakout from consolidation (ATR-normalized range break)
- Risk-reward ratio: `(target - entry) / (entry - stop_loss)`

**Scoring logic:**
- R:R < 1.5: score = 0 regardless of all other factors
- R:R 1.5–2.0: score capped at 50%
- R:R 2.0–3.0: full score
- R:R > 3.0: score multiplier 1.1 (bonus)

### Sentiment Score (SentimentScoreComponent)

Market narrative context from asynchronous news analysis.

**Inputs:**
- Latest cached `SentimentResult` for the symbol
- Age of the sentiment result (freshness penalty beyond 4 hours)

If `SentimentResult.is_fallback == True`:
- Contribution = 0
- Signal's `confidence_degraded = True` flag is set

### Regime Score (RegimeScoreComponent)

Alignment between signal direction and current market regime.

| Signal Direction | Regime | Contribution |
|---|---|---|
| BULLISH | TRENDING_BULLISH | 100% of regime weight |
| BULLISH | SIDEWAYS | 40% |
| BULLISH | TRENDING_BEARISH | 0% + sets `regime_mismatch = True` |
| BULLISH | HIGH_VOLATILITY | 60% |
| BULLISH | LOW_VOLATILITY | 70% |
| BEARISH | TRENDING_BEARISH | 100% |
| BEARISH | SIDEWAYS | 40% |
| BEARISH | TRENDING_BULLISH | 0% + sets `regime_mismatch = True` |

If `regime_mismatch == True`: the signal is automatically downgraded by the ConfidenceEngine regardless of total score.

---

## Weight Model

### Base Weights — V1 Authoritative (FnO)

These weights are defined in `docs/19_STRATEGY_FRAMEWORK.md` and mirrored here for reference. The `config/scoring_weights.yaml` file is the runtime source. Regime is **not** a score component — it is a **multiplier** applied to each component's weight (see `docs/20_MARKET_REGIME_ENGINE.md`).

```
OI_BUILDUP:     25    ← primary FnO signal
TREND:          20
OPTION_CHAIN:   20    ← replaces old PRICE_ACTION
VOLUME:         15
VWAP:           10    ← new in V1; replaces regime-as-component
SENTIMENT:       5
IV_ANALYSIS:     5
Total:         100
```

### Regime-Conditional Weight Multipliers

Regime multipliers are stored in `config/scoring_weights.yaml`. They are applied to the base weights above, then renormalized to 100. They do **not** add new point buckets — they shift relative importance.

```yaml
weights:
  default:
    OI_BUILDUP:    25
    TREND:         20
    OPTION_CHAIN:  20
    VOLUME:        15
    VWAP:          10
    SENTIMENT:      5
    IV_ANALYSIS:    5

  regime_multipliers:
    TRENDING_BULLISH:
      OI_BUILDUP:    1.20
      TREND:         1.30
      OPTION_CHAIN:  1.00
      VOLUME:        1.10
      VWAP:          1.10
      SENTIMENT:     1.00
      IV_ANALYSIS:   0.70

    TRENDING_BEARISH:
      OI_BUILDUP:    1.20
      TREND:         1.30
      OPTION_CHAIN:  1.10
      VOLUME:        1.10
      VWAP:          1.10
      SENTIMENT:     1.20
      IV_ANALYSIS:   1.10

    SIDEWAYS:
      OI_BUILDUP:    1.00
      TREND:         0.25   # ADX gate makes trend near-useless
      OPTION_CHAIN:  1.40
      VOLUME:        1.00
      VWAP:          1.30   # mean-reversion mode
      SENTIMENT:     1.00
      IV_ANALYSIS:   1.40

    HIGH_VOLATILITY:
      OI_BUILDUP:    0.80
      TREND:         0.60
      OPTION_CHAIN:  1.25
      VOLUME:        1.00
      VWAP:          0.70
      SENTIMENT:     1.20
      IV_ANALYSIS:   1.60

    LOW_VOLATILITY:
      OI_BUILDUP:    0.90
      TREND:         0.70
      OPTION_CHAIN:  1.10
      VOLUME:        0.90
      VWAP:          0.80
      SENTIMENT:     1.00
      IV_ANALYSIS:   1.60
```

### Asset Class Weight Overrides

```yaml
  asset_class_overrides:
    FNO:
      # Uses default weights + regime_multipliers above

    EQUITY_SWING:
      TREND:         25
      OI_BUILDUP:     0   # No FnO OI data for equity
      OPTION_CHAIN:   0   # No options chain for equity
      VOLUME:        25
      VWAP:          15
      SENTIMENT:     20
      IV_ANALYSIS:    0
      PRICE_ACTION:  15   # Re-introduced for equity (support/resistance, patterns)

    EQUITY_LONGTERM:
      TREND:         15
      OI_BUILDUP:     0
      OPTION_CHAIN:   0
      VOLUME:        10
      VWAP:           5
      SENTIMENT:     20
      IV_ANALYSIS:    0
      PRICE_ACTION:  20
      FUNDAMENTAL:   30   # Added in Phase 3
```

### Weight Versioning

Every scoring run records the weight configuration version used. The version is a SHA-256 hash of the weights YAML content. This allows exact reconstruction of the scoring logic for any historical signal.

---

## Score Computation

```
For each component:
    effective_weight = regime_adjusted_weight (or asset_class_override if applicable)
    contribution = component.raw_score × effective_weight

If component.is_available == False:
    contribution = 0
    redistribute its weight proportionally to available components

Final Score = Σ contributions, normalized to [0, 100]
```

If data completeness < 60% (fewer than 60% of components had data): signal is ineligible for execution. The signal is generated with `state = REJECTED` and `rejection_reason = INSUFFICIENT_DATA`.

---

## Signal Deduplication

A signal is a duplicate if an existing ACTIVE signal matches on all of:
- `symbol`
- `direction`
- `weight_version`
- Created within the last `dedup_window_minutes` (configurable, default 30)

**On detecting a duplicate:**
1. The duplicate signal is not stored as a new record.
2. The existing signal's `last_refreshed_at` is updated.
3. The existing signal's score is updated if the new score differs by more than 5 points.
4. A `signal.refreshed` event is published (not a new signal event).

**Implementation:** Redis SET key with TTL for atomic deduplication:
```
Key:   signal:dedup:{symbol}:{direction}:{weight_version}
Value: existing_signal_id
TTL:   dedup_window_minutes × 60
```

---

## Signal TTL and Expiry

Every signal carries a `valid_until` timestamp. After this, the signal cannot be executed.

### TTL Calculation

```
For intraday FnO signals:
    valid_until = min(
        generated_at + signal_ttl_minutes (default 30),
        15:15 IST on the current trading day
    )

For swing/positional signals (Phase 2+):
    valid_until = generated_at + 3 trading_days
```

### Automatic Invalidation Triggers

A signal is invalidated before TTL expiry if:
1. The underlying price moves beyond `entry_price ± (1.5 × ATR)` from the signal's entry.
2. The market regime changes to an opposing regime (TRENDING_BEARISH for a BULLISH signal).
3. The signal's stop-loss level is breached by the underlying.

The `SignalExpiryWorker` polls open signals every 60 seconds, checks conditions against Redis LTP cache, and publishes `signal.expired` events for invalidated signals.

---

## Confidence Engine

Score measures signal quality. Confidence measures execution reliability. They are separate values.

### Confidence Inputs

The full 9-component confidence model is defined in `docs/21_SIGNAL_ENGINE.md` Stage 3. This section provides the canonical formula for implementation reference.

```
ConfidenceInput:
    adjusted_score:                    float    (0–100, post-penalty score)
    strategy_win_rate_30d:             float    (from signal_performance_stats)
    regime_direction_layer:            str      (BULLISH / BEARISH / NEUTRAL)
    signal_direction:                  str      (LONG / SHORT)
    data_freshness_per_component:      dict     (component_name → age_seconds)
    sentiment_provider:                str      (provider name or FALLBACK)
    momentum_confirmation:             str      (CONFIRMS / NEUTRAL / DIVERGES)
    breakout_confirmation:             str      (CONFIRMED / UNCONFIRMED / NONE)
    recent_consecutive_losses:         int      (rolling 5-trading-day window)
    fingerprint_accuracy:              float | None  (from signal_performance_stats)
    fingerprint_sample_count:          int      (0 if no history)
    last_signal_age_seconds:           int      (time since last signal for this instrument)
```

### Confidence Calculation — 9-Component Model

```
base_confidence         = min(60, adjusted_score × 0.60)

win_rate_adj:
    win_rate > 65%:     +10
    win_rate 55–65%:    +5
    win_rate 45–55%:    0
    win_rate < 45%:     -8
    samples < 20:       0  (insufficient data)

regime_alignment_adj:
    signal aligns with regime direction:     +8
    regime direction is NEUTRAL:             0
    signal contradicts regime direction:     -20

data_quality_adj:
    any component data 2–5 min old:    -5 per component
    any component data > 5 min old:    -10 per component  (max -20 total)
    (NSE OI structural 3–5 min delay is NOT penalized)

sentiment_provider_adj:
    OpenAI / Anthropic / Gemini:    0
    OllamaProvider:                 -3
    NeutralSentimentProvider:       -5

momentum_adj:
    CONFIRMS:   +5
    NEUTRAL:    0
    DIVERGES:   -5

breakout_adj:
    CONFIRMED (with 2× volume):    +5
    UNCONFIRMED (no volume gate):  -8
    NONE:                          0

loss_streak_adj     = max(-15, -3 × recent_consecutive_losses)

historical_accuracy_adj:
    accuracy > 70%, samples >= 30:    +8
    accuracy > 70%, samples 10–29:    +4
    accuracy 60–70%, samples >= 30:   +4
    accuracy 60–70%, samples 10–29:   +2
    accuracy < 50%, samples >= 30:    -6
    accuracy < 50%, samples 10–29:    -3
    samples < 10:                     0

raw_confidence  = sum of all 9 components above
confidence_pct  = clamp(raw_confidence, 0, 100)
```

Weekly calibration: if actual win rate per confidence bucket diverges from predicted by > 10%, apply a calibration multiplier (see `docs/21_SIGNAL_ENGINE.md` — Confidence Calibration).

### Confidence Thresholds

```yaml
signal:
  min_score_to_execute:      70    # Signals below this score are not sent to OMS
  min_confidence_to_execute: 65    # Both conditions must be true
  high_confidence_threshold: 80    # Full position size
  moderate_confidence_size:  75    # 65-79 confidence → 75% position size (not 50%)
```

Note: Signals with score 50–69 are generated as informational WEAK_BUY/WEAK_SELL but never forwarded to the OMS.

---

## Signal State Machine

The canonical signal state machine is defined in `docs/21_SIGNAL_ENGINE.md` and `docs/22_OMS_DESIGN.md`. This section mirrors the unified state model for reference.

```
GENERATED          — scoring pipeline has produced a signal
    ↓
DEDUPLICATED       — suppressed: identical active signal exists within dedup window (terminal)
    ↓
WEAK_SIGNAL        — score 50–69: informational only, not forwarded to OMS (terminal for execution)
    ↓
CONFIDENCE_FAILED  — confidence < 65: not forwarded to OMS (terminal)
    ↓
EXPIRED            — TTL elapsed or regime changed before OMS reached
    ↓
RISK_PENDING       — forwarded to Risk Engine for pre-trade checks
    ├──→ RISK_REJECTED   — failed one or more risk checks (terminal, reason recorded)
    └──→ RISK_APPROVED   — all 15 checks passed
             ↓
         OMS_PENDING     — queued in OMS, awaiting broker submission
             ↓
         SENT_TO_BROKER  — order submitted to exchange
             ↓
         OPEN            — broker confirmed order fill; position is live
             ├──→ STOP_HIT    — position closed at stop loss (LOSS outcome)
             ├──→ TARGET_HIT  — position closed at target (WIN outcome)
             ├──→ TIME_EXIT   — position closed at EOD / DTE deadline
             └──→ CANCELLED   — manually closed by operator or kill switch
```

Transitions not in this diagram raise `SignalStateError` and are logged at ERROR level.  
All state transitions are appended to `signal_events` hypertable (append-only, no deletes).

---

## Signal Output Schema

```
Signal:
    signal_id:              UUID
    symbol:                 str
    exchange:               Exchange
    segment:                Segment
    direction:              SignalDirection    (BULLISH, BEARISH)
    signal_type:            SignalType

    score:                  float             (0–100)
    confidence_pct:         float             (0–100)
    weight_version:         str
    data_completeness:      float

    score_breakdown:        JSONB             (component → ComponentScore)
    confidence_breakdown:   JSONB             (factor → contribution)

    underlying_entry:       Decimal
    underlying_stop:        Decimal
    underlying_targets:     list[Decimal]     (T1, T2, T3)
    risk_reward:            Decimal

    recommended_instrument: str | None        (populated by StrikeSelector)
    recommended_quantity:   int | None        (populated by PositionSizer)
    recommended_expiry:     date | None

    regime:                 MarketRegime
    regime_mismatch:        bool
    sentiment_is_fallback:  bool
    confidence_degraded:    bool

    valid_until:            datetime
    generated_at:           datetime
    strategy_ids:           list[str]

    state:                  SignalState
    rejection_reason:       str | None
    state_history:          JSONB             (array of state transitions with timestamps)
```

---

## Strike Selector (FnO Only)

The StrikeSelector is invoked after a signal passes the confidence threshold and before RiskEngine evaluation.

### Selection Methodology

```
1. Direction → instrument type:
   BULLISH  → BUY CE (default) or SELL PE (if IV Rank > 70)
   BEARISH  → BUY PE (default) or SELL CE (if IV Rank > 70)

2. Expiry selection:
   If signal confidence >= 80: nearest liquid expiry (DTE >= 7)
   If confidence 65–80: next monthly expiry (more time, lower theta risk)
   Always: DTE >= 3 (avoid expiry-day gamma risk)

3. Strike selection:
   If score >= 80: ATM or 1 strike OTM
   If score 60–80: 1–2 strikes OTM (better risk-reward via premium)
   Constraint: selected strike must have OI >= 500 lots
   Constraint: bid-ask spread < 1% of option premium

4. Validation:
   Instrument exists and is_active in InstrumentMaster
   Current IV Rank within acceptable range for the position type
   Sufficient market depth (top 5 levels non-empty)

5. Quantity:
   Computed by PositionSizer in RiskEngine (see 17_PORTFOLIO_RISK_ENGINE.md)
```

---

## Observability

| Metric | Type | Labels | Description |
|---|---|---|---|
| `signals_evaluated_total` | Counter | `symbol`, `direction`, `regime` | Signals entering scoring |
| `signals_generated_total` | Counter | `symbol`, `direction`, `regime` | Signals passing min_score |
| `signals_rejected_low_score_total` | Counter | `symbol` | Signals below min_score |
| `signals_rejected_low_confidence_total` | Counter | `symbol` | Signals below min_confidence |
| `signals_deduplicated_total` | Counter | `symbol` | Duplicate signals suppressed |
| `signal_score` | Histogram | `symbol`, `regime` | Distribution of scores |
| `signal_confidence_pct` | Histogram | `symbol`, `regime` | Distribution of confidence |
| `signal_data_completeness` | Histogram | | % of components with data |
| `scoring_engine_duration_seconds` | Histogram | | Time to compute full score |
