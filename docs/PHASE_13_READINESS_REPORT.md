# Phase 13 Readiness Report

**Date:** 2026-06-13  
**Scope:** Post-fix validation of Scoring Engine + Confidence Engine before Risk Engine implementation  
**Source review:** docs/SCORING_CONFIDENCE_INTEGRATION_REVIEW.md (2026-06-13)  
**Test suite:** 1172 passed, 0 failed, ruff clean

---

## 1. Applied Fixes

All four approved fixes were implemented and verified.

### H-1 — In-method import removed

**File:** `src/core/application/services/confidence_engine_service.py`

Replaced the runtime import inside `calculate_confidence()`:
```python
# Before (H-1 violation)
from core.domain.confidence.confidence_calculator import ConfidenceCalculator
fingerprint_sha = ConfidenceCalculator.fingerprint_for(context, score_result)

# After (fixed)
fingerprint_sha = self._calc.fingerprint_for(context, score_result)
```

The injected `ConfidenceCalculator` instance is used directly. Static methods are callable on instances. The hidden dependency is eliminated; the import graph is fully analyzable by static tools.

---

### H-4 — Configurable `lookback_days` for historical accuracy

**Files changed:** 4

| File | Change |
|---|---|
| `config/confidence.yaml` | Added `lookback_days: 180` under `historical_accuracy` |
| `src/core/infrastructure/config/confidence_config.py` | Added `lookback_days: int = Field(ge=1)` to `HistoricalAccuracyConfig` |
| `src/core/domain/interfaces/i_signal_performance_repository.py` | Added `lookback_days: int` parameter to `get_historical_accuracy()` |
| `src/core/infrastructure/database/repositories/signal_performance_repository.py` | Applied `WHERE recorded_at >= cutoff` using `datetime.now(UTC) - timedelta(days=lookback_days)` |
| `src/core/application/services/confidence_engine_service.py` | Passes `lookback_days=cfg.historical_accuracy.lookback_days` to the repository call |

The default of 180 days prevents stale market-regime records from biasing the accuracy adjustment. The value is fully configurable in `confidence.yaml` — no code change required to adjust the window.

New test added: `TestHistoricalAccuracyAdjustment.test_historical_accuracy_called_with_lookback_days` verifies the service passes `lookback_days` to the repository.

---

### H-2 — `signal_id` added to `ScoreCalculated` event

**File:** `src/core/domain/events/signal_events.py`

Added `signal_id: uuid.UUID | None = None` as an optional keyword-only field. It defaults to `None` for all current callers; the Phase 14 Signal Engine will populate it once a Signal entity is in scope.

The field is optional by design: scoring can be invoked outside a Signal entity context (batch calibration, backtesting, direct testing). Making it required would constrain callers that have no signal_id.

New test added: `TestScoringEngineServicePipeline.test_event_signal_id_defaults_to_none` confirms the default.

---

### H-3 — `score_breakdown` added to `ScoreCalculated` event

**Files changed:** 2

| File | Change |
|---|---|
| `src/core/domain/events/signal_events.py` | Added 10 `breakdown_*` scalar fields |
| `src/core/application/services/scoring_engine_service.py` | Populates all 10 fields from `result.score_breakdown` |

Fields added to `ScoreCalculated`:
```
breakdown_oi_buildup: float
breakdown_trend: float
breakdown_option_chain: float
breakdown_volume: float
breakdown_vwap: float
breakdown_sentiment: float
breakdown_iv_analysis: float
breakdown_regime_alignment: str
breakdown_regime_mismatch: bool
breakdown_total: float
```

Each is sourced directly from the corresponding `ScoreBreakdown` field, ensuring parity with `ScoreResult.score_breakdown`. Individual scalar fields were chosen over a serialized dict to maintain type safety, keep the event hashable (frozen dataclass), and stay consistent with how `ConfidenceCalculated` exposes all 10+ adjustment values as individual scalars.

New test added: `TestScoringEngineServicePipeline.test_event_contains_score_breakdown` asserts all 10 fields match the ScoreResult.

---

## 2. Updated Findings Table

| ID | Severity | Status | Finding |
|---|---|---|---|
| H-1 | High | **FIXED** | In-method import removed from `ConfidenceEngineService` |
| H-2 | High | **FIXED** | `signal_id: uuid.UUID \| None = None` added to `ScoreCalculated` |
| H-3 | High | **FIXED** | 10 `breakdown_*` scalar fields added to `ScoreCalculated` |
| H-4 | High | **FIXED** | `lookback_days=180` configurable cutoff on `get_historical_accuracy()` |
| M-1 | Medium | Open | `ComponentOutput.metadata` is untyped dict (sub-component detail schema-less) |
| M-2 | Medium | Open | Score bucket granularity: STANDARD spans 70–84 (14 pts) |
| M-3 | Medium | Open | Calibration factors Redis-only (no DB persistence backup) |
| M-4 | Medium | Open | Options-centric design; equity/futures expansion requires additive extension |
| L-1 | Low | Open | No `RiskRequest` domain VO defined (Phase 13 responsibility) |
| L-2 | Low | Open | `instrument_class` Optional on `ScoreContext`; dilutes win-rate lookups |
| L-3 | Low | Open | `Score` and `Confidence` VOs in domain layer are unused dead code |

**0 High findings remain.** All four mandatory pre-Phase 13 fixes are complete.

Open findings are all Medium or Low severity and none block Phase 13. The three Medium items (M-1, M-2, M-3) and three Low items (L-1, L-2, L-3) are tracked for resolution in Phases 14–16.

---

## 3. Architecture Readiness Score

| Dimension | Previous | Current | Delta | Rationale |
|---|---|---|---|---|
| Separation of concerns | 9/10 | 9/10 | — | Unchanged; no overlap introduced |
| Dependency direction | 8/10 | **9/10** | +1 | H-1 fixed; runtime import eliminated |
| Determinism / reproducibility | 9/10 | 9/10 | — | AC-11 unchanged; calibration non-determinism documented |
| Explainability | 8/10 | **9/10** | +1 | H-3 fixed; breakdown now in event for dashboard consumers |
| Event architecture | 7/10 | **9/10** | +2 | H-2 + H-3 fixed; signal_id and breakdown now in ScoreCalculated |
| Historical accuracy methodology | 7/10 | **9/10** | +2 | H-4 fixed; unbounded lookback eliminated |
| Missing data handling | 9/10 | 9/10 | — | Unchanged |
| Calibration robustness | 7/10 | 7/10 | — | M-3 deferred (Redis-only persistence) |
| Asset class extensibility | 8/10 | 8/10 | — | Unchanged |
| Risk Engine readiness | 9/10 | 9/10 | — | All required inputs available |
| **Total** | **82 / 100** | **92 / 100** | **+10** | |

**Score: 92 / 100** — above the 90-point threshold.

---

## 4. Phase 13 Risk Engine — Input Availability Checklist

The Risk Engine requires the following inputs. All are confirmed available from Phase 11 and 12 outputs.

| Input | Source | Status |
|---|---|---|
| `adjusted_score` | `ScoreResult.adjusted_score` | ✓ Available |
| `direction` | `ScoreResult.direction` | ✓ Available |
| `is_eligible` | `ScoreResult.is_eligible` | ✓ Available |
| `final_confidence` | `ConfidenceResult.final_confidence` | ✓ Available |
| `passed_gate` | `ConfidenceResult.passed_gate` | ✓ Available |
| `fingerprint` | `ConfidenceResult.fingerprint` | ✓ Available (for Kelly lookup) |
| ATR (position sizing) | `ScoreContext.features.atr_14` via `FeatureSnapshot` | ✓ Available if ScoreContext is forwarded |
| Win rate (Kelly) | `ISignalPerformanceRepository.get_win_rate()` | ✓ Interface exists |
| Kill switch state | `kill_switch_events` table (append-only) | ✓ Table defined; wiring is Phase 13 work |
| Account state | Not yet defined | Phase 13 responsibility |
| `RiskRequest` VO | Not yet defined | Phase 13 responsibility |

---

## 5. Phase 13 Implementation Guidance

The following constraints and interface expectations are provided as input to Phase 13 planning. These do not require changes to Phase 11 or 12.

**What Phase 13 must define:**
- `RiskRequest` value object combining `ScoreResult` + `ConfidenceResult` + account state + position context
- `RiskDecision` value object (approved / rejected, reason, position size, position sizing inputs)
- `IRiskEngine` interface in `core/domain/interfaces/`
- `RiskEngineService` in `core/application/services/` (application orchestrator)
- Risk domain services in `core/domain/risk/` (pure, synchronous, no I/O)

**What Phase 13 must NOT do (architecture lock):**
- No signal label generation (BUY/SELL/STRONG_BUY)
- No modification to ScoreResult or ConfidenceResult value objects
- No injection of IAIProvider into RiskEngine, PositionSizer, or KillSwitchService
- `risk_decisions` table is append-only — no UPDATE or DELETE
- `kill_switch_events` table is INSERT-only for the application DB user

**Available Risk events (already defined, Phase 13 will implement publishers):**
- `RiskApproved` — `src/core/domain/events/risk_events.py`
- `RiskRejected` — `src/core/domain/events/risk_events.py`
- `DailyLossLimitBreached` — `src/core/domain/events/risk_events.py`
- `DrawdownLimitBreached` — `src/core/domain/events/risk_events.py`
- `GraduatedResponseActivated` — `src/core/domain/events/risk_events.py`

**Recommended first task for Phase 13:**
Define `RiskRequest` VO. Its field contract determines what the Phase 14 Signal Engine must pass through, and every other Phase 13 component depends on it.

---

## 6. Final Recommendation

```
READY_FOR_PHASE_13
Architecture Readiness Score: 92 / 100

All mandatory pre-Phase 13 fixes are complete.
All 1172 tests pass. ruff clean.
Phase 13 Risk Engine planning is approved.
```

---

*Fixes validated against codebase state: 1172 tests passing, ruff clean, 2026-06-13.*
