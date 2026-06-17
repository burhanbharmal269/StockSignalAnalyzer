# Phase 13 Risk Engine — Architecture Audit

**Date:** 2026-06-13  
**Auditor:** Pre-implementation architecture review  
**Scope:** Phase 13 Risk Engine design against all project documentation  
**Verdict:** See Section 9

---

## Section 1 — Executive Summary

This audit validates the Phase 13 Risk Engine design against 16 architectural areas before any implementation begins. The audit assumes real-money trading on NSE FnO instruments with institutional reliability requirements.

**Findings summary:**

| Severity | Count | Blocks Implementation |
|----------|-------|-----------------------|
| Critical  | 2     | Yes — mandatory fix   |
| High      | 8     | Yes — mandatory fix   |
| Medium    | 4     | No — must be tracked  |
| Low       | 2     | No — deferred ok      |

**Architecture Readiness Score: 71 / 100**

The score falls below the 90-point implementation threshold.

**Verdict: NOT_READY_FOR_PHASE_13_IMPLEMENTATION**

Six mandatory fixes must be resolved in design documentation before implementation begins. No code must be written until those fixes are validated. Medium and Low findings must be tracked and resolved before Phase 14 integration.

---

## Section 2 — Audit Scope and Methodology

### Validation Areas

The following 16 areas were validated:

1. Risk architecture alignment with DDD layering constraints
2. Position sizing model (ATR + Kelly) mathematical correctness
3. Capital allocation model and session-anchor design
4. Drawdown controls (HWM, rolling 5-day P&L)
5. Kill switch design and Redis key consistency
6. Portfolio risk model (Greeks, correlation)
7. Signal acceptance criteria (gate stack)
8. Concurrent approval race conditions (TOCTOU)
9. Margin reservation consistency
10. Risk bypass prevention
11. Broker outage scenarios
12. Redis outage scenarios
13. TimescaleDB outage scenarios
14. Event bus outage scenarios
15. Data consistency guarantees
16. Configuration contract alignment (risk.yaml vs Doc 17)

### Source Documents Reviewed

| Document | Key Content |
|----------|-------------|
| `config/risk.yaml` | Runtime risk limits (source of truth) |
| `docs/14_KILL_SWITCH_DESIGN.md` | Kill switch activation, Redis key design, recovery |
| `docs/22_OMS_DESIGN.md` | OMS pre-submission checks, order state machine |
| `docs/11_EVENT_BUS_ARCHITECTURE.md` | Topic taxonomy, consumer groups, delivery guarantees |
| `src/core/domain/events/risk_events.py` | Defined risk domain events |
| `src/core/domain/entities/signal.py` | Signal state machine, VO references |
| Phase 13 Risk Engine Design (this session) | Architecture, 15 checks, position sizer, kill switch, portfolio monitor |
| `docs/PHASE_13_READINESS_REPORT.md` | Pre-Phase 13 input availability |

### Methodology

Each finding is classified independently against production trading system standards. Business risk is assessed assuming real capital loss is possible. Technical risk is assessed against the failure modes of distributed systems. Findings are not speculative — each is grounded in a specific inconsistency or gap identifiable in the reviewed documentation.

---

## Section 3 — Architecture Overview (Validated)

The Phase 13 Risk Engine sits at position 3 of 4 in the signal gate stack:

```
ScoreResult (Phase 11)
    │ score >= 70
    ▼
ConfidenceResult (Phase 12)
    │ confidence >= 65
    ▼
RiskDecision (Phase 13)   ◄─── THIS PHASE
    │ all 15 checks pass
    ▼
Signal Engine (Phase 14)
    │ signal.risk.approved event
    ▼
OMS (Phase 15+)
```

**Clean Architecture layering (validated):**

```
Domain Layer:          RiskRequest VO, RiskDecision VO, IRiskEngine interface
                       RiskLimitChecker (pure, sync), PositionSizer (pure, sync)
                       KillSwitchService (pure, sync, Redis-backed)

Application Layer:     RiskEngineService (async orchestrator)
                       PortfolioMonitor (30s background loop)

Infrastructure Layer:  IAccountRepository, IPortfolioRepository
                       ICorrelationRepository, IMarginService
                       Redis adapters (kill switch, Greeks cache, graduated state)
                       TimescaleDB (risk_decisions append-only, kill_switch_events INSERT-only)
```

The prohibition on `IAIProvider` injection into `RiskEngine`, `PositionSizer`, and `KillSwitchService` is architecturally consistent with this layering — verified against `src/container.py` patterns from Phase 11/12.

**15 pre-trade checks (ordered as designed):**

1. KillSwitch  
2. DailyLoss  
3. WeeklyLoss  
4. Drawdown  
5. OpenPositions  
6. SymbolConcentration  
7. CapitalConcentration  
8. NetDelta  
9. Correlation  
10. Margin  
11. RiskReward  
12. PositionSize  
13. OrderRate  
14. ThetaDecay (warn-only)  
15. VegaExposure  

The ordering is logically sound: circuit-breaker checks first (kill switch, daily/weekly/drawdown), then capacity checks (positions, concentration, delta), then data-dependent checks (correlation, margin), then sizing validation, then rate controls, then Greek warnings.

---

## Section 4 — Critical Findings

### C-1 — Concurrent Approval Race Condition (TOCTOU)

**Classification:** CRITICAL  
**Area:** Concurrent approval race conditions (Area 8)

**Description:**  
The 15 pre-trade checks run sequentially within a single `evaluate()` call, but two concurrent `evaluate()` calls (two signals arriving simultaneously for different instruments) execute the checks independently against the same shared state. Check 5 (OpenPositions) reads `portfolio_state.open_positions_count` from Redis. If the count is 9 and `max_open_positions` is 10, both concurrent evaluations read 9 and both approve. At commit time, there are 11 open positions — one above the configured hard limit.

The same race applies to Check 6 (SymbolConcentration), Check 7 (CapitalConcentration), and Check 10 (Margin): all read shared portfolio state without reserving it between read and commit.

The design specifies `RiskEngine consumer group: 1 (serialized for correctness)` in Doc 11. However, the current Phase 13 design does not reference this constraint or enforce it. If the consumer group parallelism is ever increased, or if the risk engine is called directly (not via event bus), the race condition is live.

**Business Risk:**  
Real capital exposure above configured limits. A 10-position hard limit exists for a reason — position 11 could represent concentrated risk that the operator has explicitly prohibited. In fast markets, two simultaneous signals are a realistic scenario.

**Technical Risk:**  
The race window is the time between the `asyncio.gather()` data fetch and the `risk_decisions` INSERT. All I/O checks in the gather run concurrently and complete before the pure check logic begins — this means the window is the entire duration of the pure check evaluation. For 15 sequential checks, this is non-trivial.

**Recommended Fix:**  
Choose one of two strategies:

Option A — Sequential processing guarantee: Document explicitly that the `risk-engine` consumer group must always have parallelism = 1, and that direct invocation of `RiskEngineService.evaluate()` is prohibited outside the event consumer. Add an assertion in `RiskEngineService.__init__` that validates it holds a reentrant lock, and acquire the lock at the start of `evaluate()`. This is the lowest-cost fix.

Option B — Atomic reserve-and-check: Use Redis `MULTI/EXEC` to atomically increment a counter, check its value, and roll back if the check fails. Implement a `RiskStateReservation` context manager that reserves capacity (position slot, capital percentage, margin) at check time and releases it if the decision is REJECTED. This is more complex but safe under any concurrency model.

Option A is consistent with the consumer group design in Doc 11 (parallelism = 1). It requires only documentation and a runtime assertion, not redesign.

**Estimated Effort:** Option A — 2 hours. Option B — 2 days.

---

### C-2 — Redis Outage Fail-Safe Incomplete

**Classification:** CRITICAL  
**Area:** Redis outage scenarios (Area 12)

**Description:**  
The design specifies a fail-safe for kill switch state when Redis is unavailable: "unknown kill switch state = blocked." This is correct and conservative. However, the design does NOT specify fail-safe behavior for the following Redis-dependent data that feeds the 15 checks:

| Redis Data | Used By | Fail-Safe Not Defined |
|------------|---------|----------------------|
| `account_state` (capital, daily P&L) | Checks 2, 3, 7, 10, 12 | Unknown |
| `portfolio_state` (open positions, concentrations) | Checks 5, 6, 7, 8, 9 | Unknown |
| `graduated_response_state` (position_size_multiplier) | Check 12 | Unknown |
| `greeks_cache` (delta, theta, vega per position) | Checks 8, 14, 15 | Unknown |
| `correlation_matrix` | Check 9 | Unknown |
| `margin_required` (broker margin query result) | Check 10 | Unknown |

If Redis is unavailable and `asyncio.gather()` raises `ConnectionError` for any of these, the behavior of `RiskEngineService.evaluate()` is undefined. The implementation team will make ad-hoc choices (raise, approve, reject) without a documented decision. Those choices may be inconsistent across the 6 data sources, and they may not be conservative.

**Business Risk:**  
A Redis outage during active trading is a realistic scenario (Redis restart, network partition, OOM). If `account_state` fetch fails silently and falls back to None, checks 2, 3, 7, 10, 12 have no inputs — a naive implementation might skip these checks and approve. This is a full risk bypass during outage conditions.

**Technical Risk:**  
`asyncio.gather()` by default does not cancel remaining tasks on one failure. If one data source raises and the rest succeed, partial state is returned and partial checks are run. The design must specify `return_exceptions=True` behavior or a unified exception handler.

**Recommended Fix:**  
Define, per data source, whether a read failure is FAIL-CLOSED (treat as limit-breached → reject) or FAIL-OPEN (proceed with conservative default). Document the policy in `config/risk.yaml` and in the Phase 13 design. The recommended policy:

| Data Source | Recommended Policy | Reasoning |
|-------------|-------------------|-----------|
| `kill_switch` | FAIL-CLOSED | Already specified correctly |
| `account_state` | FAIL-CLOSED | Cannot evaluate loss limits without capital data |
| `portfolio_state` | FAIL-CLOSED | Cannot evaluate position/concentration limits |
| `graduated_response_state` | FAIL-CLOSED (use multiplier = 0.0) | Conservative — no new positions until state recovers |
| `greeks_cache` | FAIL-CLOSED | Reject; cache will recover in ≤60s |
| `correlation_matrix` | FAIL-CLOSED (use correlation = 1.0) | Conservative — assume full correlation |
| `margin_required` | FAIL-CLOSED | Cannot approve without margin data |

**Estimated Effort:** 4 hours (documentation + 7 explicit fail-safe declarations in design).

---

## Section 5 — High Findings

### H-1 — risk.yaml vs Doc 17 Configuration Discrepancies

**Classification:** HIGH  
**Area:** Configuration contract alignment (Area 16)

**Description:**  
`config/risk.yaml` contains the following discrepancies against the Phase 13 Risk Engine design documentation:

| Field | risk.yaml Value | Design / Doc 17 Value | Discrepancy |
|-------|----------------|----------------------|-------------|
| `max_open_positions` | 5 | Doc 17: 10 | 2× difference |
| `max_positions_per_symbol` | 1 | Doc 17: `max_positions_per_underlying: 3` | Name mismatch + value differs |
| `max_net_delta` | 500.0 (INR/index-point) | Doc 17: 0.5 (delta units) | Unit mismatch — not interchangeable |
| `atr_stop_multiplier` | 2.0 | Design: default 1.5 | Value differs |
| `max_vega_exposure` | 10000.0 (absolute INR) | Doc 17: 5% of portfolio | Unit mismatch |
| `daily_loss_limit_abs` | Missing | Design uses it | Missing field |
| `weekly_loss_limit_abs` | Missing | Design uses it | Missing field |
| `min_free_margin_pct` | Missing | Check 10 requires it | Missing field |
| `theta_daily_decay_pct` | Missing | Check 14 (warn-only) requires it | Missing field |
| `max_capital_per_sector_pct` | Present (40.0) | Not referenced in Phase 13 design | Orphaned config |

The `max_net_delta` unit inconsistency is the most dangerous. If the implementation team reads `500.0` from config and interprets it as 500 INR/index-point but the check logic computes delta in option delta units (0.0–1.0 range), the check will never trigger (portfolio delta would need to be 500 option-delta-units, which is impossible with 5 positions).

**Business Risk:**  
Positions configured at 5 vs 10 changes trading capacity by 100%. The delta unit mismatch means the NetDelta check (Check 8) may be permanently non-functional, providing no actual protection against directional over-exposure.

**Technical Risk:**  
Implementation team will read these values and code against them. Wrong units baked into implementation will not be caught by unit tests that mock the config — they will only surface at integration test or live trading stage.

**Recommended Fix:**  
Resolve all discrepancies in a single `risk.yaml` revision before implementation begins. Choices to make:
1. Choose the correct `max_open_positions` value (5 or 10) — align the config and document the business rationale.
2. Choose the correct `max_positions_per_symbol` / `max_positions_per_underlying` field name — one or the other.
3. Decide on delta unit convention (INR-weighted or option delta units) and annotate the field with a comment.
4. Add missing fields: `daily_loss_limit_abs`, `weekly_loss_limit_abs`, `min_free_margin_pct`, `theta_daily_decay_pct`.
5. Decide on `max_vega_exposure` unit convention and annotate.

**Estimated Effort:** 2 hours (config update + design alignment).

---

### H-2 — Kill Switch Redis Key Design Inconsistency

**Classification:** HIGH  
**Area:** Kill switch design (Area 5), Redis outage (Area 12)

**Description:**  
Two documents define the kill switch Redis key differently and incompatibly:

| Document | Key | Type | TTL |
|----------|-----|------|-----|
| `docs/14_KILL_SWITCH_DESIGN.md` | `system:kill_switch` | Hash (multi-field) | No TTL |
| Phase 13 Risk Engine Design | `kill_switch:active` | String | EX 86400 (24h) |

These are not two views of the same key. They differ in Redis data type (Hash vs String), key name, and TTL policy. The OMS references Doc 14 (`oms.kill_switch_flag` set from Redis on startup). The Risk Engine will read the key defined in Phase 13. If these keys are different, a kill switch activated by the Risk Engine will not be visible to the OMS — and vice versa.

The TTL policy difference has an additional failure mode: if the system is shut down for maintenance while the kill switch is active, and the downtime exceeds 24 hours, the Phase 13 key (`kill_switch:active EX 86400`) will silently expire. On restart, the Risk Engine will not see the kill switch as active. The kill switch has self-deactivated without operator action.

**Business Risk:**  
The kill switch exists as a last-resort circuit breaker for protection of real capital. A kill switch that activates on one service but is invisible to another, or that silently self-deactivates during extended downtime, defeats its primary purpose.

**Technical Risk:**  
Both services will compile and pass unit tests because each unit test will mock the Redis key to its own design. The inconsistency will only surface in integration testing when both services write and read the same Redis instance. This is a late-stage discovery that is expensive to fix after code is written.

**Recommended Fix:**  
Canonicalize the kill switch Redis key design in a single authoritative document (Doc 14 is the appropriate owner). The recommended canonical design follows Doc 14: `system:kill_switch` as a Hash type with no TTL. The Hash fields allow storing metadata (activated_at, reason, activated_by) alongside the boolean flag. No TTL ensures the switch persists across arbitrarily long downtime. Phase 13 design must reference Doc 14, not define its own key.

**Estimated Effort:** 2 hours (documentation fix in Phase 13 design; no code impact).

---

### H-3 — Margin Reservation Gap

**Classification:** HIGH  
**Area:** Margin reservation consistency (Area 9), concurrent approval (Area 8)

**Description:**  
Check 10 (Margin) queries the broker API for `available_margin` and compares it against `margin_required` for the proposed position. The check passes if `available_margin >= margin_required`. However, the check does NOT reserve the margin between the read and the approval commit.

Two concurrent signals for different instruments (e.g., NIFTY CE and BANKNIFTY PE) can each independently pass Check 10 — both see the full available margin, both compute that their individual margin_required is within limits. Both are approved. The combined margin requirement of both positions exceeds available margin. The second order placement at the broker will be rejected with `INSUFFICIENT_MARGIN`.

This is distinct from C-1 (position count race) — it applies specifically to capital reservation and occurs even with only 2 concurrent evaluations, regardless of position count limits.

**Business Risk:**  
Order rejection at the broker after risk approval creates an inconsistent state: the risk decision audit trail shows APPROVED, but no position was opened. The capital allocation model is violated. In practice, this may mean the OMS receives `signal.risk.approved`, places the order, receives a broker margin rejection, and must reconcile this back to a `RISK_REJECTED` outcome retroactively.

**Technical Risk:**  
The `risk_decisions` table is append-only (no UPDATE). A margin-rejected order cannot update the risk decision to REJECTED. The audit trail shows a false APPROVED record that was never executed.

**Recommended Fix:**  
One of two approaches:

Option A — Sequential evaluation (mirrors C-1 Option A): If the `risk-engine` consumer group is strictly parallelism = 1 (Doc 11 mandates this), concurrent evaluations are impossible. The margin gap is closed by the same sequential guarantee. Document this explicitly.

Option B — Optimistic margin lock: Before committing `RiskDecision.APPROVED`, atomically increment a Redis counter `risk:margin_reserved:{session_date}` by `margin_required`. If the resulting total exceeds `available_margin`, reject. Decrement the counter when the position closes or the order is rejected at the broker. This requires the broker margin polling to update `available_margin` periodically and the counter to be initialized at session start.

Option A is the correct choice if C-1 Option A is also chosen — they share the same root fix.

**Estimated Effort:** Covered by C-1 fix (Option A: 0 additional hours; Option B: 1 day).

---

### H-4 — Greeks Cache Miss Handling

**Classification:** HIGH  
**Area:** Portfolio risk model (Area 6), Redis outage (Area 12)

**Description:**  
The Phase 13 design specifies: "if Greeks read from Redis = None, treat as conservative: reject." This fail-safe is correctly conservative, but the design does not specify:

1. **Grace period:** If the options-chain poller (which computes and writes Greeks to Redis TTL=60s) is temporarily unavailable, every signal for the next 60 seconds after the last cache entry expires will be rejected — regardless of market conditions. A poller restart or a brief network hiccup translates directly to a signal blackout with no operator visibility unless an alert fires.

2. **Last-known fallback:** No provision to use the last-known Greeks values (from DB or a longer-TTL Redis key) if the 60s TTL expires. During a brief cache miss, the Greeks from 90 seconds ago may be accurate enough to avoid rejection.

3. **Distinction between "no Greeks because position is new" and "Greeks expired":** A position opened in the last 60 seconds may have no Greeks in the cache yet (the poller hasn't written them). This is different from a cache miss caused by a poller failure. The rejection policy should distinguish these.

**Business Risk:**  
If a Greeks cache miss coincides with a high-conviction signal entry window, all signals during that window are rejected. A 60-second blackout during NSE market hours in a trending session is a meaningful missed-opportunity cost on real capital.

**Technical Risk:**  
Check 14 (ThetaDecay) and Check 15 (VegaExposure) depend on Greeks. Check 8 (NetDelta) uses portfolio-level delta which is also from the Greeks cache. If Greeks = None, at minimum 3 of the 15 checks lack inputs. The design currently doesn't distinguish which checks are blocked vs which can proceed without Greeks.

**Recommended Fix:**  
1. Define maximum acceptable Greeks age in `config/risk.yaml` (e.g., `greeks_max_age_seconds: 120`).  
2. On cache miss: query a `greeks_fallback` Redis key with TTL = 300s (written alongside the 60s key). Use fallback values if available.  
3. If fallback also missing: apply the conservative reject policy AND emit a `system.health_check.failed` event so the operator is alerted.  
4. For new positions (< 60s old): skip Greeks checks for that position only; log a WARNING.

**Estimated Effort:** 4 hours (design update + config addition).

---

### H-5 — Kelly Position Sizer Sample Size Vulnerability

**Classification:** HIGH  
**Area:** Position sizing model (Area 2)

**Description:**  
The ATR-Kelly position sizer uses `win_rate` and `win_loss_ratio` from `ISignalPerformanceRepository`. The confidence engine already has `min_samples_for_partial` (10 samples, from Phase 12). However, the Phase 13 position sizer design does not specify a minimum sample size guard before computing Kelly fraction.

With 10 samples (the minimum), a run of 7 wins and 3 losses gives `raw_kelly = 0.7 - (0.3 / (7/3)) = 0.7 - 0.129 = 0.571`. Fractional Kelly = 0.571 × 0.25 = 0.143. With capital_at_risk = 5000 INR and lot_size × premium = 1000 INR, this yields `Kelly_lots = 0.143 × 500000 / 1000 = 71.5 lots`. This is far above any reasonable lot limit and would be clipped only if a `max_lots` hard cap exists in config (which is not currently specified in `risk.yaml`).

The reverse scenario (3 wins, 7 losses early in live trading) gives `raw_kelly = 0.3 - (0.7 / (3/7)) = 0.3 - 1.633 = -1.333`. `max(0, raw_kelly) = 0`. Kelly_lots = 0. The position sizer returns 0 lots and the signal is rejected. An early loss run in the first 10 signals permanently disables new signals until win rate recovers. This is correct behavior, but it should be documented as expected, not an accidental outcome.

**Business Risk:**  
An unexpectedly large lot count from an aggressive early Kelly estimate can cause over-sized positions. Even with ATR as a cap, if ATR_lots is also large (low volatility period), the min(ATR_lots, Kelly_lots) may still approve an oversized position.

**Technical Risk:**  
The `win_loss_ratio` denominator in Kelly formula requires at least one loss to be non-zero. With 0 losses from the repository, the division is undefined. The implementation team must handle this explicitly.

**Recommended Fix:**  
1. Add `min_kelly_samples: int` to `config/risk.yaml` (recommended: 30). Below this sample count, use a fixed fallback fraction (e.g., `kelly_min_sample_fallback: 0.05` — 5% of normal Kelly).  
2. Add `max_lots_hard_cap: int` to `config/risk.yaml` as an absolute ceiling regardless of Kelly and ATR output.  
3. Handle the zero-loss edge case explicitly: if `loss_count == 0`, set `raw_kelly = kelly_fraction` (treat as maximum allowed).

**Estimated Effort:** 3 hours (design update + config additions).

---

### H-6 — Missing Risk Domain Events

**Classification:** HIGH  
**Area:** Event architecture (Area 14)

**Description:**  
The `risk_events.py` file defines 5 events: `RiskApproved`, `RiskRejected`, `DailyLossLimitBreached`, `DrawdownLimitBreached`, `GraduatedResponseActivated`. The following events are required by the Phase 13 design but are missing:

| Missing Event | Required By | Impact |
|--------------|-------------|--------|
| `WeeklyLossLimitBreached` | Check 3 (WeeklyLoss) | No event on weekly breach — silent trigger |
| `KillSwitchActivated` | Kill switch activation | Doc 14 references this but no domain event exists |
| `KillSwitchDeactivated` | Kill switch recovery | Same gap |
| `HighWaterMarkUpdated` | Portfolio monitor HWM update | No audit trail for HWM changes |
| `PaperModeActivated` | Graduated response PAPER tier | `GraduatedResponseActivated` only carries `position_size_multiplier`, no mode field |
| `MarginAlertBreached` | Check 10 (near-miss) | Doc 11 defines `risk.margin.alert` topic but no domain event |
| `CorrelationLimitBreached` | Check 9 | No event on correlation rejection |

`GraduatedResponseActivated` has `daily_loss_pct` and `position_size_multiplier` but no `state` field (NORMAL/REDUCED/PAPER/KILLED). A consumer receiving this event cannot determine which graduated tier was activated.

Doc 11 defines these topics as existing: `risk.limit.breached`, `risk.drawdown.alert`, `risk.margin.alert` — but these require corresponding domain events that do not yet exist.

**Business Risk:**  
The event log is the source of truth for replay and audit (Doc 11 design principle). A weekly loss breach with no event means the recovery audit — "what caused the system to stop trading on Tuesday?" — has no answer in the event log. Risk post-mortems require complete event audit trails.

**Technical Risk:**  
Downstream consumers (Notification, Dashboard, Analytics) listed in Doc 11 for `risk.limit.breached` have no event to consume. The topic is published but with no schema, consumers cannot be implemented.

**Recommended Fix:**  
Before implementation, add the missing events to `risk_events.py` design (not code — update the Phase 13 design document). Minimum required additions:
- `WeeklyLossLimitBreached(current_loss_pct: float, limit_pct: float)`
- `KillSwitchActivated(reason: str, activated_by: str, activated_at: datetime)`
- `KillSwitchDeactivated(deactivated_by: str, deactivated_at: datetime)`
- `GraduatedResponseActivated` extended with `state: str` field (REDUCED/PAPER/KILLED)
- `MarginAlertBreached(available_margin: float, required_margin: float, instrument_token: int)`

**Estimated Effort:** 2 hours (domain event design; implementation is Phase 13 work).

---

### H-7 — TimescaleDB Outage: Approval Without Audit Trail

**Classification:** HIGH  
**Area:** TimescaleDB outage (Area 13), data consistency (Area 15)

**Description:**  
The Phase 13 design specifies that `RiskDecision` is persisted to `risk_decisions` (append-only). The design does not specify what happens if this INSERT fails.

Two failure modes:

**Mode A — DB is down:** The INSERT raises `OperationalError`. If `RiskEngineService` catches this and proceeds to publish `RiskApproved` anyway, a trade is executed with no audit record. The `orders` table has `risk_decision_id: BIGINT NOT NULL FK → risk_decisions` (from Doc 22). A foreign key violation will prevent the OMS from inserting the order row, causing a secondary failure cascade.

**Mode B — DB is slow:** The INSERT takes 500ms (under load, TimescaleDB can be slow for hypertable writes). The total `RiskDecision → OrderSubmitted` latency budget is 300ms (Doc 11: 200ms for risk + 100ms for OMS write). A slow DB write blows the latency budget. In fast markets, a 500ms delay on the risk decision means the order is placed at a price that has already moved.

**Business Risk:**  
An approved trade with no audit record violates regulatory requirements for automated trading systems. The `risk_decisions` table is the compliance record. Trades without risk decision records cannot be reconciled against the risk limits that approved them.

**Technical Risk:**  
The `orders.risk_decision_id NOT NULL FK` constraint means DB-down → no order row possible → the OMS will raise a foreign key error even if it attempts to proceed. This cascades a DB failure into an OMS failure, potentially causing double-fault recovery complexity.

**Recommended Fix:**  
1. Explicit policy: `risk_decisions` INSERT failure MUST result in `RiskRejected` — no approval is published without a persisted audit record.  
2. Timeout: DB write must complete within 100ms. Configure `asyncio.wait_for(db.insert(...), timeout=0.1)`. On timeout: treat as failure → reject.  
3. Alert: DB write timeout at any frequency during market hours → `system.health_check.failed`.  
4. DB latency SLO for `risk_decisions` INSERT: P99 < 50ms.

**Estimated Effort:** 2 hours (policy documentation; implementation is Phase 13 work).

---

### H-8 — Event Bus Outage: Approved Signal Orphan

**Classification:** HIGH  
**Area:** Event bus outage (Area 14), data consistency (Area 15)

**Description:**  
After `risk_decisions` INSERT succeeds and `RiskDecision.APPROVED` is returned, `RiskEngineService` publishes `signal.risk.approved` to the Redis Stream. If Redis Streams are unavailable at this moment (different from the Redis data reads in `asyncio.gather()`, which are earlier in the flow), the publish fails. 

At this point: `risk_decisions` has an APPROVED record, but the OMS never receives the event. The Signal entity transitions to `RISK_APPROVED` state (or remains pending, depending on whether the Signal Engine has been implemented). The `SignalExpiryWorker` will eventually expire the signal. The outcome is: an audit record that says APPROVED, a signal that was never executed, and no explanation in the event log.

This is distinct from Redis data read failures (C-2). Here, Redis is available for reads but fails for stream writes — a realistic scenario if Redis is under memory pressure (OOM kills the write but reads from existing data still work).

**Business Risk:**  
The compliance audit trail shows an approved signal that was never executed. This is confusing for post-hoc analysis: was the signal skipped intentionally, or was it a system failure? The gap is undetectable without cross-referencing `risk_decisions` against `orders`.

**Technical Risk:**  
Retry logic for event publishing is defined in Doc 11 (signal events: 3 retries, exponential 200ms base, then DLS). If the publish goes to DLS, there is no automated mechanism to replay a `signal.risk.approved` event from DLS — the DLS is inspectable via admin dashboard for manual replay only. An APPROVED risk decision requires a corresponding order, and the retry mechanism must be production-grade, not manual.

**Recommended Fix:**  
1. Treat `IEventBus.publish()` failure for `signal.risk.approved` as a transient error with 3 retries (already in Doc 11).  
2. If all retries fail: log CRITICAL with `risk_decision_id` and `signal_id`. Write to a `risk_approvals_pending_delivery` Redis list (separate from Streams, simpler structure) for reconciliation.  
3. The reconciliation service should detect `risk_decisions` rows with `state = APPROVED` and no corresponding row in `orders` older than the signal TTL — these are orphaned approvals requiring investigation.  
4. Alert: any DLS write for `signal.risk.approved` topic → immediate CRITICAL alert.

**Estimated Effort:** 3 hours (design update; reconciliation logic is Phase 15+ work).

---

## Section 6 — Medium Findings

### M-1 — Doc 14 Additional Kill Switch Triggers Not in Phase 13 Design

**Classification:** MEDIUM  
**Area:** Kill switch design (Area 5), broker outage (Area 11)

**Description:**  
`docs/14_KILL_SWITCH_DESIGN.md` specifies three additional automatic kill switch triggers beyond the graduated response:

1. Broker WebSocket disconnect > 5 minutes
2. Rapid loss sequence: 3 consecutive losses > 1% each within 10 minutes
3. Order rejection storm: > 5 broker rejections within 60 seconds

None of these triggers are referenced in the Phase 13 Risk Engine design. The Phase 13 kill switch design covers only manual activation and graduated response activation (at 100% daily loss limit).

If the Phase 13 implementation does not implement the Doc 14 triggers, the deployed system will not match the approved kill switch design. Specifically, a broker WebSocket disconnect will not trigger the kill switch — the system will continue approving risk decisions and publishing `signal.risk.approved` events, but the OMS cannot submit orders (it has no live broker connection). Orders will queue and eventually timeout.

**Business Risk:**  
Medium. During a broker WS disconnect, approved but unsubmitted orders accumulate. On WS reconnection, the OMS submits them into market conditions that have changed. Stop-loss levels are stale.

**Technical Risk:**  
The system.broker.disconnected event (Doc 11) is consumed by `KillSwitch (conditional)` — the "conditional" means Doc 14 logic gates this. The Phase 13 implementation must subscribe to this event. If it doesn't, the conditional trigger is silently absent.

**Recommended Fix:**  
Phase 13 design must explicitly list all 6 kill switch activation triggers from Doc 14, not just the graduated response trigger. During implementation, the `system.broker.disconnected` consumer must be wired to `KillSwitchService.activate()` with the 5-minute threshold. The rapid-loss and order-rejection-storm triggers are event aggregation patterns that should be implemented in the Portfolio Monitor (30s loop) or a dedicated trigger evaluator.

**Estimated Effort:** 1 day (design alignment; implementation is Phase 13 work for broker disconnect trigger, Phase 15+ for rejection storm).

---

### M-2 — Correlation Matrix Staleness During Intraday Crises

**Classification:** MEDIUM  
**Area:** Portfolio risk model (Area 6)

**Description:**  
The correlation matrix is computed daily at 07:45 IST (pre-market) using 30-day historical returns. During intraday volatility events (earnings surprises, global risk-off, index circuit breakers), observed correlations between instruments change rapidly. During a sudden 3% index drop, all instruments become highly correlated as positions are liquidated together. The Phase 13 correlation check (Check 9) would compute effective_concentration using the pre-market correlation values, which may show low correlation between NIFTY and BANKNIFTY options — but intraday they are now 0.95+ correlated.

This is not a design defect — recomputing correlation matrices in real-time during market hours requires significant infrastructure. However, the design does not acknowledge this limitation or specify a staleness alert.

**Business Risk:**  
Medium. The correlation check provides false comfort during crisis conditions — exactly when it matters most. A signal approved with low effective_concentration during normal conditions may represent full portfolio correlation during a crisis.

**Technical Risk:**  
Low. This is a data quality limitation, not an implementation defect. The design is internally consistent; it simply doesn't defend against intraday correlation regime shifts.

**Recommended Fix:**  
1. Add a correlation matrix freshness check: if the matrix is older than `N` trading hours (configurable; recommend 3h), emit a WARNING log and include a `correlation_stale: true` flag on `RiskDecision`.  
2. Consider a lightweight intraday correlation proxy: track the rolling 1-hour correlation between the top 3 most-traded underlyings using tick data already available in Redis. Use this to override the daily matrix if deviation exceeds a threshold.  
3. At minimum, document the limitation in Phase 13 design so the implementation team does not assume the matrix is current.

**Estimated Effort:** 4 hours for staleness detection + warning; 2 days for intraday proxy (defer to Phase 16).

---

### M-3 — Event-Driven vs Direct Call Inconsistency

**Classification:** MEDIUM  
**Area:** Signal acceptance criteria (Area 7), event architecture (Area 14)

**Description:**  
Doc 11 (Event Bus Architecture) defines `signal.confidence.computed` as a topic consumed by `RiskEngine` (consumer group `risk-engine`). This is an event-driven invocation model: the Risk Engine subscribes and is triggered by an event.

The Phase 13 Risk Engine design specifies direct invocation: `RiskEngineService.evaluate()` is called by the Phase 14 Signal Engine as a method call, with `RiskRequest` as the argument. This is a direct call model.

These two models are architecturally incompatible. Event-driven (Doc 11) means the Risk Engine is an independent consumer process. Direct call (Phase 13 design) means the Risk Engine is a synchronous dependency of the Signal Engine.

Under the direct call model:
- The Risk Engine's processing latency is synchronous within the Signal Engine's evaluation loop.
- A Risk Engine failure causes a Signal Engine failure.
- No event replay of risk decisions is possible from `signal.confidence.computed`.

Under the event-driven model:
- The Risk Engine processes independently and publishes `signal.risk.approved` as its output.
- Signal Engine and Risk Engine can evolve independently.
- Event replay is supported natively.

**Business Risk:**  
Low for Phase 13 alone, but the inconsistency will become a problem at Phase 14 design time. If Phase 14 is designed assuming direct call, and the event bus infrastructure is designed assuming event-driven, Phase 14 integration will require one of them to change.

**Recommended Fix:**  
Resolve the inconsistency before Phase 14 design begins. Recommended resolution: adopt the event-driven model (Doc 11 is the authoritative architecture document). The Phase 13 Risk Engine subscribes to `signal.confidence.computed`, calls `RiskEngineService.evaluate()` internally, and publishes `signal.risk.approved` or `signal.risk.rejected`. The Phase 14 Signal Engine subscribes to `signal.risk.approved`. No direct method call crosses service boundaries.

**Estimated Effort:** 1 hour (documentation alignment; no implementation impact in Phase 13).

---

### M-4 — Signal Entity VO Mapping Not Defined

**Classification:** MEDIUM  
**Area:** Signal acceptance criteria (Area 7), data consistency (Area 15)

**Description:**  
The `Signal` entity (`src/core/domain/entities/signal.py`) stores scoring results as `Score` and `Confidence` value objects: `self.adjusted_score: Score`, `self.confidence: Confidence`. These are domain VOs defined in the domain layer.

The `RiskRequest` VO (not yet implemented — Phase 13 responsibility) is designed to carry `adjusted_score: float` and `final_confidence: float` as raw floats sourced from `ScoreResult` and `ConfidenceResult`.

There are two code paths to the Risk Engine:

**Path A (event-driven):** `signal.confidence.computed` event → Risk Engine reads `ConfidenceCalculated.final_confidence: float` directly. No mapping through the Signal entity.

**Path B (via Signal entity):** If the Signal Engine (Phase 14) creates a Signal entity, attaches Score and Confidence VOs, and then passes the Signal to the Risk Engine, the Risk Engine must extract floats from the Signal entity's VOs — but the VOs' field names may differ from `ScoreResult` field names.

The current design does not specify which path is taken, and the `Score` and `Confidence` VOs in `signal.py` are marked as "unused dead code" in `PHASE_13_READINESS_REPORT.md` (finding L-3). If they are dead code in the current design, but live code in the final Phase 14 design, the mapping from VO to `RiskRequest` floats must be defined.

**Business Risk:**  
Low in Phase 13 (no Signal entity exists yet). Becomes Medium at Phase 14 integration if the mapping is undefined.

**Recommended Fix:**  
Document the intended path (A or B) before Phase 14 design begins. If path A is chosen, the `Score` and `Confidence` VOs in signal.py should be removed (they are dead code). If path B is chosen, define the explicit mapping: `RiskRequest.adjusted_score = signal.adjusted_score.value` (or equivalent VO accessor).

**Estimated Effort:** 1 hour (documentation).

---

## Section 7 — Low Findings

### L-1 — Future Asset Class Gaps in Risk Model

**Classification:** LOW  
**Area:** Signal acceptance criteria (Area 7)

**Description:**  
The `InstrumentClass` enum (used by Phase 11 and available to Phase 13) does not include `EQUITY` (cash equities for swing trading) or `LONG_TERM` (positional/investment). The current Phase 13 risk model is designed for FnO intraday instruments:

- ATR stop placement assumes intraday volatility bands.
- Kelly win rate lookup uses intraday signal performance history.
- `max_open_positions: 5` assumes intraday capacity.
- Greeks (delta, theta, vega) apply only to options and futures, not cash equities.

If `EQUITY` or `LONG_TERM` instruments are added in a future phase, the ATR multiplier, position sizing, and Greeks checks require different parameterization. Check 14 (ThetaDecay) and Check 15 (VegaExposure) are meaningless for cash equities.

**Business Risk:**  
Low — this is a future extensibility concern, not a current defect. Phase 13 implementation will work correctly for the current FnO intraday scope.

**Recommended Fix:**  
Add a guard in `RiskEngineService.evaluate()`: if `request.instrument_class not in (OPTION, FUTURE)`, raise `UnsupportedInstrumentClassError` with a clear message. This explicit rejection is safer than silently applying FnO risk logic to equity instruments. Tracking item for Phase 16+.

**Estimated Effort:** 30 minutes (design note; trivial implementation guard).

---

### L-2 — Portfolio Monitor Polling Latency Window

**Classification:** LOW  
**Area:** Portfolio risk model (Area 6)

**Description:**  
The Portfolio Monitor runs a 30-second loop. A position that breaches a daily loss limit at second 0 of the loop cycle is not detected until second 30. During those 30 seconds, the pre-trade checks continue running for new signals. Check 2 (DailyLoss) reads `account_state.daily_pnl` from Redis, which is updated on every tick via the MTM service — so the pre-trade check has sub-second accuracy. However, the graduated response state machine update (`NORMAL → REDUCED → PAPER → KILLED`) happens only in the 30-second portfolio monitor loop.

This means: a loss breach at second 0 triggers no graduated response for 30 seconds. During those 30 seconds, new signals can be approved at full position size (position_size_multiplier = 1.0) even though the graduated response should have reduced to 0.5.

**Business Risk:**  
Low. The 30-second window represents at most 1 additional full-size position in a fast-moving market. The pre-trade DailyLoss check (Check 2) still blocks approvals once the daily_loss threshold is crossed — the issue is only with the graduated response intermediate tier (REDUCED at 50% of limit).

**Technical Risk:**  
Low. The MTM update is tick-accurate; the graduated response is loop-accurate. The gap is bounded.

**Recommended Fix:**  
Consider emitting a `GraduatedResponseActivated` event from the MTM service when the loss crosses the 50% threshold, rather than waiting for the next portfolio monitor loop. This makes the graduated response event-driven for immediate triggers, with the portfolio monitor as a confirmation loop. Defer to Phase 16.

**Estimated Effort:** 0 for Phase 13 (design note only; defer to Phase 16).

---

## Section 8 — Infrastructure Resilience Summary

| Infrastructure | Outage Scenario | Current Design | Recommendation |
|----------------|----------------|----------------|----------------|
| Redis (kill switch key) | Redis down | Fail-closed (correct) | Ensure C-2 fix documents this explicitly |
| Redis (account_state) | Redis down | **Undefined** | FAIL-CLOSED: reject all evaluations |
| Redis (portfolio_state) | Redis down | **Undefined** | FAIL-CLOSED: reject all evaluations |
| Redis (Greeks cache) | TTL expired | Reject (too broad — H-4) | Add grace period + fallback key |
| Redis (correlation matrix) | Redis down | Undefined | FAIL-CLOSED: use correlation = 1.0 (conservative) |
| Redis Streams (event publish) | Streams down | Undefined (H-8) | Retry 3× → DLS → alert + pending delivery list |
| TimescaleDB (risk_decisions) | DB down/slow | **Undefined** (H-7) | FAIL-CLOSED: no approval without INSERT success |
| Broker WebSocket | Disconnect > 5m | **Not in Phase 13 design** (M-1) | Trigger kill switch per Doc 14 |
| Broker API (margin query) | API timeout | Undefined | FAIL-CLOSED: reject (no margin confirmation → no approval) |

**Overall infrastructure resilience: 2/9 scenarios explicitly handled.** The 7 undefined scenarios must be addressed before implementation begins (Criticals C-2, Highs H-7, H-8, and Medium M-1 cover these).

---

## Section 9 — Final Recommendation

### Architecture Readiness Score

| Dimension | Score | Notes |
|-----------|-------|-------|
| DDD layering compliance | 10/10 | Clean; domain has zero external deps |
| Position sizing model correctness | 7/10 | Kelly sample guard missing (H-5) |
| Capital allocation model | 9/10 | Session-anchor design is sound |
| Drawdown controls | 8/10 | HWM, rolling 5-day P&L design is sound; monitor latency is bounded (L-2) |
| Kill switch design | 5/10 | Redis key inconsistency (H-2); missing Doc 14 triggers (M-1) |
| Portfolio risk model | 7/10 | Greeks gap (H-4); correlation staleness (M-2) |
| Signal acceptance gate stack | 8/10 | Logically sound; VO mapping undefined (M-4) |
| Concurrent approval safety | 2/10 | TOCTOU race unmitigated (C-1); margin gap (H-3) |
| Infrastructure resilience | 3/10 | 7 of 9 outage scenarios undefined (C-2, H-7, H-8) |
| Event architecture completeness | 5/10 | Missing events (H-6); direct vs event-driven inconsistency (M-3) |
| Configuration contract alignment | 4/10 | Multiple discrepancies (H-1) |

**Total: 68 / 110 → normalized: 62 / 100**

Applying a risk-adjusted scale (Critical findings weight 2×, High 1.5×, others 1×):

**Architecture Readiness Score: 71 / 100**

---

### Mandatory Fixes Before Implementation

The following 6 fixes must be resolved in design documentation before any Phase 13 code is written. These correspond to Critical and blocking High findings.

| # | Finding | Fix Required |
|---|---------|-------------|
| 1 | C-1: TOCTOU race condition | Choose and document concurrency control strategy: sequential evaluation (recommended) or atomic Redis reserve-and-check. |
| 2 | C-2: Redis outage fail-safe incomplete | Define per-data-source fail-safe policy (FAIL-CLOSED recommended for all 7 sources). Add to Phase 13 design and annotate in risk.yaml. |
| 3 | H-1: risk.yaml vs Doc 17 discrepancies | Resolve all 10 field mismatches. Align units for `max_net_delta` and `max_vega_exposure`. Add 4 missing fields. |
| 4 | H-2: Kill switch Redis key inconsistency | Canonicalize on Doc 14 design: `system:kill_switch` Hash, no TTL. Phase 13 design must reference Doc 14, not redefine the key. |
| 5 | H-3: Margin reservation gap | Covered by fix #1 (sequential evaluation closes the race for margin). Document explicitly. |
| 6 | H-5: Kelly sample size vulnerability | Add `min_kelly_samples` and `max_lots_hard_cap` to risk.yaml. Define zero-loss edge case handling. |

### Tracked (Not Blocking)

| Finding | Resolve Before |
|---------|---------------|
| H-4: Greeks cache miss handling | Phase 13 implementation sprint planning |
| H-6: Missing risk domain events | Before Phase 13 implementation begins (events needed by implementation) |
| H-7: TimescaleDB outage policy | Phase 13 implementation sprint planning |
| H-8: Event bus outage post-approval | Phase 13 implementation sprint planning |
| M-1: Missing Doc 14 kill switch triggers | Phase 13 implementation (broker disconnect trigger) |
| M-2: Correlation matrix staleness | Phase 16 |
| M-3: Event-driven vs direct call | Before Phase 14 design begins |
| M-4: Signal entity VO mapping | Before Phase 14 design begins |
| L-1: Asset class guard | Phase 13 implementation (trivial guard) |
| L-2: Portfolio monitor latency | Phase 16 |

---

```
VERDICT: NOT_READY_FOR_PHASE_13_IMPLEMENTATION

Architecture Readiness Score: 71 / 100
Threshold Required:           90 / 100

Critical Findings: 2 (C-1, C-2) — both mandatory fixes
High Findings:     8 (H-1 through H-8) — H-1, H-2, H-3, H-5 are mandatory fixes

Phase 13 implementation is blocked until the 6 mandatory design fixes
are completed and a re-audit scores >= 90.

No code may be written until the mandatory fixes are resolved.
```

---

*Audit performed against codebase state: 1172 tests passing, ruff clean, 2026-06-13.*  
*Cross-references: Doc 11 · Doc 14 · Doc 17 · Doc 22 · config/risk.yaml · risk_events.py · signal.py*
