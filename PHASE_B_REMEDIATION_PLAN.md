# Phase B Remediation Plan

**Date:** 2026-06-13  
**Status:** AWAITING APPROVAL  
**Source:** PHASE_B_RISK_LOGIC_AUDIT.md  
**Scope:** Six mandatory remediations required before Phase C is approved  
**Instruction:** Do not generate implementation code. Wait for approval.

---

## Remediation Index

| # | ID | Title | Priority | Files Impacted |
|---|-----|-------|---------|----------------|
| 1 | C1 | Absolute loss limits not enforced | Mandatory — Phase C Blocker | `risk_limit_checker.py`, `test_risk_limit_checker.py` |
| 2 | H2 | `max_orders_per_day` dead — PortfolioState missing daily order count | Mandatory — Phase C Blocker | `portfolio_state.py`, `risk_limit_checker.py`, `test_portfolio_state.py`, `test_risk_limit_checker.py` |
| 3 | H1 | GROSS correlation formula rejects risk-reducing trades | Mandatory — Phase C Blocker | `risk_limit_checker.py`, `test_risk_limit_checker.py` |
| 4 | M3 | Capital concentration tests current exposure, not projected post-trade | Mandatory — Phase C Blocker | `risk_limit_checker.py`, `test_risk_limit_checker.py` |
| 5 | H3 | Greek unit contract undefined — GreeksSnapshot delta ambiguous | Design Update | `greeks_snapshot.py` |
| 6 | M4 | No enforcement that Phase D must respect `is_warning=True` | Design Update | `risk_decision.py`, `test_risk_decision.py` |

---

## Remediation 1 — C1: Absolute Loss Limits Not Enforced

### Root Cause

`check_daily_loss` and `check_weekly_loss` derive a percentage by dividing `abs(daily_pnl)` by `session_capital`. They compare this to `config.daily_loss.limit_pct` (2.0%) and `config.weekly_loss.limit_pct` (5.0%) respectively.

Neither function reads `config.daily_loss.limit_abs` (10,000 INR) or `config.weekly_loss.limit_abs` (25,000 INR). These fields are loaded into `RiskConfig` but have zero callers in Phase B.

Doc 17 defines the limit as: _"whichever triggers first (pct or abs)"_. Only the percentage path is implemented.

**Why the bug is invisible at default config:**

For the default `total_capital: 500,000` and `limit_pct: 2.0`, the triggers are:
- Percentage trigger: `500,000 × 2% = 10,000 INR`
- Absolute trigger: `10,000 INR`

They are identical. The missing check is undetectable until capital is increased:

| Capital | limit_pct fires at | limit_abs fires at | Unprotected gap |
|---------|-------------------|--------------------|-----------------|
| 500K | 10,000 INR | 10,000 INR | None |
| 1M | 20,000 INR | 10,000 INR | 10,000 INR |
| 5M | 100,000 INR | 10,000 INR | 90,000 INR |

**The pre-computed fields exist but are unused:**

`AccountState` already carries:
- `daily_loss_consumed_pct: float` — documented as `abs(daily_pnl) / daily_loss_limit_abs × 100`
- `weekly_loss_consumed_pct: float` — same basis for weekly

When `daily_loss_consumed_pct >= 100.0`, the absolute daily limit has been reached. `check_daily_loss` does not read this field. It recomputes the wrong thing.

### Proposed Fix

Both checks must enforce two independent conditions. Either condition failing causes rejection. The absolute limit takes precedence in evaluation order and in the failure message when it is the binding constraint.

**`check_daily_loss` — updated logic:**

```
Condition 1 (Percentage):
    current_loss_pct = abs(daily_pnl) / session_capital × 100  (only when daily_pnl < 0)
    pct_breached = current_loss_pct >= config.daily_loss.limit_pct

Condition 2 (Absolute — takes precedence):
    abs_breached = account.daily_loss_consumed_pct >= 100.0
    (uses the pre-computed field already normalised against limit_abs)

passed = not abs_breached and not pct_breached

Failure message priority:
    if abs_breached:   "Daily loss INR {abs(daily_pnl):.0f} at or above absolute limit {limit_abs} INR"
    elif pct_breached: "Daily loss {current_loss_pct:.2f}% at or above limit {limit_pct:.2f}%"
```

**`check_weekly_loss` — same pattern:**

```
Condition 1 (Percentage):
    current_loss_pct = abs(weekly_pnl) / session_capital × 100  (only when weekly_pnl < 0)
    pct_breached = current_loss_pct >= config.weekly_loss.limit_pct

Condition 2 (Absolute — takes precedence):
    abs_breached = account.weekly_loss_consumed_pct >= 100.0

passed = not abs_breached and not pct_breached
```

The `current_value` field in `RiskCheckResult` should carry the binding value:
- When `abs_breached`: report `daily_loss_consumed_pct` as `current_value`, `100.0` as `limit_value`
- When only `pct_breached`: report `current_loss_pct` as `current_value`, `limit_pct` as `limit_value`

### Files Impacted

| File | Change |
|------|--------|
| `src/core/domain/risk/risk_limit_checker.py` | Update `check_daily_loss` and `check_weekly_loss` to check both conditions |
| `tests/unit/domain/risk/test_risk_limit_checker.py` | Add new test cases (see below) |

### Test Changes Required

**New test cases for `TestCheckDailyLoss`:**

| Test name | Setup | Expected |
|-----------|-------|---------|
| `test_abs_limit_fires_before_pct_with_large_capital` | `session_capital=1_000_000`, `daily_pnl=-15_000`, `daily_loss_consumed_pct=150.0` | `passed=False` — absolute fires (15K > 10K limit_abs) even though pct = 1.5% < 2.0% |
| `test_abs_limit_at_100_pct_fails` | `daily_loss_consumed_pct=100.0` | `passed=False` |
| `test_abs_limit_below_100_passes_when_pct_ok` | `daily_loss_consumed_pct=90.0`, `session_capital=500_000`, `daily_pnl=-4_500` | `passed=True` (both below their limits) |
| `test_pct_fires_when_abs_not_reached` | `session_capital=500_000`, `daily_pnl=-10_001`, `daily_loss_consumed_pct=100.01` | `passed=False` — both fire together at default capital |
| `test_failure_message_labels_abs_limit_when_binding` | `daily_loss_consumed_pct=150.0` | `current_value == daily_loss_consumed_pct`, `limit_value == 100.0` |

**New test cases for `TestCheckWeeklyLoss`:**

| Test name | Setup | Expected |
|-----------|-------|---------|
| `test_weekly_abs_limit_fires_with_large_capital` | `session_capital=1_000_000`, `weekly_pnl=-30_000`, `weekly_loss_consumed_pct=120.0` | `passed=False` |
| `test_weekly_abs_limit_at_100_pct_fails` | `weekly_loss_consumed_pct=100.0` | `passed=False` |

**Existing test to verify is unaffected:**

`test_loss_at_limit_fails` — at default `session_capital=500_000`, both limits coincide at the same INR value. Must still pass.

---

## Remediation 2 — H2: `max_orders_per_day` Dead Config

### Root Cause

`PortfolioState` has one order-rate field: `orders_last_minute: int`. `check_order_rate` reads this and compares to `config.order_rate.max_orders_per_minute`. The daily cap (`config.order_rate.max_orders_per_day: 50`) is never enforced because `PortfolioState` has no field to carry the day's total order count. The config field has zero callers.

A bot running at the maximum per-minute rate (4 orders/min) for a 375-minute NSE session can place 1,500 orders. The per-day cap of 50 provides no protection.

### Proposed Fix

**Step 1 — Add `orders_today: int` to `PortfolioState`:**

Add the field adjacent to `orders_last_minute`. Apply the same invariant (`>= 0`).

New `PortfolioState` field:
```
orders_today: int    — Count of orders placed since midnight IST for the current trading day.
```

The `RedisPortfolioStateRepository` (Phase C/D) is responsible for writing this field from Redis. The `risk:portfolio_state` Hash must include `orders_today` as a key.

**Step 2 — Update `check_order_rate` to enforce both limits:**

```
Condition 1 (Per-minute rate):
    rate_ok = portfolio.orders_last_minute < config.order_rate.max_orders_per_minute

Condition 2 (Daily total):
    daily_ok = portfolio.orders_today < config.order_rate.max_orders_per_day

passed = rate_ok and daily_ok

Failure message:
    if not rate_ok:   "Order rate {orders_last_minute}/min at or above limit {max_orders_per_minute}/min"
    elif not daily_ok: "Daily order count {orders_today} at or above daily limit {max_orders_per_day}"
```

Both conditions must pass. Either can independently trigger failure.

The `current_value` in `RiskCheckResult` should carry the binding value:
- When rate fails: `float(portfolio.orders_last_minute)`, `limit_value = float(max_orders_per_minute)`
- When only daily fails: `float(portfolio.orders_today)`, `limit_value = float(max_orders_per_day)`

### Files Impacted

| File | Change |
|------|--------|
| `src/core/domain/risk/portfolio_state.py` | Add `orders_today: int` field with `>= 0` invariant |
| `src/core/domain/risk/risk_limit_checker.py` | Update `check_order_rate` to check both conditions |
| `tests/unit/domain/risk/test_portfolio_state.py` | Add `orders_today` construction and invariant tests |
| `tests/unit/domain/risk/test_risk_limit_checker.py` | Update `_make_portfolio` factory; add new test cases |

### Test Changes Required

**`portfolio_state.py` tests (`test_portfolio_state.py`):**

| Test name | Expected |
|-----------|---------|
| `test_orders_today_zero_valid` | Construction succeeds with `orders_today=0` |
| `test_orders_today_positive_valid` | Construction succeeds with `orders_today=49` |
| `test_orders_today_negative_raises` | `RiskInvariantError` raised for `orders_today=-1` |

**`test_risk_limit_checker.py` — factory update:**

`_make_portfolio()` default factory must add `orders_today=0`. All existing tests that pass `_make_portfolio()` continue to work without changes.

**New test cases for `TestCheckOrderRate`:**

| Test name | Setup | Expected |
|-----------|-------|---------|
| `test_daily_limit_at_cap_fails` | `orders_today=max_orders_per_day` | `passed=False` |
| `test_daily_limit_above_cap_fails` | `orders_today=max_orders_per_day + 5` | `passed=False` |
| `test_daily_limit_below_cap_passes` | `orders_today=max_orders_per_day - 1` | `passed=True` |
| `test_rate_ok_daily_limit_exceeded_fails` | `orders_last_minute=0`, `orders_today=max_orders_per_day` | `passed=False` |
| `test_rate_exceeded_daily_ok_fails` | `orders_last_minute=max_orders_per_minute`, `orders_today=0` | `passed=False` |
| `test_both_within_limits_passes` | `orders_last_minute=0`, `orders_today=0` | `passed=True` |
| `test_current_value_is_daily_when_daily_is_binding` | daily cap exceeded, rate ok | `current_value == orders_today` |

**Existing tests to update:**

All existing `TestCheckOrderRate` tests use `_make_portfolio(orders_last_minute=...)` via the factory. After adding `orders_today=0` as the default, the existing tests are unaffected.

---

## Remediation 3 — H1: GROSS Correlation Formula Incorrectly Rejects Risk-Reducing Trades

### Root Cause

The current GROSS formulation:
```
correlated_exposure = (|portfolio.net_delta| + |new_delta_abs|) × max_rho
```

Uses absolute values for both the existing portfolio delta and the new position delta. It does not distinguish whether the new trade increases or decreases directional exposure.

**The false rejection scenario:**

```
portfolio.net_delta = -2,490   (heavily short; just 10 below the -2,500 limit)
new LONG CALL:  delta = +25   (opposing direction — would reduce net delta to -2,465)
max_rho = 1.0  (same underlying; also fired when matrix is empty → CONSERVATIVE_DEFAULT)

Check 8 (NetDelta):   |(-2,490 + 25)| = 2,465 < 2,500 → PASS
Check 9 (Correlation): (2,490 + 25) × 1.0 = 2,515 > 2,500 → FAIL (incorrect)
```

The correlation check rejects a trade that unambiguously reduces portfolio risk. Check 8 correctly passes it. The correlation check is incorrect.

**Why the existing test does not detect this:**

`test_corr_fires_independently_of_net_delta` tests the scenario where `net_delta = -(limit - 20)` and a LONG CALL is added. This LOOKS like a risk-reducing trade but was designed to prove the GROSS formula catches an edge case. In fact, it is proving a false rejection. The test validates incorrect behavior and must be removed and replaced.

### Proposed Fix

Replace the GROSS formula with a **signed, correlation-adjusted projected net delta** formula:

```
Step 1 — Compute the new position's signed delta contribution (same as Check 8):
    direction_sign = +1.0 if LONG else -1.0
    new_delta_signed = (option_delta × lot_size × direction_sign)   for OPTION
                     = (lot_size × direction_sign)                   for FUTURE

Step 2 — Scale the existing portfolio delta by the maximum pairwise correlation:
    corr_adjusted_portfolio = portfolio.net_delta × max_rho

Step 3 — Compute effective correlated exposure:
    effective_exposure = corr_adjusted_portfolio + new_delta_signed
    correlated_exposure = abs(effective_exposure)

Step 4 — Compare to limit:
    passed = correlated_exposure < config.greeks.max_net_delta
```

**Verification against all key scenarios:**

| Scenario | net_delta | new_delta_signed | max_rho | effective | |limit| | Result |
|----------|-----------|-----------------|---------|-----------|-------|--------|
| Risk-reducing (same underlying) | −2,490 | +25 | 1.0 | −2,465 | 2,465 | 2,500 | PASS ✓ |
| Risk-increasing (same underlying) | +2,490 | +25 | 1.0 | +2,515 | 2,515 | 2,500 | FAIL ✓ |
| Cross-instrument (rho=0.85), same direction | +2,000 | +25 | 0.85 | 1,725 | 1,725 | 2,500 | PASS ✓ |
| Cross-instrument (rho=0.85), opposing direction | +2,000 | −25 | 0.85 | 1,675 | 1,675 | 2,500 | PASS ✓ |
| Empty portfolio | 0.0 | +25 | N/A | early exit | — | — | PASS ✓ |

**Formula properties:**

- When `max_rho = 1.0` (same underlying or any cache miss): the formula is identical to Check 8's projected net delta. Risk-reducing trades that pass Check 8 also pass Check 9.
- When `max_rho < 1.0` (cross-instrument with known correlation): Check 9 is **more lenient** than Check 8, correctly giving a cross-instrument correlation discount on the existing portfolio delta.
- The formula never independently fires against a trade that has already passed Check 8 for same-underlying trades (`max_rho = 1.0`).

**What Check 9 provides over Check 8:**

For cross-instrument trades, Check 9 grants a **discount** proportional to `1 - max_rho`. A NIFTY trade against a BANKNIFTY-heavy portfolio (`rho = 0.85`) sees only 85% of the portfolio delta as effective correlated exposure. This is more permissive and more correct than Check 8's treatment of all portfolio delta at face value.

**Acknowledged limitation:**

This formula uses `portfolio.net_delta` (total signed portfolio delta) scaled by `max_rho`. It cannot compute per-underlying correlated gross exposure, which would require per-underlying delta breakdown not available in `PortfolioState`. A more precise gross-exposure correlation check (requiring per-underlying delta data) is deferred to Phase 2.

### Files Impacted

| File | Change |
|------|--------|
| `src/core/domain/risk/risk_limit_checker.py` | Replace GROSS formula in `check_correlation` with signed formula above |
| `tests/unit/domain/risk/test_risk_limit_checker.py` | Remove `test_corr_fires_independently_of_net_delta`; replace with directional tests below |

### Test Changes Required

**Remove:**

| Test name | Reason |
|-----------|--------|
| `test_corr_fires_independently_of_net_delta` | Validated the false rejection. With the fixed formula, the scenario now correctly PASSES. The test must be removed. |

**Replace with:**

| Test name | Setup | Expected |
|-----------|-------|---------|
| `test_corr_allows_risk_reducing_opposing_direction` | `net_delta=-(limit-20)`, new LONG CALL with delta=+25, same underlying, empty matrix (`max_rho=1.0`) | `passed=True` — opposing direction trade passes even when portfolio is near limit |
| `test_corr_blocks_risk_increasing_near_limit` | `net_delta=+(limit-20)`, new LONG CALL with delta=+25, same underlying, empty matrix | `passed=False` — same-direction trade near limit correctly rejected |
| `test_corr_cross_instrument_discount_applied` | `net_delta=+2_400`, new NIFTY trade delta=+25, existing=BANKNIFTY, `matrix={"NIFTY":{"BANKNIFTY":0.85}}` | `passed=True` — corr_adjusted = 2_400×0.85+25 = 2,065 < 2,500 |
| `test_corr_empty_matrix_uses_conservative_default` | existing=BANKNIFTY, new=NIFTY, empty matrix | `max_rho=1.0` applied; verify via `current_value` |
| `test_corr_same_underlying_equivalent_to_net_delta_check` | Any same-underlying scenario | `current_value` must equal what Check 8 would compute as `abs(projected)` |

**Existing tests to verify unaffected:**

- `test_empty_portfolio_passes` — still passes (early exit unchanged)
- `test_same_underlying_rho_1` — still passes (125 < 2500 unchanged)
- `test_empty_matrix_uses_conservative_default` — verify it still fails in the risk-increasing direction scenario used in that test
- `test_low_correlation_passes_what_net_delta_blocks` — re-evaluate; with the new formula, cross-instrument discount may make this pass for different reasons; update comment/assertion accordingly
- `test_missing_pair_uses_conservative_default` — still passes (125 < 2500)

---

## Remediation 4 — M3: Capital Concentration Uses Current Exposure, Not Projected Post-Trade

### Root Cause

`check_capital_concentration` sub-check A compares `existing_pct` (current capital in the underlying) to `conc_limit`. It does not project what the concentration would be after the new trade is executed.

```python
existing_pct = portfolio.capital_per_underlying_pct.get(request.underlying, 0.0)
conc_ok = existing_pct < conc_limit   # tests current, not projected
```

A NIFTY position at 19% of capital passes when `conc_limit = 20%`, even if the new trade would add 2% capital to NIFTY (resulting in 21% — over the limit). The check tests the pre-trade state, not the post-trade outcome.

**The denominator discrepancy:**

`capital_per_underlying_pct` uses `total_capital` as the base (% of total capital, as documented in `PortfolioState`). The current sub-check B uses `session_capital` as the denominator for `notional_pct`. These are different denominators and cannot be directly combined for the projection without normalisation.

The projection must convert the new trade's capital-at-risk to the same `total_capital` basis as `capital_per_underlying_pct`.

### Proposed Fix

Compute the **projected** post-trade capital concentration using `total_capital` as the common denominator for both sub-checks.

**Sub-check A (concentration limit) — updated logic:**

```
# New trade capital-at-risk (1-lot risk, same as sub-check B uses for its notional check)
total_cap = float(account.account_capital)   # total_capital denominator
if instrument_class == "OPTION" and option_premium is not None:
    lot_risk = float(option_premium) × lot_size
else:
    lot_risk = atr_14 × atr_stop_multiplier × lot_size

# Project post-trade concentration using total_capital as base
new_trade_capital_pct = (lot_risk / total_cap × 100.0) if total_cap > 0.0 else 0.0
projected_pct = existing_pct + new_trade_capital_pct
conc_ok = projected_pct < conc_limit

Failure message:
    "{underlying} projected capital {projected_pct:.1f}% (existing {existing_pct:.1f}% 
     + new {new_trade_capital_pct:.1f}%) would exceed limit {conc_limit:.1f}%"
```

**Sub-check B (per-trade notional cap) — denominator change:**

Sub-check B currently uses `session_capital` as its denominator. To maintain internal consistency between sub-checks A and B, sub-check B should also use `account_capital` (total capital) as the denominator. The limit is `max_notional_per_trade_pct` — it makes sense for this to be a percentage of total capital rather than of session capital (which fluctuates intraday).

```
notional_pct = (lot_risk / total_cap × 100.0) if total_cap > 0.0 else 0.0
notional_ok = notional_pct <= config.position_limits.max_notional_per_trade_pct
```

**Pass case — return projected value:**

When both sub-checks pass, `current_value` should return the projected concentration:
```
current_value = projected_pct
limit_value = conc_limit
```

### Files Impacted

| File | Change |
|------|--------|
| `src/core/domain/risk/risk_limit_checker.py` | Update `check_capital_concentration` to project post-trade pct using `account_capital` |
| `tests/unit/domain/risk/test_risk_limit_checker.py` | Add projection-specific test cases (see below) |

### Test Changes Required

**New test cases for `TestCheckCapitalConcentration`:**

| Test name | Setup | Expected |
|-----------|-------|---------|
| `test_projection_pushes_above_limit_fails` | `existing_pct=19.0`, `conc_limit=20.0`, trade notional = 2% of total_cap | `passed=False` — projected 21% > 20% |
| `test_projection_stays_below_limit_passes` | `existing_pct=17.0`, trade notional = 2% | `passed=True` — projected 19% < 20% |
| `test_current_value_is_projected_not_existing` | `existing_pct=10.0`, trade notional = 5% | `result.current_value == 15.0` (projected), not `10.0` (existing) |
| `test_message_shows_both_existing_and_new_trade_pct` | Any setup | `"existing"` and projected value both appear in `result.message` |

**Existing test to update:**

`test_below_conc_limit_passes` — currently sets `capital_per_underlying_pct={"NIFTY": limit - 1.0}` and expects pass. Must verify the new trade's contribution does not push above the limit. If `option_premium` is small (low notional), this test continues to pass. Adjust the test setup to explicitly use a small premium that keeps `projected_pct < conc_limit`.

`test_notional_at_limit_passes` and `test_notional_above_limit_fails` — sub-check B denominator change from `session_capital` to `account_capital`. These tests use `session_capital=Decimal("500000")` and `account_capital=Decimal("500000")` (same value), so no numeric change is required. Add a comment documenting the denominator used.

---

## Remediation 5 — H3: Greek Unit Contract Undefined

### Root Cause

`GreeksSnapshot.delta` is currently documented as:
```
delta: Option delta (signed; call ≈ +0.5, put ≈ −0.5 at ATM).
```

This description unambiguously describes the **raw Black-Scholes delta** (dimensionless, 0–1 range for calls).

`GreeksAggregate.net_delta` is documented as:
```
net_delta: Sum of per-position delta values (INR/point of underlying).
```

`GreeksCalculator.aggregate()` sums `s.delta` from snapshots with no transformation. If `GreeksSnapshot.delta` is the raw per-share delta (0.5), then `GreeksAggregate.net_delta` would be in raw-delta units, not INR/point.

For `PortfolioState.net_delta` (used in Check 8 and Check 9) to be in INR/point, the conversion must happen at snapshot write time:
```
snapshot.delta = raw_delta × lot_size   (e.g., 0.5 × 50 = 25.0 for NIFTY ATM call, 1 lot)
```

The current docstring says `delta ≈ +0.5` — which is NOT the lot-size-scaled INR/point value. The docstring and the intended unit contract are contradictory. `GreeksComputeService` (Phase D) has no written specification to follow.

If Phase D writes raw deltas (as the docstring implies), all four Greek-dependent checks (8, 9, 14, 15) enforce limits using wrong-unit values. This is a silent failure — no exception is raised.

### Proposed Fix: Define Explicit Unit Contract

**This remediation is a design update — no functional code change in Phase B domain files. The fix is precision in specification.**

**GreeksSnapshot contract — updated field documentation:**

```
position_id: str
    Internal or broker position identifier.

delta: float
    Position-level delta contribution in the same unit system as PortfolioState.net_delta:
    INR per 1-point move in the underlying index.
    
    Computation required by GreeksComputeService:
        delta = raw_bs_delta × lot_size × lots
        
    Example: NIFTY ATM call, raw delta = 0.5, lot_size = 50, lots = 1
             → snapshot.delta = 0.5 × 50 × 1 = 25.0
    
    NOT the raw Black-Scholes delta (0–1 range). The phase that writes this 
    snapshot (GreeksComputeService, Phase D) is responsible for the scaling.

gamma: float
    Position-level gamma contribution (INR per 1-point² move in the underlying).
    Computation: raw_gamma × lot_size × lots

theta: float
    Position-level daily time decay (INR per calendar day, negative for long options).
    Computation: raw_theta × lot_size × lots

vega: float
    Position-level sensitivity to 1% IV change (INR per 1% IV change, per lot).
    Computation: raw_vega × lot_size × lots
```

**GreeksAggregate — add validation range note:**

The `snapshot_count >= 0` invariant is correct. Add documentation that `net_delta`, `net_theta`, `net_vega` are unconstrained in sign (negative theta for long portfolios is correct). No range validator is required for the aggregate.

**GreeksCalculator — add precondition comment:**

A precondition comment must be added stating: _"Inputs must be pre-scaled to INR-unit values by the caller (GreeksComputeService). This function sums values as-is without unit conversion."_

**Phase D integration test requirement:**

The Phase D implementation plan must include an integration test that asserts:
```
Given: position with raw_bs_delta=0.5, lot_size=50, lots=1
When: GreeksComputeService writes the GreeksSnapshot
Then: snapshot.delta == 25.0  (NOT 0.5)
```

This test closes the validation gap that Phase B cannot close alone.

### Files Impacted

| File | Change |
|------|--------|
| `src/core/domain/risk/greeks_snapshot.py` | Rewrite field docstrings to specify INR-unit contract with explicit computation formula and example |
| `src/core/domain/risk/greeks_calculator.py` | Add precondition comment stating inputs must be pre-scaled |
| `src/core/domain/risk/greeks_aggregate.py` | Update `net_delta` docstring to reference the unit contract defined in `GreeksSnapshot` |

### Test Changes Required

No Phase B unit test changes. The unit tests test the aggregation logic (sum, any, len), which is correct regardless of units. The integration test that validates the scaling is a **Phase D deliverable** — it must be listed in the Phase D implementation plan as a mandatory test.

**Add to the Phase D test plan (not Phase B):**

| Test | Location |
|------|----------|
| `test_greeks_snapshot_delta_is_lot_size_scaled_not_raw_bs` | `tests/integration/test_greeks_compute_service.py` (Phase D) |

---

## Remediation 6 — M4: No Enforcement That Phase D Must Respect `is_warning=True`

### Root Cause

`RiskCheckResult.is_warning: bool = False` signals that a `passed=False` result must not cause trade rejection. Only `check_theta_decay` sets this to `True`.

There is no programmatic enforcement. Phase D (`RiskEngineService.evaluate()`) must check this flag before treating `passed=False` as a rejection. If it iterates with `if not result.passed: reject(...)`, theta breaches become hard rejections — silently, with no compilation or test error.

The `RiskCheckResult` VO cannot enforce its own semantics. This contract exists only in the design document and comments.

### Proposed Fix: Add `is_hard_failure` Property to `RiskCheckResult`

Add a computed property to `RiskCheckResult` that encodes the correct rejection predicate:

```python
@property
def is_hard_failure(self) -> bool:
    """True when this result requires trade rejection.
    
    A result with passed=False and is_warning=True (ThetaDecay) must NOT
    trigger rejection. Only hard failures stop the evaluation.
    
    Phase D MUST use this property as the rejection predicate:
        if result.is_hard_failure:
            return reject(result)
        # DO NOT use: if not result.passed
    """
    return not self.passed and not self.is_warning
```

This converts an implicit contract (doc + comment) into an explicit callable property on the VO itself. Phase D is guided toward correct usage at the call site.

**Why not a class method or validator:**

`RiskCheckResult` is a frozen dataclass. Properties are supported. The property has no I/O and no side effects. It derives entirely from existing fields. No new parameters or dependencies are required.

### Files Impacted

| File | Change |
|------|--------|
| `src/core/domain/risk/risk_decision.py` | Add `is_hard_failure` property to `RiskCheckResult` |
| `tests/unit/domain/risk/test_risk_decision.py` | Add property tests (see below) |

### Test Changes Required

**New test cases for `RiskCheckResult` (in `test_risk_decision.py`):**

| Test name | Setup | Expected |
|-----------|-------|---------|
| `test_is_hard_failure_when_failed_and_not_warning` | `passed=False, is_warning=False` | `is_hard_failure == True` |
| `test_not_hard_failure_when_passed_true` | `passed=True, is_warning=False` | `is_hard_failure == False` |
| `test_not_hard_failure_when_warning_even_if_failed` | `passed=False, is_warning=True` | `is_hard_failure == False` — the ThetaDecay case |
| `test_not_hard_failure_when_passed_true_and_warning` | `passed=True, is_warning=True` | `is_hard_failure == False` |
| `test_theta_decay_result_is_never_hard_failure` | Call `check_theta_decay` with theta above threshold | `result.is_hard_failure == False` always |

The last test is a cross-module test that validates the end-to-end contract across `check_theta_decay` and `is_hard_failure`.

---

## Updated Readiness Score Projection

### Current State (Phase B, Post-Audit)

| Dimension | Current Score | Issue |
|-----------|--------------|-------|
| Risk check correctness | 10 / 20 | C1, H2, M5 |
| Boundary condition handling | 7 / 10 | M1 |
| Kelly implementation | 8 / 10 | L2 |
| ATR sizing implementation | 9 / 10 | — |
| Correlation logic | 5 / 10 | H1 |
| Concentration logic | 7 / 10 | H4, M3 |
| Delta exposure logic | 8 / 10 | — |
| Greeks aggregation | 6 / 10 | H3 |
| Warning vs rejection behavior | 6 / 10 | M2, M4 |
| Test coverage quality | 9 / 10 | — |
| Future asset compatibility | 5 / 10 | H2, L1 |
| Structural quality | 20 / 20 | — |
| **Total** | **100 / 140** | **72 / 100** |

### Projected State After All Six Remediations

| Dimension | Projected Score | Remediation That Fixes It |
|-----------|----------------|--------------------------|
| Risk check correctness | 17 / 20 | R1 (C1), R2 (H2) — M5 minor |
| Boundary condition handling | 7 / 10 | M1 not addressed; no change |
| Kelly implementation | 8 / 10 | — |
| ATR sizing implementation | 9 / 10 | — |
| Correlation logic | 9 / 10 | R3 (H1) — per-underlying gross is Phase 2 |
| Concentration logic | 9 / 10 | R4 (M3), H4 (if L1 also fixed) |
| Delta exposure logic | 8 / 10 | — |
| Greeks aggregation | 9 / 10 | R5 (H3) |
| Warning vs rejection behavior | 9 / 10 | R6 (M4), M2 deferred |
| Test coverage quality | 10 / 10 | New tests close the capital-size gap |
| Future asset compatibility | 8 / 10 | R2 closes H2 |
| Structural quality | 20 / 20 | — |
| **Projected Total** | **123 / 140** | **88 / 100** |

### Remaining Open Items (Not Addressed by These Six Remediations)

| ID | Finding | Deferred To |
|----|---------|------------|
| H4 | OPTION with `option_premium=None` uses FUTURE formula in CapConc | Closed if L1 (RiskRequest invariant) is added as part of this remediation batch |
| M1 | Inconsistent boundary operators across 15 checks | Document as deliberate policy in Phase D or address in a separate cleanup pass |
| M2 | ThetaDecay does not include new position's theta contribution | Requires adding `option_theta` to `RiskRequest` — Phase D planning item |
| L1 | `RiskRequest` doesn't enforce OPTION must carry `option_premium` | Can be bundled into this remediation at low cost |
| L2 | `kelly_fraction_effective` semantics differ by path | Documentation only; no behavioral change required |
| L3 | `open_positions_count` duplicated in `AccountState` and `PortfolioState` | Phase D cleanup |
| L4 | Inconsistent defensive coding (assert vs conditional) | Low priority cleanup |

**Recommendation on L1:** Add the OPTION-requires-premium invariant to `RiskRequest.__post_init__` as part of this remediation batch. It is a 3-line change that closes H4 at the invariant level and prevents the silent FUTURE-formula fallback in `check_capital_concentration`.

---

## Remediation Sequencing

The six remediations are independent and can be implemented in parallel. However, the following ordering is recommended for review efficiency:

```
Phase B Remediation Implementation Order
─────────────────────────────────────────

Step 1 — Schema changes (no logic yet):
    R5: Update GreeksSnapshot docstring (unit contract)
    R2a: Add orders_today field to PortfolioState
    R6: Add is_hard_failure property to RiskCheckResult
    → Ruff check; full test suite must still pass (no behaviour change)

Step 2 — Risk logic changes:
    R1: Fix check_daily_loss and check_weekly_loss (absolute limit enforcement)
    R2b: Fix check_order_rate (add daily cap enforcement)
    R3: Fix check_correlation (replace GROSS with signed formula)
    R4: Fix check_capital_concentration (projected concentration)
    → All new tests must be written alongside each fix

Step 3 — Verification:
    poetry run pytest tests/unit/ -q   (target: ≥ 1435 + new tests, 0 failures)
    poetry run ruff check src/ tests/  (0 violations required)
    Verify test_corr_fires_independently_of_net_delta is REMOVED
    Verify all new test cases listed above are present and passing
```

---

## Definition of Done for This Remediation Batch

Phase C approval requires all of the following:

- [ ] `check_daily_loss` enforces both `limit_pct` and `limit_abs`; absolute limit takes precedence in message
- [ ] `check_weekly_loss` enforces both `limit_pct` and `limit_abs`; absolute limit takes precedence in message
- [ ] `PortfolioState.orders_today: int` field exists with `>= 0` invariant
- [ ] `check_order_rate` enforces both `max_orders_per_minute` and `max_orders_per_day`
- [ ] `check_correlation` uses signed-delta formula; risk-reducing opposing-direction trades pass when Check 8 also passes
- [ ] `test_corr_fires_independently_of_net_delta` is removed; replacement directional tests exist
- [ ] `check_capital_concentration` sub-check A tests projected post-trade concentration using `account_capital` as base
- [ ] `GreeksSnapshot` docstring specifies INR-unit contract with explicit formula and numeric example
- [ ] `RiskCheckResult.is_hard_failure` property exists and is tested
- [ ] `poetry run pytest tests/unit/ -q` passes all tests (0 failures)
- [ ] `poetry run ruff check src/ tests/` reports 0 violations
- [ ] Updated readiness score ≥ 85 / 100

---

*Remediation plan generated: 2026-06-13. Awaiting approval before implementation begins.*
