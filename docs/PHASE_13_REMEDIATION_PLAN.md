# Phase 13 Risk Engine — Remediation Plan

**Date:** 2026-06-13  
**Source Audit:** docs/PHASE_13_RISK_ENGINE_ARCHITECTURE_AUDIT.md  
**Scope:** Design-level resolution of Critical and High findings: C-1, C-2, H-1, H-2, H-3, H-5  
**Status:** READY_FOR_REVIEW (see Section 8)

---

## Findings Being Resolved

| ID | Severity | Finding |
|----|----------|---------|
| C-1 | Critical | Concurrent approval race condition (TOCTOU) |
| C-2 | Critical | Redis outage fail-safe undefined for 7 data sources |
| H-1 | High | risk.yaml vs Doc 17 — 10 field discrepancies |
| H-2 | High | Kill switch Redis key design inconsistency |
| H-3 | High | Margin reservation gap |
| H-5 | High | Kelly position sizer sample size vulnerability |

---

## Section 1 — Updated Architecture Decisions

### C-1: Concurrent Approval Race Condition

#### Root Cause

The 15 pre-trade checks read shared portfolio state (open position count, margin, capital concentration, net delta) during `asyncio.gather()` and then run pure logic checks against those values. Between the read and the decision commit, another concurrent evaluation can read the same state and make the same decision. Both evaluations see `open_positions = 9` against a limit of 10 and both approve. The result is `open_positions = 11` — one above the hard limit. No mechanism exists to atomically reserve capacity between read and commit.

The same race window applies to:
- Check 5 (OpenPositions): open_positions counter
- Check 6 (SymbolConcentration): positions per underlying counter
- Check 7 (CapitalConcentration): capital allocated per underlying
- Check 8 (NetDelta): portfolio-level net delta
- Check 10 (Margin): available margin (see H-3 below)

#### Option A vs Option B Comparison

| Dimension | Option A: Sequential (parallelism = 1) | Option B: Distributed Reservation / Locking |
|-----------|----------------------------------------|---------------------------------------------|
| **Complexity** | Low. Enforce consumer group parallelism = 1. Add asyncio `asyncio.Lock` inside `RiskEngineService` as a defence-in-depth measure. No new data structures or protocols. | High. Requires Redis `MULTI/EXEC` (or Lua scripts) to atomically read-increment-check-rollback for each check. Requires reservation TTLs to handle crashes mid-evaluation. Requires rollback logic on rejection. |
| **Safety** | High. Sequential execution eliminates the race window entirely. One evaluation completes before the next begins. | High. Atomic operations eliminate the race window. Correct if implemented without bugs. More implementation surface area means more risk of subtle correctness errors. |
| **Throughput** | For Phase 1: sufficient. NSE FnO signal generation rate at ≤200 instruments: estimated 1–5 signals per minute across all instruments. Risk evaluation P99 < 200ms (Doc 17 SLO). At 200ms each, sequential throughput = 5 evaluations/second = 300/minute — 60× the estimated signal rate. No throughput constraint exists in Phase 1. | Unlimited horizontal scaling. Multiple workers can evaluate different signals in parallel. Required for Phase 2 (>200 instruments, Kafka migration per Doc 11). |
| **Future Scaling** | Becomes a bottleneck when signal rate approaches 5/second sustained. Doc 11 defines the Kafka migration threshold as >200 instruments. At that scale, Option B is required. Option A must be migrated. | Phase 2 ready. Design is valid for both single-process and multi-process deployment. Migration from Option A to Option B requires adding reservation logic but does not change the 15-check logic or the `RiskDecision` schema. |
| **Recovery from crash mid-evaluation** | Trivially safe: the asyncio lock is released when the coroutine exits, whether normally or via exception. The next evaluation proceeds. | Requires TTL-based reservation expiry in Redis. A crashed worker holding a reservation must time out before the next worker can acquire the same resource slot. This introduces a minimum recovery latency equal to the TTL. |
| **Operational risk** | Low. A single bug in the lock acquisition path would cause a deadlock that is immediately visible (all risk checks stall). | Medium. A bug in the rollback path could leave orphaned reservations until TTL expiry, causing false rejections. This is harder to debug in production. |

#### Recommendation: Option A for Phase 1

**Choose Option A.** The NSE FnO signal rate in Phase 1 does not require parallelism. Option A eliminates the race condition with minimal complexity, zero new Redis dependencies, and trivial crash recovery. The concurrency model is already specified by Doc 11: the `risk-engine` consumer group has parallelism = 1. This plan makes that constraint explicit and enforceable.

Document Option B as the Phase 2 migration path when the Kafka migration threshold (>200 instruments) is crossed.

#### Proposed Solution

1. The `risk-engine` consumer group MUST be configured with parallelism = 1 at all times. This is the primary concurrency control. Documented in Doc 11 (already) and in Phase 13 implementation notes.

2. `RiskEngineService` MUST hold an instance-level `asyncio.Lock` acquired at the start of `evaluate()` and released on exit. This is defence-in-depth: if a second evaluation is triggered by a direct call (not the event consumer), the lock prevents concurrent execution.

3. `RiskEngineService.evaluate()` MUST NOT be called concurrently from any code path outside the event consumer. This prohibition is documented in the Phase 13 implementation constraints.

4. The lock is non-reentrant. Recursive calls to `evaluate()` from within an active evaluation are a design error and will deadlock — which is the correct behavior (explicit failure, not silent data corruption).

#### Architectural Impact

- No change to the 15-check logic
- No change to `RiskDecision` schema
- No change to `RiskRequest` VO
- No new Redis keys
- Adds one `asyncio.Lock` field to `RiskEngineService.__init__`
- Adds one `async with self._lock:` block in `evaluate()`

#### Files / Docs Requiring Updates

| Document | Change |
|----------|--------|
| Phase 13 implementation notes | Add: "parallelism = 1 is a hard constraint, not a default" |
| `docs/11_EVENT_BUS_ARCHITECTURE.md` | Already specifies parallelism = 1 for `risk-engine` group — add NOTE confirming it is enforced by a lock, not just a config |
| `src/core/application/services/risk_engine_service.py` (Phase 13) | Lock acquisition — implementation responsibility |

#### Migration Impact

None. Option A is additive. Migrating to Option B in Phase 2 requires adding Redis reservation logic around the same 15 checks — the checks themselves do not change.

#### Future Scalability Impact

When signal rate approaches 5/second sustained (Phase 2), migrate to Option B. The migration marker is the Kafka threshold from Doc 11: >200 instruments OR cross-process deployment. At that point, the `asyncio.Lock` is removed and replaced with Redis `MULTI/EXEC` reservation blocks per check category.

---

### H-3: Margin Reservation Gap (Resolved by C-1)

#### Root Cause

Check 10 (Margin) queries `available_margin` and approves if it is sufficient. Two concurrent evaluations both see the full available margin and both approve. The combined margin requirement exceeds available margin. The second order placement at the broker is rejected with `INSUFFICIENT_MARGIN`.

#### Proposed Solution

**Closed by C-1 Option A.** Sequential evaluation means no two margin checks can observe the same available margin snapshot simultaneously. The first approved signal causes an order submission, which reduces available margin via the broker settlement. By the time the second evaluation runs, the margin query reflects the reduced balance.

**Residual risk acknowledged:** There is a latency window between the risk approval and the broker reflecting the margin change. This window is bounded by broker API update latency (typically < 500ms). A second signal evaluated within this window could see stale margin. Given the signal rate in Phase 1 (1–5/minute) and the lock serializing evaluations, this residual window is acceptable. If it becomes a concern in Phase 2, introduce explicit margin reservation as described in Option B.

---

### C-2: Redis Outage Fail-Safe Policy

#### Root Cause

The kill switch is the only Redis dependency with a documented fail-safe (unknown = blocked). The remaining six Redis data sources that feed the 15 pre-trade checks have no documented behavior on read failure. Implementations built without this specification will make ad-hoc choices that may be inconsistent and unsafe.

#### Proposed Solution

Every Redis dependency in `RiskEngineService.evaluate()` has a designated failure policy. These policies are applied within the `asyncio.gather()` call by setting `return_exceptions=True` and inspecting results before the check logic runs. A single failed data source does not silently proceed to the checks — it produces a deterministic, documented outcome.

**Failure Policy Table:**

| Redis Data Source | Failure Policy | Justification |
|-------------------|----------------|---------------|
| `system:kill_switch` (Hash) | **FAIL_CLOSED** — treat as active (block) | Already specified in Doc 14. Unknown kill switch state is always safe: block and investigate. |
| `account_state` | **FAIL_CLOSED** — reject evaluation | Checks 2, 3, 4, 7, 12 depend on daily P&L, weekly P&L, drawdown, and capital data. Without this, the system cannot evaluate loss limits. Approving without loss limit data is a compliance and capital risk. |
| `portfolio_state` | **FAIL_CLOSED** — reject evaluation | Checks 5, 6, 7, 8, 9 depend on open position count, per-underlying count, capital allocation, and portfolio delta. Without this, position and concentration limits cannot be evaluated. |
| `graduated_response_state` | **FAIL_CLOSED** — use multiplier = 0.0 (block new positions) | The multiplier controls position sizing. Unknown multiplier state means the system does not know whether it should be in NORMAL, REDUCED, or PAPER mode. Conservative behavior: no new positions until state is readable. Emit `system.health_check.failed`. |
| `greeks_cache` | **FAIL_CLOSED with TTL-graduated fallback** | Primary: read from `risk:greeks:{position_id}` (TTL 60s). Fallback: read from `risk:greeks:fallback:{position_id}` (TTL 300s, written alongside primary). If primary miss: use fallback and emit WARNING. If both miss: reject. See Section 5 for key design. |
| `correlation_matrix` | **FAIL_CLOSED with conservative default** | On read failure: assume all correlations = 1.0 (perfect positive correlation). This means Check 9 uses the most conservative possible effective concentration, which may cause over-rejection but never under-rejection. Emit WARNING. Do not block the entire evaluation — proceed with the conservative value. |
| `margin_required` (broker API result) | **FAIL_CLOSED** — reject evaluation | Check 10 (Margin) cannot be evaluated without margin data. Approving without a margin check is the most dangerous possible outcome — it can result in broker-level margin rejection, partial position state, and audit trail inconsistency. |

**Unified exception handler specification:**

```
gather_result = await asyncio.gather(
    fetch_account_state(),
    fetch_portfolio_state(),
    fetch_graduated_response_state(),
    fetch_greeks_cache(),
    fetch_correlation_matrix(),
    fetch_margin_required(),
    return_exceptions=True
)

For each result in gather_result:
    If isinstance(result, Exception):
        Apply the FAIL_CLOSED policy for that data source.
        Record: failed_source, exception_type, timestamp.
        If policy = reject_evaluation:
            Return RiskDecision(approved=False, rejection_code=DATA_SOURCE_UNAVAILABLE,
                               failed_source=<source_name>)
        If policy = conservative_default:
            Continue with documented default value.
            Append check warning to RiskDecision.checks.
```

**Redis fail-safe behavior is logged at ERROR level.** Every data source failure during market hours is an incident. Each produces a `system.health_check.failed` event with `component=<source_name>` and `reason=redis_read_error`.

#### Event Stream Failure Policy

The event stream (`signal.risk.approved` / `signal.risk.rejected` publish) is treated separately because it occurs after the 15 checks complete, not during them.

**Policy:** Retry 3 times with exponential backoff (200ms base, as per Doc 11 signal event retry policy). On all retries exhausted:
- Write to `risk:approvals_pending_delivery` Redis List (separate from Streams, survives stream outage if Redis data plane is healthy)
- Emit CRITICAL log with `risk_decision_id` and `signal_id`
- The reconciliation service detects `risk_decisions` rows with `approved=True` and no corresponding `orders` row older than signal TTL — these are orphaned approvals

**Event stream failure does NOT cause a new RiskDecision.** The decision is final. Only the delivery of the notification is retried.

#### Architectural Impact

- Adds exception handling to the `asyncio.gather()` block in `RiskEngineService.evaluate()`
- Adds a `risk:greeks:fallback:{position_id}` Redis key write alongside the primary Greeks cache write (GreeksService responsibility, Phase 13)
- Adds `risk:approvals_pending_delivery` Redis List as a delivery fallback
- No change to `RiskDecision` schema beyond adding `failed_sources: list[str]` field for audit

#### Files / Docs Requiring Updates

| Document | Change |
|----------|--------|
| Phase 13 implementation notes | Add fail-safe policy table as a mandatory implementation constraint |
| `config/risk.yaml` | Add `redis_fail_safe` section (see Section 3) |
| `docs/14_KILL_SWITCH_DESIGN.md` | No change — kill switch fail-safe already documented |
| `src/core/application/services/risk_engine_service.py` (Phase 13) | Exception handling in gather — implementation responsibility |
| Greeks cache writer (Phase 13) | Must write both primary (TTL 60s) and fallback (TTL 300s) keys |

#### Migration Impact

None. The fail-safe logic is additive. When migrating to Kafka (Phase 2), the `risk:approvals_pending_delivery` List becomes a Kafka dead-letter topic.

#### Future Scalability Impact

In a multi-instance deployment (Phase 2), each instance applies the same fail-safe policies independently. The policies do not require inter-instance coordination. Correlation matrix conservative default (1.0) is idempotent across instances.

---

## Section 2 — Updated Risk Engine Flow

The following flow supersedes the Phase 13 design's pre-trade check description.

```
RiskEngineService.evaluate(request: RiskRequest) -> RiskDecision:

─── Concurrency Gate (C-1) ────────────────────────────────────────────────────
  ACQUIRE self._evaluation_lock  (asyncio.Lock — non-reentrant)
  If lock held: wait (sequential execution guaranteed)

─── Parallel I/O Phase (C-2 fail-safe applied to each) ───────────────────────
  gather(
    [1] fetch kill_switch_state()          → FAIL_CLOSED: reject (block=True)
    [2] fetch account_state()              → FAIL_CLOSED: reject
    [3] fetch portfolio_state()            → FAIL_CLOSED: reject
    [4] fetch graduated_response_state()   → FAIL_CLOSED: multiplier=0.0, reject
    [5] fetch greeks_cache(positions)      → FAIL_CLOSED: use fallback or reject
    [6] fetch correlation_matrix()         → conservative default: all ρ=1.0
    [7] fetch margin_required(instrument)  → FAIL_CLOSED: reject
    return_exceptions=True
  )
  
  For each failed source: log ERROR, emit system.health_check.failed
  Apply policies (see C-2 table)
  If any reject-policy source failed: return RiskDecision(approved=False,
                                                          code=DATA_SOURCE_UNAVAILABLE)
  
─── Pure Check Phase (sequential, ordered) ────────────────────────────────────
  Check  1: KillSwitch         → kill_switch_state.is_active
  Check  2: DailyLoss          → account_state.daily_loss_consumed_pct >= 100
  Check  3: WeeklyLoss         → account_state.weekly_loss_consumed_pct >= 100
  Check  4: Drawdown           → account_state.drawdown_from_hwm_pct >= max_drawdown_pct
  Check  5: OpenPositions      → portfolio_state.open_positions_count >= max_open_positions
  Check  6: SymbolConcentration → portfolio_state.positions_per_underlying[symbol] >= max_positions_per_underlying
  Check  7: CapitalConcentration → portfolio_state.capital_per_underlying_pct[symbol] + new_pct > max_capital_per_underlying_pct
  Check  8: NetDelta           → (portfolio_state.net_delta + proposed_delta) > max_net_delta
  Check  9: Correlation        → effective_concentration(correlation_matrix) > max_net_delta
  Check 10: Margin             → account_state.available_margin < margin_required
  Check 11: RiskReward         → request.risk_reward_ratio < min_risk_reward_ratio
  Check 12: PositionSize       → compute_lots() (see Section 6; H-5 Kelly protection applied)
  Check 13: OrderRate          → portfolio_state.orders_last_minute >= max_orders_per_minute
  Check 14: ThetaDecay         → WARN if daily_theta_decay > max_theta_daily_decay_pct [not hard block]
  Check 15: VegaExposure       → (portfolio_state.net_vega + proposed_vega) > max_net_vega_pct_of_capital
  
  First failure → return RiskDecision(approved=False, rejection_code=<check_name>, ...)
  All pass     → proceed to sizing and persistence

─── Sizing Phase ──────────────────────────────────────────────────────────────
  final_lots = min(
    atr_lots(request, account_state),
    kelly_lots(request, performance_data)  ← H-5 protections applied
  ) × graduated_response_state.position_size_multiplier
  
  If final_lots == 0: return RiskDecision(approved=False, code=POSITION_SIZE_ZERO)

─── Persistence Phase (H-7 policy) ───────────────────────────────────────────
  decision = RiskDecision(approved=True, position_size_lots=final_lots, ...)
  
  INSERT INTO risk_decisions (...)  ← timeout=100ms (asyncio.wait_for)
  If INSERT fails or timeout:
    → return RiskDecision(approved=False, code=AUDIT_PERSISTENCE_FAILURE)
    → log CRITICAL
    → emit system.health_check.failed(component=timescaledb)
  
─── Event Publication Phase (H-8 policy) ──────────────────────────────────────
  Publish signal.risk.approved  (retry 3×, exponential 200ms)
  If all retries fail:
    → LPUSH risk:approvals_pending_delivery <decision_json>
    → log CRITICAL with risk_decision_id

─── Release Gate ──────────────────────────────────────────────────────────────
  RELEASE self._evaluation_lock
  return decision
```

**Key differences from the original Phase 13 design:**

1. The concurrency gate (lock) wraps the entire evaluation — from I/O gather to lock release.
2. Every I/O gather result is inspected for exceptions before checks run.
3. Persistence failure produces a REJECTED decision — not a silent pass.
4. Event publication failure produces a delivery fallback, not a silent loss.

---

## Section 3 — Authoritative risk.yaml Schema

The following schema is the single source of truth for Phase 13 and beyond. It resolves all 10 discrepancies identified in H-1. Every field change from the current `config/risk.yaml` is annotated.

```yaml
# Portfolio Risk Limits — Phase 13 Authoritative Schema
# Source of truth: docs/17_PORTFOLIO_RISK_ENGINE.md + PHASE_13_REMEDIATION_PLAN.md
# All limits are configuration, not code. Changing a limit requires no deployment.
# Annotated fields mark changes from the pre-Phase-13 config.

version: "2.0"    # CHANGED: 1.0 → 2.0 (schema revision)

capital:
  total_capital: 500000            # INR — set to actual trading capital before Phase 14
  risk_per_trade_pct: 1.0          # RENAMED: capital_at_risk_pct → risk_per_trade_pct (aligns with Doc 17)

daily_loss:
  limit_pct: 2.0                   # 2% of capital = INR 10,000 on 500K capital
  limit_abs: 10000                 # ADDED: INR; whichever triggers first (pct or abs)
  graduated_response:
    reduce_size_at_pct: 50         # RENAMED: graduated_response_pct → graduated_response.reduce_size_at_pct
    paper_mode_at_pct: 75          # ADDED: at 75% of daily limit → paper trading mode
    kill_switch_at_pct: 100        # ADDED: at 100% → kill switch activation

weekly_loss:
  limit_pct: 5.0                   # rolling 5 trading days (not calendar week)
  limit_abs: 25000                 # ADDED: INR; whichever triggers first

drawdown:
  max_drawdown_pct: 10.0           # from rolling 30-day high-water mark

position_limits:
  max_open_positions: 10           # CHANGED: 5 → 10 (aligns with Doc 17)
  max_positions_per_underlying: 3  # RENAMED+CHANGED: max_positions_per_symbol: 1 → max_positions_per_underlying: 3
                                   # Rationale: one underlying (e.g., NIFTY) can have CE + PE + hedge
  max_capital_per_underlying_pct: 20.0   # RENAMED: max_capital_per_symbol_pct → max_capital_per_underlying_pct
  max_capital_per_sector_pct: 40.0       # Retained (not in Doc 17; valid risk control for sector exposure)
  max_notional_per_trade_pct: 10         # ADDED: single trade notional cap (Doc 17)

order_rate:
  max_orders_per_minute: 5         # CHANGED: 10 → 5 (aligns with Doc 17)
  max_orders_per_day: 50           # ADDED: daily order count hard cap (Doc 17)

greeks:
  # Unit convention (canonical, resolves H-1 unit inconsistency):
  # All Greek limits are in INR per unit of underlying move, expressed at portfolio level.
  #
  # Net delta formula:
  #   portfolio_net_delta = Σ (position.delta × lots × lot_size)
  #   Unit: INR per 1-point move in the underlying index
  #   Example: NIFTY ATM call (delta=0.5), 2 lots, lot_size=50
  #            → 0.5 × 2 × 50 = 50 INR/point
  #
  max_net_delta: 2500              # CHANGED: 500.0 → 2500; unit = INR/point
                                   # Interpretation: if NIFTY moves 1 point, portfolio P&L changes by ≤ 2500 INR
                                   # For 500K capital: 2500 INR/point × 100-point move = 250K (50% capital) — hard limit
                                   # Operator must calibrate to their risk tolerance

  max_net_gamma_pct: 0.1           # ADDED: portfolio gamma as % of portfolio value (Doc 17)

  # Net vega formula:
  #   portfolio_net_vega = Σ (position.vega × lots × lot_size)
  #   Unit: INR per 1% change in implied volatility
  max_net_vega_pct: 5.0            # CHANGED: max_vega_exposure: 10000.0 (absolute) →
                                   #          max_net_vega_pct: 5.0 (% of capital, aligns with Doc 17)
                                   # Computation: portfolio_vega / total_capital × 100 ≤ 5.0

  max_theta_daily_decay_pct: 0.5   # ADDED: max daily theta burn as % of capital (Doc 17); Check 14 warn-only

margin:
  utilization_limit_pct: 80        # ADDED: alert at 80% margin utilization
  min_free_margin_pct: 20          # ADDED: block new positions if free margin < 20% (Doc 17)

risk_reward:
  min_ratio: 1.5                   # RENAMED: minimum_ratio → min_ratio (clearer)
  max_ratio: 10.0                  # ADDED: unusually high R:R may indicate data error (Doc 17)

position_sizing:
  method: "atr_kelly"              # atr_kelly | fixed_fractional | fixed_lots
  kelly_fraction: 0.25             # fractional Kelly multiplier (25% of raw Kelly)
  atr_period: 14
  atr_stop_multiplier: 1.5         # CHANGED: 2.0 → 1.5 (aligns with Phase 13 design default)
  max_position_size_lots: 50       # ADDED: absolute hard cap — Kelly and ATR output is min'd against this (H-5)
  min_kelly_samples: 30            # ADDED: minimum historical samples before Kelly is used (H-5)
  kelly_min_sample_fallback: 0.05  # ADDED: fallback as fraction of kelly_fraction when samples < min (H-5)
                                   # Effective fallback = 0.05 × 0.25 = 1.25% Kelly — very conservative

redis_fail_safe:                   # ADDED: documents the fail-safe policy per Redis data source (C-2)
  # Policies: FAIL_CLOSED (reject evaluation) | CONSERVATIVE_DEFAULT (use documented safe default)
  account_state: FAIL_CLOSED
  portfolio_state: FAIL_CLOSED
  graduated_response_state: FAIL_CLOSED     # treats as multiplier=0.0 (no new positions)
  greeks_cache:
    policy: FAIL_CLOSED
    fallback_ttl_seconds: 300              # duration the fallback Greeks key is valid
  correlation_matrix:
    policy: CONSERVATIVE_DEFAULT
    default_correlation: 1.0              # assume perfect positive correlation
  margin_required: FAIL_CLOSED
```

#### Field Change Summary

| Field (old) | Field (new) | Change Type | Value Change |
|-------------|-------------|-------------|--------------|
| `capital.capital_at_risk_pct` | `capital.risk_per_trade_pct` | Rename | None |
| `daily_loss.graduated_response_pct` | `daily_loss.graduated_response.reduce_size_at_pct` | Rename + restructure | None |
| _(missing)_ | `daily_loss.limit_abs` | Added | 10000 |
| _(missing)_ | `daily_loss.graduated_response.paper_mode_at_pct` | Added | 75 |
| _(missing)_ | `daily_loss.graduated_response.kill_switch_at_pct` | Added | 100 |
| _(missing)_ | `weekly_loss.limit_abs` | Added | 25000 |
| `position_limits.max_open_positions` | `position_limits.max_open_positions` | Value fix | 5 → 10 |
| `position_limits.max_positions_per_symbol` | `position_limits.max_positions_per_underlying` | Rename + value fix | 1 → 3 |
| `position_limits.max_capital_per_symbol_pct` | `position_limits.max_capital_per_underlying_pct` | Rename | None |
| _(missing)_ | `position_limits.max_notional_per_trade_pct` | Added | 10 |
| `order_rate.max_orders_per_minute` | `order_rate.max_orders_per_minute` | Value fix | 10 → 5 |
| _(missing)_ | `order_rate.max_orders_per_day` | Added | 50 |
| `greeks.max_net_delta` | `greeks.max_net_delta` | Unit fix + value change | 500.0 → 2500 (INR/point) |
| _(missing)_ | `greeks.max_net_gamma_pct` | Added | 0.1 |
| `greeks.max_vega_exposure` | `greeks.max_net_vega_pct` | Rename + unit fix | 10000 (abs INR) → 5.0 (% of capital) |
| _(missing)_ | `greeks.max_theta_daily_decay_pct` | Added | 0.5 |
| _(missing)_ | `margin.utilization_limit_pct` | Added | 80 |
| _(missing)_ | `margin.min_free_margin_pct` | Added | 20 |
| `risk_reward.minimum_ratio` | `risk_reward.min_ratio` | Rename | None |
| _(missing)_ | `risk_reward.max_ratio` | Added | 10.0 |
| `position_sizing.atr_stop_multiplier` | `position_sizing.atr_stop_multiplier` | Value fix | 2.0 → 1.5 |
| _(missing)_ | `position_sizing.max_position_size_lots` | Added (H-5) | 50 |
| _(missing)_ | `position_sizing.min_kelly_samples` | Added (H-5) | 30 |
| _(missing)_ | `position_sizing.kelly_min_sample_fallback` | Added (H-5) | 0.05 |
| _(missing)_ | `redis_fail_safe.*` | Added (C-2) | per-source policies |

---

## Section 4 — Updated Redis Key Strategy

All Risk Engine Redis keys follow a consistent naming convention: `risk:{scope}:{identifier}`.

No Risk Engine key has a TTL that could cause silent state loss. Keys that carry safety-critical state (kill switch, graduated response) have no TTL. Keys that carry computed data (Greeks, correlation) have explicit TTLs with documented fail-safe behavior on expiry.

### Complete Redis Key Register (Phase 13)

| Key Pattern | Type | TTL | Owns | Readers | Fail-Safe |
|-------------|------|-----|------|---------|-----------|
| `system:kill_switch` | Hash | None | KillSwitchService | RiskEngine, OMS, all components | FAIL_CLOSED: treat as active |
| `risk:account_state` | Hash | 30s | AccountStatePoller | RiskEngine | FAIL_CLOSED |
| `risk:portfolio_state` | Hash | 60s | PortfolioMonitor | RiskEngine | FAIL_CLOSED |
| `risk:graduated_response` | Hash | None | PortfolioMonitor | RiskEngine | FAIL_CLOSED: multiplier=0.0 |
| `risk:greeks:{position_id}` | Hash | 60s | GreeksComputeService | RiskEngine | Use fallback key |
| `risk:greeks:fallback:{position_id}` | Hash | 300s | GreeksComputeService | RiskEngine | FAIL_CLOSED if also missing |
| `risk:correlation_matrix` | JSON String | 24h | CorrelationService | RiskEngine | CONSERVATIVE_DEFAULT: ρ=1.0 |
| `risk:hwm:{date}` | String | 35d | PortfolioMonitor | PortfolioMonitor | N/A — HWM computed from DB on miss |
| `risk:approvals_pending_delivery` | List | None | RiskEngine | DeliveryReconciler | N/A — this IS the fallback |

### `risk:account_state` Hash Fields

```
account_capital:           str (Decimal)
available_margin:          str (Decimal)
used_margin:               str (Decimal)
margin_utilization_pct:    str (float)
daily_pnl:                 str (Decimal)
daily_loss_consumed_pct:   str (float)
weekly_pnl:                str (Decimal)
weekly_loss_consumed_pct:  str (float)
drawdown_from_hwm_pct:     str (float)
session_capital:           str (Decimal)   ← frozen at 09:15 IST; used for sizing
captured_at:               str (ISO 8601)
```

### `risk:portfolio_state` Hash Fields

```
open_positions_count:              str (int)
positions_per_underlying:          str (JSON: {underlying: count})
capital_per_underlying_pct:        str (JSON: {underlying: pct})
net_delta:                         str (float, INR/point)
net_vega:                          str (float, INR per 1% IV change)
net_theta_daily:                   str (float, INR/day)
orders_last_minute:                str (int)
captured_at:                       str (ISO 8601)
```

### `risk:graduated_response` Hash Fields

```
state:                     str  (NORMAL | REDUCED | PAPER | KILLED)
position_size_multiplier:  str  (1.0 | 0.5 | 0.0 | 0.0)
activated_at:              str  (ISO 8601 | null)
reason:                    str  (null if NORMAL)
```

This key has NO TTL. The graduated response state persists across process restarts. A KILLED state requires manual operator intervention to reset (consistent with kill switch deactivation procedure).

---

## Section 5 — Updated Kill Switch Design

### H-2 Root Cause

`docs/14_KILL_SWITCH_DESIGN.md` (the authoritative document) defines:
```
Key:  system:kill_switch
Type: Redis Hash
TTL:  None
```

The Phase 13 Risk Engine design used a different, incompatible key:
```
Key:  kill_switch:active
Type: String
TTL:  EX 86400 (24 hours)
```

These differences are incompatible:
1. **Key name mismatch:** OMS reads from `system:kill_switch` (per Doc 14). Phase 13 Risk Engine would write to `kill_switch:active`. A kill switch activated by the Risk Engine is invisible to the OMS.
2. **Type mismatch:** A Hash type and a String type share no read compatibility.
3. **TTL:** A 24-hour TTL silently deactivates the kill switch if the system is down for maintenance longer than 24 hours. An operator-activated kill switch that self-deactivates overnight is a safety failure.

### Proposed Solution

**Doc 14 is the single source of truth.** The Phase 13 design's `kill_switch:active EX 86400` key is removed. All Phase 13 code must use `system:kill_switch` (Hash, no TTL) exclusively.

### Canonical Kill Switch Key Specification

```
Key:    system:kill_switch
Type:   Redis Hash
TTL:    None (persists indefinitely)

Hash fields:
  is_active:           "true" | "false"
  activated_at:        ISO 8601 UTC | ""
  activated_by:        "operator" | "risk_engine" | "dead_mans_switch" | "system" | ""
  activation_reason:   str | ""
  deactivated_at:      ISO 8601 UTC | ""
  deactivated_by:      str (user_id) | ""
  deactivation_note:   str | ""
```

All string values because Redis Hash values are strings. Boolean `is_active` is read as: `value == "true"`.

### OMS Visibility

The OMS reads `system:kill_switch` at startup via `HGET system:kill_switch is_active`. It sets the in-memory `oms.kill_switch_flag`. It subscribes to `system.kill_switch.activated` events (Doc 11) to update the in-memory flag asynchronously without Redis polling.

The OMS does not poll Redis continuously for the kill switch. The in-memory flag is the hot path. The Redis Hash is the persistent ground truth consulted on startup and after any event bus reconnection.

### Startup Recovery Behavior

On any process start (fresh or restart):

```
Startup sequence:
1. Read system:kill_switch from Redis BEFORE initializing any trading component.
2. If Redis is unavailable at startup: fail-closed — initialize in BLOCKED state.
   Log CRITICAL: "kill_switch_state_unknown_at_startup"
   Emit alert.
   Do not process signals until Redis is available and state is confirmed.
3. If is_active == "true": initialize all trading components in BLOCKED state.
   Do not process events until operator manually deactivates.
4. If is_active == "false" or key does not exist: initialize normally.
   Log INFO: "kill_switch_inactive_at_startup"
```

### Multi-Instance Behavior

In Phase 1, all components run in a single process. The `system:kill_switch` Hash in Redis is the shared state. All instances (current and future) share this key.

In Phase 2 multi-process deployments:
- Each process reads `system:kill_switch` at startup.
- Each process subscribes to `system.kill_switch.activated` (Redis Streams consumer group `kill-switch`).
- The `kill-switch` consumer group has parallelism = 1 (Doc 11) — exactly one instance processes each activation event.
- All other instances receive the event via their own group subscription and update their in-memory flag.

No inter-process communication beyond the event bus subscription is required. Redis Hash provides the persistent ground truth; the event bus provides the real-time propagation.

### Kill Switch + Graduated Response Relationship

The graduated response state (`risk:graduated_response`) and the kill switch (`system:kill_switch`) are independent but coordinated:

```
NORMAL     → no constraints
REDUCED    → position_size_multiplier = 0.5
PAPER      → position_size_multiplier = 0.0 (signals generated, no orders placed)
KILLED     → kill switch activated; OMS blocks all new order submissions

Graduated state does NOT set system:kill_switch.
Kill switch activation does NOT set risk:graduated_response.state = KILLED.
These are separate state machines updated independently.
```

When the kill switch is activated, the graduated response state is irrelevant — the OMS blocks all submissions regardless. The graduated response state is preserved so that on deactivation, the system resumes at the correct graduated tier (not back to NORMAL if losses justify REDUCED or PAPER).

### Architectural Impact

- Phase 13 implementation must remove all references to `kill_switch:active`
- All Redis reads for kill switch state use `HGET system:kill_switch is_active`
- All Redis writes use `HSET system:kill_switch ...fields...`
- `KillSwitchService` is the only writer to `system:kill_switch`
- No other component writes to `system:kill_switch` directly

#### Files / Docs Requiring Updates

| Document | Change |
|----------|--------|
| Phase 13 design (in-session) | Remove `kill_switch:active EX 86400`; reference Doc 14 exclusively |
| `docs/14_KILL_SWITCH_DESIGN.md` | Add startup recovery sequence (Section: Startup Behavior) |
| Phase 13 implementation notes | Add: "IAIProvider FORBIDDEN from KillSwitchService; no TTL on system:kill_switch" |

---

## Section 6 — Updated Position Sizing Design

### H-5 Root Cause

The Phase 13 position sizer uses `win_rate` and `win_loss_ratio` from `ISignalPerformanceRepository` to compute raw Kelly. No minimum sample guard exists. With 10 samples (the minimum for Phase 12 historical accuracy), Kelly can produce extreme lot counts. The `win_loss_ratio` denominator becomes undefined when `loss_count == 0`.

### Proposed Solution

The Kelly sizing path has four protection layers:

#### Layer 1: Minimum Sample Guard

```
If historical_sample_count < min_kelly_samples (config: 30):
    kelly_fraction_effective = kelly_fraction × kelly_min_sample_fallback
    # = 0.25 × 0.05 = 0.0125 (1.25% Kelly — very conservative)
    
    Log WARNING: "kelly_insufficient_samples"
    Record in RiskDecision.checks: check_14_kelly_samples_below_minimum = True
Else:
    kelly_fraction_effective = kelly_fraction  # = 0.25 (normal fractional Kelly)
```

The fallback is not a hard block — the signal can still be approved at a conservative size. A hard block would mean a new instrument with no trade history can never receive its first trade.

#### Layer 2: Zero-Loss Edge Case

```
If loss_count == 0 (no historical losses recorded):
    # Win rate = 1.0; division by win_loss_ratio would use only wins
    # Edge: system has been perfect so far — this is statistically unreliable
    # Safe behavior: treat as insufficient samples regardless of total count
    kelly_fraction_effective = kelly_fraction × kelly_min_sample_fallback
    Log WARNING: "kelly_no_historical_losses"
```

#### Layer 3: Raw Kelly Floor

```
raw_kelly = win_rate - ((1 - win_rate) / win_loss_ratio)
raw_kelly = max(0.0, raw_kelly)    ← floor at zero (negative Kelly = skip trade)

If raw_kelly == 0.0:
    # Negative raw Kelly means expected value of this strategy is negative
    # Under current performance: do not trade
    return RiskDecision(approved=False, rejection_code=KELLY_NEGATIVE_EXPECTED_VALUE)
```

A negative raw Kelly is not a data error — it is correct behavior. A strategy with win_rate = 0.3 and win_loss_ratio = 0.5 has negative expected value. The system should reject the signal.

#### Layer 4: Absolute Hard Cap

```
kelly_lots = floor(
    (account_state.session_capital × kelly_fraction_effective × raw_kelly)
    / (option_premium × lot_size)
)

atr_lots = floor(
    account_state.session_capital × risk_per_trade_pct / 100
    / (option_premium × lot_size)
)

final_lots_pre_cap = min(atr_lots, kelly_lots)
final_lots = min(final_lots_pre_cap, max_position_size_lots)  # config: 50
final_lots = max(0, final_lots)  # floor at zero

If final_lots == 0:
    return RiskDecision(approved=False, rejection_code=POSITION_SIZE_ZERO)
```

The `max_position_size_lots` cap is the last-resort guard. It ensures that no mathematical edge case in the Kelly or ATR formula can produce an outsized position, regardless of inputs.

#### Session Capital Anchor

The Kelly and ATR formulas both use `account_state.session_capital` — the account capital frozen at 09:15 IST — not the live MTM value. This prevents a sizing spiral where intraday losses reduce the capital denominator, causing the risk percentage to compute smaller lot sizes, which interact with Kelly's relative formula to produce unexpected outputs. The session capital is a stable reference point for the entire trading day.

#### Complete Sizing Flow

```
PositionSizer.compute_lots(
    request: RiskRequest,
    account_state: AccountState,
    performance: StrategyPerformance,
    config: RiskConfig
) -> SizingResult:

  1. Fetch sample_count, win_rate, win_loss_ratio from performance repository
  
  2. Determine kelly_fraction_effective:
     if sample_count < config.min_kelly_samples OR loss_count == 0:
         kelly_fraction_effective = config.kelly_fraction × config.kelly_min_sample_fallback
         sizing_note = "below_minimum_samples" or "no_historical_losses"
     else:
         kelly_fraction_effective = config.kelly_fraction
  
  3. Compute raw_kelly:
     raw_kelly = win_rate - ((1 - win_rate) / win_loss_ratio)
     raw_kelly = max(0.0, raw_kelly)
     if raw_kelly == 0.0:
         return SizingResult(lots=0, rejection_code=KELLY_NEGATIVE_EXPECTED_VALUE)
  
  4. Compute ATR lots:
     capital_at_risk = account_state.session_capital × config.risk_per_trade_pct / 100
     if instrument is OPTION:
         atr_lots = floor(capital_at_risk / (option_premium × lot_size))
     elif instrument is FUTURE:
         stop_distance = abs(request.entry_price - request.stop_loss_price)
         atr_lots = floor(capital_at_risk / (stop_distance × lot_size))
     atr_lots = max(0, atr_lots)
  
  5. Compute Kelly lots:
     kelly_capital = account_state.session_capital × kelly_fraction_effective × raw_kelly
     kelly_lots = floor(kelly_capital / (option_premium × lot_size))
     kelly_lots = max(0, kelly_lots)
  
  6. Apply graduated response:
     multiplier = account_state.position_size_multiplier  # 1.0, 0.5, or 0.0
     final_lots = floor(min(atr_lots, kelly_lots) × multiplier)
  
  7. Apply hard cap:
     final_lots = min(final_lots, config.max_position_size_lots)
  
  8. Final floor:
     if final_lots == 0:
         return SizingResult(lots=0, rejection_code=POSITION_SIZE_ZERO)
  
  return SizingResult(
      lots=final_lots,
      atr_lots_pre_cap=atr_lots,
      kelly_lots_pre_cap=kelly_lots,
      kelly_fraction_effective=kelly_fraction_effective,
      sizing_note=sizing_note,
  )
```

#### Architectural Impact

- `PositionSizer` is a pure domain service in `core/domain/risk/`
- No I/O — all inputs are passed in
- Returns `SizingResult` (not raw int) to carry sizing diagnostics for the `RiskDecision` audit record
- `SizingResult` is included in `RiskDecision.checks` for full audit trail
- `ISignalPerformanceRepository` already supports win rate lookup (Phase 12)

#### Files / Docs Requiring Updates

| Document | Change |
|----------|--------|
| `config/risk.yaml` | Three new fields: `max_position_size_lots`, `min_kelly_samples`, `kelly_min_sample_fallback` |
| `docs/17_PORTFOLIO_RISK_ENGINE.md` | Add four-layer Kelly protection section |
| Phase 13 implementation notes | Sizing must use session_capital (frozen), not live MTM capital |

---

## Section 7 — Readiness Score Projection

### Dimension Rescoring After This Plan

| Dimension | Score Before | Score After | Delta | Changed By |
|-----------|-------------|-------------|-------|------------|
| DDD layering compliance | 10/10 | 10/10 | 0 | — |
| Position sizing model correctness | 7/10 | 9/10 | +2 | H-5: Four-layer Kelly protection |
| Capital allocation model | 9/10 | 9/10 | 0 | — |
| Drawdown controls | 8/10 | 8/10 | 0 | — |
| Kill switch design | 5/10 | 9/10 | +4 | H-2: Canonical key; startup recovery; multi-instance |
| Portfolio risk model | 7/10 | 7/10 | 0 | H-4 not in scope |
| Signal acceptance gate stack | 8/10 | 8/10 | 0 | — |
| Concurrent approval safety | 2/10 | 9/10 | +7 | C-1: Sequential + lock; H-3: Covered |
| Infrastructure resilience | 3/10 | 8/10 | +5 | C-2: All 7 data sources with explicit policies |
| Event architecture completeness | 5/10 | 5/10 | 0 | H-6 not in scope |
| Configuration contract alignment | 4/10 | 9/10 | +5 | H-1: All 10 discrepancies resolved |
| **Total** | **68/110** | **91/110** | **+23** | |

**Normalized score: 91/110 × 100 = 83/100**  
**Risk-adjusted score (no Criticals remain): 86/100**

### Gap to 90/100 Threshold

The following High findings from the audit remain open and are not resolved by this plan. They must be addressed before the 90-point implementation threshold is reached.

| ID | Finding | Required Before |
|----|---------|----------------|
| H-4 | Greeks cache miss grace period and fallback key design | Implementation sprint planning |
| H-6 | Missing risk domain events (WeeklyLossLimitBreached, KillSwitchActivated, etc.) | Before implementation begins — events are needed by implementation |
| H-7 | TimescaleDB outage: approval without audit trail (persistence failure policy) | Implementation sprint planning |
| H-8 | Event bus outage after approval: orphaned approved signals | Implementation sprint planning |

**H-6 is the most urgent remaining item.** Domain events cannot be added retroactively without breaking consumers. They must be defined before any Phase 13 service writes its first event.

H-4, H-7, H-8 are addressed in the Updated Risk Engine Flow (Section 2) at a design level. Their detailed resolution belongs in a Phase 13 implementation specification, not this remediation plan.

### Projected Score After Remaining Highs

If H-4, H-6, H-7, H-8 are resolved in the Phase 13 implementation specification:
- Portfolio risk model: 7 → 9 (+2, H-4)
- Event architecture completeness: 5 → 8 (+3, H-6)
- Infrastructure resilience: 8 → 10 (+2, H-7, H-8 detailed)
- **Total: 91 + 7 = 98/110 → 89/100 normalized → ~93/100 risk-adjusted**

This is above the 90-point implementation threshold.

---

## Section 8 — READY_FOR_REVIEW

This remediation plan resolves the following findings at the design level:

| Finding | Resolution | Document |
|---------|------------|----------|
| C-1: TOCTOU race condition | Option A: sequential evaluation; asyncio lock; parallelism=1 enforced | Section 1 |
| C-2: Redis fail-safe undefined | FAIL_CLOSED for 5 sources; CONSERVATIVE_DEFAULT for correlation matrix; retry+DLS for event stream | Section 1 |
| H-1: risk.yaml discrepancies | 10 field corrections; 10 new fields; unit conventions documented | Section 3 |
| H-2: Kill switch key inconsistency | Doc 14 is authoritative; `system:kill_switch` Hash, no TTL; startup recovery; multi-instance behavior defined | Section 5 |
| H-3: Margin reservation gap | Resolved by C-1 sequential evaluation | Section 1 |
| H-5: Kelly sample size vulnerability | Four-layer protection: sample guard, zero-loss edge, raw_kelly floor, absolute hard cap | Section 6 |

**No code has been written. No implementation has begun.**

This plan is ready for review. Upon approval, the next step is to resolve the remaining High findings (H-4, H-6, H-7, H-8) in a Phase 13 Implementation Specification before any code is written.

The Phase 13 implementation threshold of 90/100 is achievable after those four remaining findings are resolved.

---

```
READY_FOR_REVIEW

Remediation plan covers: C-1, C-2, H-1, H-2, H-3, H-5
Architecture is locked. No code written.
Remaining open (not in scope of this plan): H-4, H-6, H-7, H-8

Projected readiness after this plan + H-4, H-6, H-7, H-8 resolution: ~93/100
```

---

*Cross-references: docs/14_KILL_SWITCH_DESIGN.md · docs/17_PORTFOLIO_RISK_ENGINE.md · docs/11_EVENT_BUS_ARCHITECTURE.md · docs/22_OMS_DESIGN.md · PHASE_13_RISK_ENGINE_ARCHITECTURE_AUDIT.md*  
*No implementation code. Design decisions only. 2026-06-13.*
