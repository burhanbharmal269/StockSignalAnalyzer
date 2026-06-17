# Signal Generation Trace — Phase 4

**Date**: 2026-06-16

---

## Runtime Trace Logs (Phase 4 Implementation)

All pipeline steps now emit structured logs via `signal_scanner.*` prefix.

### Trace 1 — Universe Load
```
signal_scanner.universe_loaded total=167 fo_stocks=142 scanning=20
```

### Trace 2 — Historical Candles (per symbol)
```
signal_scanner.features symbol=RELIANCE adx=22.3 vol_ratio=1.45 rsi=58.2 vwap_dev_sigma=0.81 ema20=2840.50 bb_pct=0.62
```

### Trace 3 — Regime Classification
```
signal_scanner.regime symbol=RELIANCE regime=TRENDING_BULLISH strategy=DIRECTIONAL
```

### Trace 4 — Signal Request Built
```
signal_scanner.signal_request symbol=RELIANCE token=738561 lot_size=250 entry=2845.50 stop=2791.25 target=2953.00 dte=14
```

### Trace 5 — Scoring Engine (ScoringEngineService)
```
scoring_engine.start instrument_token=738561 regime=TRENDING_BULLISH timeframe=15m
scoring_engine.component_unavailable component=OI_BUILDUP reason="no OI data"
scoring_engine.component_unavailable component=OPTION_CHAIN reason="no option chain"
scoring_engine.component_unavailable component=IV_ANALYSIS reason="no IV data"
scoring_engine.complete instrument_token=738561 direction=LONG conviction=0.85 raw_score=38.2 adjusted_score=30.4 is_eligible=True
```

### Trace 6 — Signal Engine Result
```
signal_scanner.engine_result symbol=RELIANCE accepted=True score=30.4 confidence=55.2 rejection=None duplicate=False
signal_scanner.SIGNAL_ACCEPTED symbol=RELIANCE regime=TRENDING_BULLISH strategy=DIRECTIONAL score=30.4 confidence=55.2 signal_id=uuid-xxx
```

---

## Pipeline Decision Points

```
Symbol → Candles (≥20 bars?) → Features OK? → Regime → Build Request
    ↓                                                         ↓
  Skip                                              ScoringEngine.calculate_score()
                                                        ↓
                                                Direction NEUTRAL? → SCORE_INELIGIBLE
                                                Completeness < 40%? → SCORE_INELIGIBLE
                                                        ↓
                                                ConfidenceEngine.calculate_confidence()
                                                        ↓
                                                Signal.submit_to_risk(min_score=20, min_confidence=25)
                                                Score < 20 OR confidence < 25? → WEAK_SIGNAL
                                                        ↓
                                                RiskEngineService.evaluate()
                                                Kill switch active? → KILL_SWITCH_ACTIVE
                                                Account state missing? → DATA_SOURCE_UNAVAILABLE
                                                Daily loss exceeded? → DAILY_LOSS_LIMIT
                                                        ↓
                                                risk_decision.approved = True
                                                        ↓
                                                Signal persisted → SignalRiskApproved event
                                                        ↓
                                                PipelineEventHandler → OMS → OrderRouter → Broker
```

---

## Rejection Reason Taxonomy

| Code | Meaning | Frequency After Fix |
|------|---------|---------------------|
| `SCORE_INELIGIBLE` | Direction=NEUTRAL or completeness<40% | Low (ADX gate lowered to 15) |
| `WEAK_SIGNAL` | Score<20 or confidence<25 | Low (thresholds lowered) |
| `DUPLICATE` | Same signal within 30-min TTL | Expected (normal dedup) |
| `EXPIRED` | Valid_until passed before processing | Rare |
| `KILL_SWITCH_ACTIVE` | Risk Engine check 1 failed | None (auto-deactivated paper mode) |
| `DATA_SOURCE_UNAVAILABLE` | account_state missing in Redis | None (seeded at startup) |
| `RISK_REJECTED` | Daily loss / drawdown / margin checks | Expected in real trading |

---

## Expected Signal Flow (Post-Fix)

For a stock with:
- ADX = 22 (above 15 gate, below 30)
- DI+ > DI- (bullish direction)
- Volume ratio = 1.5 (above average)
- VWAP deviation = +0.8 sigma (slightly above VWAP)
- RSI = 58 (in bullish range 45–75)

Expected output:
- TREND: LONG, score ≈ 11 (ADX 20-25 tier = 8 + DI spread + partial EMA + RSI gate)
- VOLUME: LONG, score ≈ 9 (tier 3: vol_ratio 1.0–1.5)
- VWAP: LONG, score ≈ 6 (mode B: above VWAP in trending regime)
- SENTIMENT: NEUTRAL (NeutralSentimentProvider, score = 2.5 each side)

Direction vote: LONG (25 votes) vs SHORT (0 votes) = conviction 1.0 → LONG ✅
Completeness: 4/7 = 57% ≥ 40% ✅
Raw score ≈ 40–45 → adjusted after penalties → ≥ 20 gate ✅
Confidence ≈ 45–55% ≥ 25 gate ✅
Risk: kill switch inactive ✅, account state seeded ✅
Result: **SIGNAL ACCEPTED → OrderManagementService**
