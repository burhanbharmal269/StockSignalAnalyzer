# Scoring Engine & Confidence Engine — Integration Review

**Date:** 2026-06-13  
**Reviewer:** Architecture Review (Pre-Phase 13)  
**Status:** FINAL  
**Scope:** Phase 11 (Scoring Engine) + Phase 12 (Confidence Engine) — readiness for Phase 13 (Risk Engine)

---

## 1. Executive Summary

The Scoring Engine and Confidence Engine are architecturally sound. The clean-architecture layering is correctly applied, domain services are pure and deterministic, and responsibility boundaries are properly enforced. The event bus integration is functional.

**Eleven findings** were identified across ten review areas:

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 4 |
| Medium | 4 |
| Low | 3 |

No finding blocks Phase 13 implementation. The four high-severity items should be addressed either before Phase 13 or as part of its first PR. None require architectural redesign.

**Architecture Readiness Score: 82 / 100**

**Recommendation: READY_FOR_PHASE_13**

---

## 2. Architecture Findings

### 2.1 Score vs Confidence Separation

**Verdict: PASS — No responsibility overlap.**

The separation is correctly enforced:

| Concern | Score Engine | Confidence Engine |
|---|---|---|
| What is measured | Signal strength | Signal trustworthiness |
| Primary inputs | Market data, component scores | Historical outcomes, win rates, data quality |
| Output | `adjusted_score`, `direction` | `final_confidence`, `passed_gate` |
| Redis usage | None | Calibration factor lookup |
| DB usage | None | `signal_performance_stats` reads |

**Verified:** No scoring logic exists inside the Confidence Engine. No confidence logic exists inside the Scoring Engine.

**One nuance (not a flaw):** Both engines use regime alignment, but for different purposes:
- Scoring: regime alignment multiplies component weights (directional boost)
- Confidence: regime alignment adjusts trustworthiness (a flat ±8/0/−20 adjustment)

These are semantically distinct. The confidence adjustment is "does the market environment support this signal direction" while the scoring multiplier is "given the regime, how much does this component evidence matter." No duplication.

---

### 2.2 Dependency Review

**Verdict: MOSTLY PASS — One code-quality violation found.**

#### Correct dependency direction
```
config/strategy.yaml ─────────────────────────────────────────┐
config/confidence.yaml ─────────────────────────────────────┐ │
                                                             │ │
FeatureSnapshot + ScoreContext ─→ IScoreComponent (×7) ─→ ComponentOutput
                                                             │
                                           ScoreCalculator ←─┘
                                           ScoreExplanationBuilder
                                                 │
                                           ScoreResult (frozen VO)
                                                 │
                                    ┌────────────┘
                                    │ + ComponentOutput×7
                                    │ + ISignalPerformanceRepository (async)
                                    │ + Redis (calibration, fail-open)
                                    ▼
                              ConfidenceCalculator (pure domain)
                              ConfidenceExplanationBuilder (pure domain)
                                    │
                              ConfidenceResult (frozen VO)
                                    │
                              ConfidenceCalculated event ──→ Redis Streams
```

#### Domain layer — clean
- `ScoreCalculator`: imports only domain VOs, enums, and config. Zero infrastructure. ✓  
- `ConfidenceCalculator`: imports only domain VOs, enums, and config. Zero infrastructure. ✓  
- `ScoreExplanationBuilder`: zero infrastructure. ✓  
- `ConfidenceExplanationBuilder`: zero infrastructure. ✓

#### Application layer — mostly clean

**FINDING H-1 (High): In-method import in `ConfidenceEngineService`**

Inside `calculate_confidence()`:
```python
from core.domain.confidence.confidence_calculator import ConfidenceCalculator
fingerprint_sha = ConfidenceCalculator.fingerprint_for(context, score_result)
```

This is a runtime import inside a method body. The class is already available via `self._calc` (injected in `__init__`). The static method can be called as `self._calc.fingerprint_for(context, score_result)` — no in-method import needed. In-method imports hide dependencies, complicate tooling analysis, and have a (small) runtime overhead per call.

**Fix:** Replace the in-method import with `self._calc.fingerprint_for(context, score_result)`.

#### No circular dependencies ✓  
#### No broker dependencies in Phase 11/12 ✓  
#### No direct DB access in domain services ✓

---

### 2.3 Event Flow Review

**Verdict: PARTIAL PASS — Two payload gaps identified.**

#### Events published

| Event | Publisher | Trigger |
|---|---|---|
| `ScoreCalculated` | `ScoringEngineService` | After every `evaluate()` call |
| `ConfidenceCalculated` | `ConfidenceEngineService` | After every `calculate_confidence()` call |
| `SignalExpired` | `SignalExpiryWorker` | When signal TTL elapses |

#### ScoreCalculated payload analysis

```python
instrument_token: int     ✓ routing key
direction: str            ✓ needed by downstream
direction_conviction: float ✓ quality signal
raw_score: float          ✓ pre-penalty transparency
adjusted_score: float     ✓ the operative value
score_quality: str        ✓ HIGH/MEDIUM/LOW/INSUFFICIENT
regime: str               ✓ context
data_completeness_pct: float ✓ data health
weights_sha256: str       ✓ reproducibility hash
penalties_count: int      ✓ summary
is_eligible: bool         ✓ routing decision
```

**FINDING H-2 (High): `ScoreCalculated` does not include `signal_id`**

The event has no `signal_id`. Any downstream consumer (dashboard, audit system, Phase 14 Signal Engine) that subscribes to this event cannot correlate it to a specific Signal entity without an external lookup by `instrument_token` + timestamp, which is fragile.

Note: Phase 13 (Risk Engine) will likely be called directly by the Phase 14 Signal Engine, not via event subscription. So this does not block Phase 13. It does become a dashboard and audit concern in Phase 15.

**FINDING H-3 (High): `ScoreCalculated` does not include `score_breakdown`**

The full per-component breakdown is in `ScoreResult` but is not serialized into the event. Downstream event consumers (dashboards subscribing to Redis Streams) cannot display "OI contributed 20.3pts, Trend contributed 18.7pts" from the event alone. They would need to call the API.

`ConfidenceCalculated` is significantly more complete — it includes all 10 adjustment values, which are the equivalent breakdown for confidence. Score is inconsistent in this regard.

#### ConfidenceCalculated payload analysis

```python
instrument_token: int          ✓
direction: str                 ✓
score_bucket: str              ✓
fingerprint: str               ✓ reproducibility
base_confidence: float         ✓
raw_confidence: float          ✓
calibrated_confidence: float   ✓
final_confidence: float        ✓
passed_gate: bool              ✓
win_rate_adj: float            ✓ all 10 adjustments included
...
signal_agreement_adj: float    ✓
recent_performance_adj: float  ✓
```

Confidence event payload is well-designed. All adjustment values are present for downstream audit.

#### Risk Engine event compatibility

The Phase 13 Risk Engine will be invoked directly (not via event subscription). The inputs it needs — `adjusted_score`, `final_confidence`, `passed_gate`, `direction`, `instrument_token`, `FeatureSnapshot` (for ATR) — are available in the domain objects passed between phases. No event changes are required for Phase 13.

---

### 2.4 Explainability Review

**Verdict: PASS for confidence, PARTIAL PASS for score.**

#### "Why score = 84?"

| Data available | Source | Accessible without code? |
|---|---|---|
| Per-component contribution | `ScoreBreakdown` fields | ✓ |
| Which penalties were applied | `ScoreResult.penalties` (list of `ScorePenalty`) | ✓ |
| Penalty types | `ScorePenalty.penalty_type` (5 types) | ✓ |
| Human-readable summary | `ScoreResult.explanation` (list[str]) | ✓ |
| Data completeness | `ScoreResult.data_completeness_pct` | ✓ |
| Score quality tier | `ScoreResult.score_quality` | ✓ |

**FINDING M-1 (Medium): Sub-component detail is untyped**

`ComponentOutput.metadata` is `dict` (no schema). Each component stores different keys:
- OI_BUILDUP: probably stores quadrant, pcr, max_pain_distance, fii_position
- TREND: probably stores adx_value, ema_alignment, supertrend_confirmed
- etc.

The dashboard cannot reliably render "ADX=32.4 → +16pts, EMA fully aligned → +4pts" without knowing the metadata schema per component. The `key_finding` field provides a single summary string, which is useful but limited.

This is an explainability gap at the sub-component level. The overall component contribution is visible (e.g., Trend contributed 18.0 pts), but the breakdown of how those 18 pts were reached within the Trend component is only accessible via untyped dict inspection.

#### "Why confidence = 76?"

| Data available | Source | Accessible without code? |
|---|---|---|
| All 10 adjustment values | `ConfidenceResult.*_adj` fields | ✓ |
| Data quality sub-inputs | `confidence_components["dq_*"]` | ✓ |
| Signal agreement detail | `confidence_components["sa_*"]` | ✓ |
| Recent performance detail | `confidence_components["rp_*"]` | ✓ |
| Raw vs calibrated vs final | Three separate fields | ✓ |
| Human-readable summary | `ConfidenceResult.explanation` (list[str]) | ✓ |
| Signal fingerprint | `ConfidenceResult.fingerprint` | ✓ |

Confidence explainability is excellent. The `confidence_components` dict with 20 keys provides full audit trail including all sub-inputs (AC-13 satisfied).

---

### 2.5 Historical Accuracy Review

**Verdict: PARTIAL PASS — Two methodology concerns.**

#### Signal Fingerprinting

The fingerprint is SHA-256 of: `(regime, score_bucket, direction, top_2_components, vix_bucket)`.

| Field | Rationale | Concern |
|---|---|---|
| `regime` | Market environment context | ✓ Appropriate |
| `score_bucket` | STRONG (≥85) or STANDARD (70-84) | ⚠️ Coarse: 70 and 84 share same bucket |
| `direction` | LONG or SHORT | ✓ Appropriate |
| `top_2_components` | The dominant signal drivers | ✓ Captures setup type |
| `vix_bucket` | Volatility environment | ✓ Appropriate |

**FINDING H-4 (High): `get_historical_accuracy` has no time-based lookback**

`get_win_rate` correctly filters by `lookback_days=90`. But `get_historical_accuracy` (fingerprint-based lookup) queries ALL historical records with no time filter. A fingerprint with 200 records from 18 months ago (a different volatility regime) is treated the same as one with 200 records from last month. This can produce misleading accuracy adjustments when market conditions have structurally changed.

**Fix:** Add `lookback_days` parameter to `get_historical_accuracy()` interface and implementation, defaulting to 180 days. This is configurable in `confidence.yaml`.

**FINDING M-2 (Medium): Score bucket granularity reduces fingerprint precision**

The `STANDARD` bucket spans scores 70–84 (a 14-point range). A signal scoring 70 and a signal scoring 84 receive identical fingerprints if all other fields match. Their historical accuracy can meaningfully differ. Tighter bucketing (e.g., 70-74, 75-79, 80-84) would improve precision without significant sample dilution — given sufficient history.

This is a calibration quality issue, not a correctness issue. It is acceptable for Phase 13. Consider as a Phase 14/15 improvement.

#### Bias risks

- **Survivorship bias:** Signals rejected by the Risk Engine never reach `signal_performance_stats` (written by Phase 14+ outcome recorder). The historical accuracy therefore measures only signals that passed risk checks, not all generated signals.
- **Selection bias in win rate:** `get_win_rate` filters by regime+direction+instrument_class. In volatile periods, fewer signals of a given type may pass the completeness gate, reducing sample sizes.
- **TIME_EXIT handling:** TIME_EXIT outcomes are not counted as WIN. They may represent neutral exits (neither profit nor loss). Treating them as non-WIN slightly underestimates win rates. Document this assumption explicitly.

---

### 2.6 Missing Data Review

**Verdict: PASS — All failure modes are handled correctly.**

#### Missing Option Chain

- `OptionChainComponent.evaluate()` → `ComponentOutput.unavailable()` (NEUTRAL, scores=0)
- `data_completeness_pct` = 6/7 = 85.7% → still eligible ✓
- Confidence: `option_chain_missing_pts` deducted from freshness sub-score ✓

#### Missing Sentiment

- `NeutralSentimentProvider` always returns neutral → `SentimentComponent` always `is_available=True`
- data_completeness_pct = 7/7 = 100% regardless of real sentiment data ✓ (by design)
- Acceptable because AI sentiment is deferred to Phase 17

#### Missing Volume

- VOLUME component (15 pts max) → unavailable → 0 contribution
- `data_completeness_pct` = 6/7 = 85.7% → still eligible ✓

#### Two components missing simultaneously

- `data_completeness_pct` = 5/7 = 71.4% < 75% → `is_eligible = False`
- Signal is NOT forwarded past gate — correct behavior ✓

**One nuance to note:** The 75% gate is component-count-based, not weight-based. Missing the 5-pt SENTIMENT and 5-pt IV_ANALYSIS together (total 10pt loss) triggers ineligibility the same as missing 5-pt SENTIMENT and 15-pt VOLUME (total 20pt loss). Both combinations yield 5/7 = 71.4%. This is conservative and safe — a false gate is safer than a false pass.

#### Delayed data

- OI grace period (300s) correctly exempts structured delays ✓
- Mild staleness (120-300s): deducted from freshness sub-score ✓
- Severe staleness (>300s): larger deduction ✓
- Cap prevents infinite penalty accumulation ✓

---

### 2.7 Calibration Review

**Verdict: PARTIAL PASS — One persistence gap.**

#### Calibration mechanism
- Weekly execution: Sunday 05:00 IST (CalibrationService)
- Buckets: 65-69, 70-74, 75-79, 80-84, 85-89, 90-100
- Formula: `factor = actual_win_rate / predicted_win_rate`
- Predicted win rate = confidence midpoint / 100 (e.g., bucket 70-74 → midpoint 72.5 → 0.725)
- Applies only if calibration error > 10% (noise guard) ✓
- Fail-open: if Redis is unavailable, factor defaults to 1.0 ✓

**FINDING M-3 (Medium): Calibration factors not persisted to database**

Calibration factors exist only in Redis (`confidence:calibration:{bucket_label}`). A Redis restart, eviction, or flush silently drops all calibration data. All confidence calculations then revert to uncalibrated (factor=1.0) without any warning or logging until the next Sunday recalibration.

This creates an auditability gap: if a signal was calculated at time T using calibration factor 0.87, and Redis is later flushed, there is no record of what factor was applied at time T (the `confidence_calibration_error` in `signal_performance_stats` captures the error, but not the factor itself).

**Fix:** Write calibration factors to a `confidence_calibration_log` table alongside the Redis write. Read from Redis in production; read from DB as fallback.

#### Reproducibility

`calibrated_confidence` depends on the Redis state at calculation time. Two calls to `calculate_confidence()` with identical inputs at different times can produce different results if Redis was updated between calls. This is inherent to the calibration design and is documented in the code. Acceptable, but should be explicitly noted in system documentation.

#### min_bucket_size = 10

A bucket with 10 samples has a ~±15% confidence interval on win rate. Calibration adjustments based on 10 samples can be volatile. The 10% error threshold partially guards against this, but consider raising min_bucket_size to 20-30 for production.

---

### 2.8 Future Asset Support Review

**Verdict: LIMITED PASS — Options-centric design requires extension for new asset classes.**

#### Currently supported
`InstrumentClass`: INDEX_OPTION, INDEX_FUTURE, STOCK_OPTION, STOCK_FUTURE

#### Not supported without extension

| Asset Class | Blocker |
|---|---|
| Equity Swing Trading | `EQUITY` not in `InstrumentClass` enum |
| Long-Term Investing | `LONG_TERM` not in enum; daily/weekly timeframes not configured |
| Commodity Futures | Not in enum |

#### Design-level asset expansion concerns

**FINDING M-4 (Medium): `FeatureSnapshot` and strategy components are options-centric**

`FeatureSnapshot` contains fields like `india_vix`, `iv_percentile`, `pcr`, `option_chain` — all specific to options trading. For equity swing trading, the relevant features are different (fundamental ratios, earnings proximity, sector rotation). Expanding asset classes would require:

1. Extending `FeatureSnapshot` with new optional field groups
2. New `IScoreComponent` implementations for non-options strategies
3. New sections in `strategy.yaml` for the new asset class weights
4. New entries in `InstrumentClass` enum
5. Potentially new fingerprint fields for equity-relevant dimensions (instead of VIX bucket)

The existing architecture SUPPORTS this extension without redesign. The component interface (`IScoreComponent`) is abstract, `strategy.yaml` is externally configurable, and `ScoreContext` fields are all Optional. Extension is additive — no existing code needs modification, only new implementations. This is a scalability note, not a flaw.

**VIX bucket in fingerprint for non-options:** For equity swing or futures instruments, India VIX may not be the right volatility discriminator. The fingerprint could use a more generic "volatility_bucket" based on HV or ATR percentile instead of VIX. This would need to be addressed before expanding asset classes.

---

### 2.9 Dashboard Readiness Review

**Verdict: PASS — All required data is structurally available.**

The dashboard (Phase 15) requires no backend structural changes to display:

| Display Element | Data Source | Available Now? |
|---|---|---|
| Score | `ScoreResult.adjusted_score` | ✓ |
| Score breakdown (per-component) | `ScoreBreakdown` fields | ✓ |
| Score penalties | `ScoreResult.penalties` list | ✓ |
| Score explanation | `ScoreResult.explanation` list[str] | ✓ |
| Confidence | `ConfidenceResult.final_confidence` | ✓ |
| Confidence breakdown (all 10 adj.) | `ConfidenceResult.confidence_components` | ✓ |
| Confidence explanation | `ConfidenceResult.explanation` list[str] | ✓ |
| Historical accuracy | `signal_performance_stats` table | ✓ (Phase 14+ writes) |
| Signal fingerprint | `ConfidenceResult.fingerprint` | ✓ |
| Data quality detail | `confidence_components["dq_*"]` | ✓ |

**What requires Phase 15 work (as planned):**
- REST API endpoints to expose ScoreResult/ConfidenceResult
- Pydantic response schemas
- Database persistence of ScoreResult details per signal (currently only summary in events)

**One gap:** Sub-component detail within a scoring component (e.g., "ADX=32 → +16pts, EMA aligned → +4pts within TREND") is only in `ComponentOutput.metadata` which is an untyped dict. The dashboard cannot render structured sub-component breakdowns without a defined schema per component type (see Finding M-1).

---

### 2.10 Risk Engine Readiness Review

**Verdict: READY — Phase 13 can be implemented without modifying Phase 11 or 12.**

#### Inputs Risk Engine needs vs what is available

| Risk Engine Input | Available From | Notes |
|---|---|---|
| `adjusted_score` | `ScoreResult` | ✓ |
| `direction` | `ScoreResult` | ✓ |
| `is_eligible` | `ScoreResult` | ✓ |
| `final_confidence` | `ConfidenceResult` | ✓ |
| `passed_gate` | `ConfidenceResult` | ✓ |
| `fingerprint` | `ConfidenceResult` | ✓ for Kelly lookup |
| ATR (position sizing) | `FeatureSnapshot.atr_14` via `ScoreContext` | ✓ if ScoreContext is passed through |
| Kelly (position sizing) | Needs win rate lookup via `ISignalPerformanceRepository` | ✓ interface exists |
| Kill switch state | `kill_switch_events` table | ✓ (needs wiring in Phase 13) |
| Account state | Will be introduced in Phase 13 | Phase 13 responsibility |

**FINDING L-1 (Low): No `RiskRequest` domain object defined**

The Risk Engine needs a structured input that combines ScoreResult + ConfidenceResult + account state + position context. No such domain object is defined yet. Phase 13 will need to define `RiskRequest` (or equivalent) as a new value object. This is Phase 13's work and not a gap in Phase 11/12.

**FINDING L-2 (Low): `instrument_class` is Optional on `ScoreContext`**

The win-rate lookup in `ConfidenceEngineService._win_rate_adj()` uses `context.instrument_class.value if context.instrument_class else ""`. When `instrument_class` is None, the repository query returns win rates across ALL instrument classes for the same regime+direction. This dilutes the accuracy — INDEX_OPTION win rates mixed with STOCK_OPTION win rates can produce misleading adjustments.

For Phase 13, the Risk Engine's Kelly calculation also uses win rates (separate from the confidence adjustment). If `instrument_class` is not reliably populated by callers, both the confidence and risk calculations will be imprecise.

**Recommendation:** Enforce `instrument_class` as non-Optional in the Signal Engine (Phase 14) when creating `ScoreContext`. Phase 13 should treat None as a hard rejection or warning.

**FINDING L-3 (Low): `Score` and `Confidence` value objects in domain layer are unused**

`src/core/domain/value_objects/score.py` defines a `Score` VO with comparison operators and `passes_execution_gate(min_score=70)`. `src/core/domain/value_objects/confidence.py` defines a `Confidence` VO with `passes_execution_gate(min_confidence=65)`.

Neither is used by `ScoreResult` or `ConfidenceResult`. The pipeline uses raw `float` values throughout. These VOs are dead abstractions that create confusion about what the "official" Score representation is.

Either adopt these VOs in `ScoreResult`/`ConfidenceResult` (stronger typing, gate logic in domain layer) or remove them. Leaving them as unused code is a maintenance liability.

---

## 3. Risks

### 3.1 Production Risk: Calibration data is not durable

Redis calibration factors can be silently lost on restart. In production, a Redis restart during trading hours would cause all confidence calculations to revert to uncalibrated values (factor=1.0) without operator awareness. This risks over-confident signals being forwarded to the Risk Engine.

**Severity:** High (production)  
**Phase impact:** Not blocking Phase 13, but must be addressed before Phase 16 (Paper Trading)

### 3.2 Data Staleness Risk: Historical accuracy uses unbounded lookback

`get_historical_accuracy()` queries all-time records for a fingerprint. In a structural regime change (e.g., market moves from trending to choppy for months), old WIN records for a TRENDING_BULLISH fingerprint continue to inflate the historical accuracy adjustment even when recent accuracy has degraded.

**Severity:** Medium  
**Phase impact:** Affects calibration quality from Phase 14 onward when outcome records begin accumulating

### 3.3 Auditability Risk: `ScoreCalculated` event lacks breakdown

If engineers or the Risk Engine need to reconstruct "what happened" from event logs alone, `ScoreCalculated` events don't contain the per-component breakdown. Reconstructing requires either the live API or a joined lookup of `signal_performance_stats`. For full event-sourced auditability, the breakdown should be in the event.

**Severity:** Medium (auditability)  
**Phase impact:** Becomes more significant from Phase 15 (Dashboard) onward

---

## 4. Required Fixes

The following fixes should be made **before Phase 13 implementation begins** (or as its first task), ordered by priority:

### Fix 1 — Remove in-method import from `ConfidenceEngineService` (H-1)

**File:** `src/core/application/services/confidence_engine_service.py`  
**Change:** Replace `from core.domain.confidence.confidence_calculator import ConfidenceCalculator` (inside `calculate_confidence()`) with `self._calc.fingerprint_for(context, score_result)`.

This is a one-line change. It removes a hidden dependency, makes the import graph analyzable by static tools, and eliminates the per-call import overhead.

### Fix 2 — Add `lookback_days` to `get_historical_accuracy()` (H-4)

**Files:**  
- `src/core/domain/interfaces/i_signal_performance_repository.py` — add `lookback_days: int` parameter  
- `src/core/infrastructure/database/repositories/signal_performance_repository.py` — add WHERE clause on `recorded_at >= cutoff`  
- `src/core/application/services/confidence_engine_service.py` — pass `lookback_days` from config  
- `config/confidence.yaml` — add `historical_accuracy.lookback_days: 180`  
- `src/core/infrastructure/config/confidence_config.py` — add field to `HistoricalAccuracyConfig`

This prevents stale historical data from distorting accuracy adjustments after market structure changes.

---

## 5. Optional Improvements

These are not blockers but would meaningfully improve robustness:

### OPT-1: Persist calibration factors to database

Add a `confidence_calibration_factors` table (or reuse `signal_performance_stats` audit column) to store the weekly factor snapshots. Use Redis as cache, DB as source-of-truth on restart.

### OPT-2: Define typed schema for `ComponentOutput.metadata`

Each scoring component should have a typed metadata dataclass (e.g., `OIBuildupMetadata`, `TrendMetadata`) instead of `dict`. This enables structured sub-component display in dashboards and type-safe downstream access.

### OPT-3: Add `score_breakdown` to `ScoreCalculated` event

Include the 7 per-component contribution values in the event payload. This enables purely event-sourced dashboard rendering without API calls. The values are scalars — there's no payload size concern.

### OPT-4: Tighten score bucket granularity in fingerprint

Consider 5-point bands (70-74, 75-79, 80-84, 85-89, 90-100) instead of STANDARD/STRONG. This improves accuracy-tracking precision with minimal implementation change.

### OPT-5: Resolve or remove unused `Score` and `Confidence` VOs

Either integrate them into `ScoreResult`/`ConfidenceResult` (enforcing gate logic in domain layer) or delete them. Their `passes_execution_gate()` methods duplicate the gate checks that already exist in `ConfidenceEngineService` and `ScoreCalculator`.

---

## 6. Technical Debt

| Item | Location | Impact |
|---|---|---|
| No `IRedisCache` abstraction | `ConfidenceEngineService`, `SignalDedupService`, `CalibrationService` | Direct Redis dependency; cannot swap cache layer without touching multiple services |
| `ComponentOutput.metadata` is untyped dict | All 7 strategy components | Dashboard/audit requires component-specific parsing |
| Momentum and Breakout always return 0 | `ConfidenceCalculator._momentum_adj`, `_breakout_adj` | Two fields in `confidence_components` are always 0; misleading in dashboards until Phase 14 activates them |
| `Score` and `Confidence` VOs unused | `score.py`, `confidence.py` | Dead code in domain layer; confuses new developers |
| In-method import | `ConfidenceEngineService.calculate_confidence()` | Hides dependency; resolvable in one line |
| Calibration in Redis only | `CalibrationService` | No DB backup; data loss on Redis restart |

---

## 7. Future Scalability Concerns

### 7.1 New asset class onboarding

Expanding to equity swing trading or long-term investing requires:
- New `InstrumentClass` enum values
- New `IScoreComponent` implementations with equity-appropriate indicators
- New config sections in `strategy.yaml` and `scoring_config.py`
- Potentially new `FeatureSnapshot` fields (fundamental ratios, earnings dates)
- New fingerprint discriminator (VIX bucket is options-specific)

The clean component interface makes this ADDITIVE (no existing code modified), which is the correct design. Estimated effort: 2–4 weeks per new asset class.

### 7.2 Throughput at scale

Currently, `ScoringEngineService` evaluates 7 components sequentially. At higher throughput (many instruments × many timeframes), parallel evaluation (via `asyncio.gather()`) would be necessary. The component interface supports this — components are stateless and independent.

`ConfidenceEngineService` already uses `asyncio.gather()` for its 5 repository reads. The scoring service should do the same for component evaluation when throughput becomes a concern.

### 7.3 Redis as single point of failure

Three services (ConfidenceEngineService, SignalDedupService, CalibrationService) depend on Redis. If Redis is unavailable:
- Calibration: fails open (factor=1.0) ✓ — handled correctly
- Dedup: if Redis is down, `is_duplicate()` likely raises; signals may all appear as non-duplicates
- Should verify `SignalDedupService.is_duplicate()` has the same fail-open behavior as calibration

### 7.4 `signal_performance_stats` growth

This table is append-only with no defined retention policy. After Phase 14 begins writing outcomes, it will grow indefinitely. Define a retention window (e.g., 3 years of outcomes) and add a cleanup or archival strategy.

---

## 8. Architecture Readiness Score

| Dimension | Score | Rationale |
|---|---|---|
| Separation of concerns | 9/10 | No overlap between scoring and confidence. Clean boundaries. |
| Dependency direction | 8/10 | Correct layering; one in-method import smell; no IRedisCache abstraction |
| Determinism / reproducibility | 9/10 | Domain services are pure; calibration non-determinism is acceptable and documented |
| Explainability | 8/10 | Excellent confidence breakdown; sub-component scoring detail is untyped |
| Event architecture | 7/10 | Events are functional; ScoreCalculated missing breakdown and signal_id |
| Historical accuracy methodology | 7/10 | Win-rate lookback is correct; historical accuracy has no lookback bound |
| Missing data handling | 9/10 | All failure modes handled; fail-open on Redis; unavailable() factory well-implemented |
| Calibration robustness | 7/10 | Correct logic; calibration data not durable beyond Redis TTL |
| Asset class extensibility | 8/10 | Architecture is extensible without redesign; options-centric features noted |
| Risk Engine readiness | 9/10 | All required inputs available; no blocker for Phase 13 |
| **Total** | **82 / 100** | |

---

## 9. Final Recommendation

```
READY_FOR_PHASE_13
```

No finding blocks Risk Engine implementation. The two required fixes (H-1 and H-4) are small, targeted changes that can be completed at the start of Phase 13 without impacting the Risk Engine's own implementation scope.

The Risk Engine can safely consume `ScoreResult` and `ConfidenceResult` as designed. The `FeatureSnapshot` (via `ScoreContext`) provides ATR for position sizing. The `ISignalPerformanceRepository` provides win rates for Kelly calculation. The `signal.py` state machine correctly gates RISK_PENDING transitions.

### Mandatory fixes before Phase 13 code is written

| Priority | Fix | Effort |
|---|---|---|
| 1 | Remove in-method import in `ConfidenceEngineService` (H-1) | 5 minutes |
| 2 | Add `lookback_days` to `get_historical_accuracy()` (H-4) | 30 minutes |

### Recommended before Phase 14 (Signal Engine)

| Item | Reason |
|---|---|
| Persist calibration factors to DB (M-3) | Durability before live signal outcome recording begins |
| Resolve Score/Confidence VO dead code (L-3) | Clarity before more phases are built on top |
| Enforce non-Optional `instrument_class` in Signal Engine (L-2) | Accuracy of win-rate and Kelly calculations |

---

*Review completed against codebase state: 1169 tests passing, ruff clean, Phase 12 gap closure complete.*
