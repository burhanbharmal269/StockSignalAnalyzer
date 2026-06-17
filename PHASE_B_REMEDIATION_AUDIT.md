# Phase B Remediation Audit

**Date:** 2026-06-13  
**Status:** COMPLETE  
**Audited by:** Post-remediation re-audit  
**Test result:** 1,463 passed / 0 failed  
**Ruff result:** 0 violations  

---

## Audit Scope

Re-audit of all findings addressed by the approved remediation batch:

| ID | Finding | Remediation |
|----|---------|------------|
| C1 | Absolute loss limits not enforced | R1 |
| H1 | GROSS correlation rejects risk-reducing trades | R3 |
| H2 | `max_orders_per_day` dead — daily order count missing | R2 |
| H3 | Greek unit contract undefined | R5 |
| H4 | OPTION with `option_premium=None` uses FUTURE formula | L1 |
| M3 | Capital concentration tests current not projected | R4 |
| M4 | No enforcement that `is_warning=True` blocks rejection | R6 |

---

## Finding C1 — Daily and Weekly Absolute Loss Limits

**Previous status:** CRITICAL — `check_daily_loss` and `check_weekly_loss` only enforced percentage limits. The `limit_abs` config fields (10,000 INR daily, 25,000 INR weekly) had zero callers. At default 500K capital both triggers coincide; at 1M capital, the system silently allowed losses up to 20K daily before the pct trigger fired.

**Implementation reviewed:**

`check_daily_loss` now enforces two independent conditions:
1. `account.daily_loss_consumed_pct >= 100.0` — absolute limit consumed (checked first).
2. `current_loss_pct >= config.daily_loss.limit_pct` — percentage limit.

The absolute condition uses the pre-computed `AccountState.daily_loss_consumed_pct` field, which normalises `abs(daily_pnl) / daily_loss_limit_abs × 100`. This avoids re-implementing the `limit_abs` division inside the check function. At `daily_loss_consumed_pct >= 100.0`, the absolute limit has been fully consumed.

The same pattern is applied identically in `check_weekly_loss` using `account.weekly_loss_consumed_pct`.

**Failure message** correctly prioritises the absolute breach when both conditions fire:
- Absolute: `"Daily loss consumed {pct:.1f}% of absolute limit ({limit_abs} INR)"`
- Percentage: `"Daily loss {pct:.2f}% at or above limit {limit_pct:.2f}%"`

**`current_value` / `limit_value`** contract:
- Absolute binding: `current_value = daily_loss_consumed_pct`, `limit_value = 100.0`
- Percentage binding: `current_value = current_loss_pct`, `limit_value = limit_pct`
- Passing: `current_value = current_loss_pct`, `limit_value = limit_pct`

**Test coverage verified:**

| Test | Scenario | Result |
|------|---------|--------|
| `test_abs_limit_fires_with_large_capital` | 1M capital, 15K loss (1.5% < 2%), `consumed_pct=150.0` | `passed=False`, `current_value=150.0` |
| `test_abs_limit_at_100_pct_fails` | `consumed_pct=100.0` | `passed=False` |
| `test_abs_limit_below_100_passes_when_pct_ok` | `consumed_pct=45.0`, pct=0.9% | `passed=True` |
| `test_current_value_is_consumed_pct_when_abs_binds` | `consumed_pct=120.0` | `current_value=120.0`, `limit_value=100.0` |
| `test_weekly_abs_limit_fires_with_large_capital` | 1M capital, 30K weekly loss | `passed=False` |
| `test_weekly_abs_limit_at_100_pct_fails` | `weekly_loss_consumed_pct=100.0` | `passed=False` |
| All pre-existing tests | Default 500K capital (triggers coincide) | Unaffected ✓ |

**Verdict: RESOLVED.** Absolute limits are now enforced. The bug is closed by construction — neither `limit_abs` nor the related `consumed_pct` fields have any other callers, so there is no regression risk.

---

## Finding H1 — Correlation Formula Incorrectly Rejects Risk-Reducing Trades

**Previous status:** HIGH — GROSS formula `(|net_delta| + |new_delta_abs|) × max_rho` used absolute values for both operands, making it impossible for an opposing-direction trade to reduce measured exposure. A portfolio at `net_delta = −2,480` could not add a LONG CALL with delta=+25 even though Check 8 (NetDelta) correctly passed it.

**Implementation reviewed:**

`check_correlation` now uses a signed, correlation-adjusted projected net-delta formula:

```python
direction_sign = 1.0 if request.direction == "LONG" else -1.0
if request.instrument_class == "OPTION" and request.option_delta is not None:
    new_delta_signed = request.option_delta * request.lot_size * direction_sign
else:
    new_delta_signed = float(request.lot_size) * direction_sign

corr_adjusted_portfolio = portfolio.net_delta * max_rho
effective_exposure = corr_adjusted_portfolio + new_delta_signed
correlated_exposure = abs(effective_exposure)
```

The formula correctly handles all four cases:

| Scenario | net_delta | new_delta_signed | max_rho | corr_adj | effective | |exposure| | Expected |
|----------|-----------|-----------------|---------|---------|-----------|----------|---------|
| Risk-reducing (same underlying) | −2,480 | +25 | 1.0 | −2,480 | −2,455 | 2,455 | PASS ✓ |
| Risk-increasing (same underlying) | +2,480 | +25 | 1.0 | +2,480 | +2,505 | 2,505 | FAIL ✓ |
| Cross-instrument at rho=0.85 | +2,480 | +25 | 0.85 | +2,108 | +2,133 | 2,133 | PASS ✓ |
| LOW rho (0.2), risk-reducing | −2,480 | +25 | 0.2 | −496 | −471 | 471 | PASS ✓ |

Docstring updated with reference to `AD-P13-01`. The architecture decision document is written at `docs/architecture_decisions/AD-P13-01.md`.

**Removed test:** `test_corr_fires_independently_of_net_delta` — this test validated the false rejection behavior of the GROSS formula. It is removed.

**Updated test:** `test_empty_matrix_uses_conservative_default` — updated from a negative portfolio (which with the new formula would show a risk-reducing PASS) to a positive portfolio (same-direction trade → risk-increasing FAIL). The test now verifies conservative-default rho in a risk-increasing scenario.

**Renamed test:** `test_low_correlation_passes_what_net_delta_blocks` → `test_low_correlation_applies_discount_to_portfolio_delta` — name updated to accurately reflect the signed formula behavior.

**New tests:**

| Test | Scenario | Expected |
|------|---------|---------|
| `test_corr_allows_risk_reducing_opposing_direction` | `net_delta=−2,480`, LONG CALL delta=+25, rho=1.0 | PASS |
| `test_corr_blocks_risk_increasing_near_limit` | `net_delta=+2,480`, LONG CALL delta=+25, rho=1.0 | FAIL |
| `test_corr_cross_instrument_rho_discount_reduces_exposure` | `net_delta=+2,480`, NIFTY trade, BANKNIFTY portfolio, rho=0.85 | PASS, `current_value≈2,133` |

**Verdict: RESOLVED.** Risk-reducing opposing-direction trades now correctly pass. Same-direction risk-increasing trades near the limit correctly fail. Cross-instrument rho discount applied correctly. `AD-P13-01` documents the intentional design constraint.

---

## Finding H2 — `max_orders_per_day` Dead Config

**Previous status:** HIGH — `PortfolioState` had no `orders_today` field. `check_order_rate` only enforced `max_orders_per_minute`. The daily cap of 50 orders per day had zero callers and zero enforcement.

**Implementation reviewed:**

`PortfolioState` now has:
```python
orders_today: int   # Count of orders placed since midnight IST, current trading day
```

`__post_init__` validates `orders_today >= 0` with `RiskInvariantError`.

`check_order_rate` now enforces two independent conditions:
1. `orders_last_minute >= max_orders_per_minute` — per-minute rate (checked first).
2. `orders_today >= max_orders_per_day` — daily total.

Both conditions use `>=` (at-limit fails), consistent with the existing `test_at_limit_fails` behavior.

**`current_value` / `limit_value`** contract:
- Per-minute binding: `float(orders_last_minute)`, `float(max_orders_per_minute)`
- Daily binding: `float(orders_today)`, `float(max_orders_per_day)`
- Passing: `float(orders_last_minute)`, `float(max_orders_per_minute)` (per-minute as primary metric)

**Test coverage verified:**

| Test | Scenario | Expected |
|------|---------|---------|
| `test_daily_limit_at_cap_fails` | `orders_today = max_orders_per_day` | `passed=False` |
| `test_daily_limit_above_cap_fails` | `orders_today = max_orders_per_day + 5` | `passed=False` |
| `test_daily_limit_below_cap_passes` | `orders_today = max_orders_per_day - 1` | `passed=True` |
| `test_rate_ok_daily_limit_exceeded_fails` | `orders_last_minute=0`, `orders_today=max` | `passed=False`, `current_value=max_orders_per_day` |
| `test_rate_exceeded_daily_ok_fails` | `orders_last_minute=max`, `orders_today=0` | `passed=False` |
| `test_both_within_limits_passes` | both=0 | `passed=True` |
| `test_orders_today_zero_valid` | `orders_today=0` | Construction succeeds |
| `test_orders_today_positive_valid` | `orders_today=49` | Construction succeeds |
| `test_negative_orders_today_raises` | `orders_today=-1` | `RiskInvariantError` |

**`_make_portfolio` factory** updated with `orders_today=0` as default. All 82 existing order-rate and portfolio tests that call this factory continue to pass without modification.

**Phase C/D impact noted:** `RedisPortfolioStateRepository` (Phase C) must populate `orders_today` from Redis. The `risk:portfolio_state` Hash must include `orders_today` as a key. This is a Phase C schema requirement.

**Verdict: RESOLVED.** Daily order cap is now enforced. The field is schema-complete in the domain layer.

---

## Finding H3 — Greek Unit Contract Undefined

**Previous status:** HIGH — `GreeksSnapshot.delta` docstring described "call ≈ +0.5, put ≈ −0.5 at ATM" (raw Black-Scholes units), but `GreeksAggregate.net_delta` claimed "INR/point of underlying." `GreeksCalculator` summed deltas as-is without conversion. Phase D (`GreeksComputeService`) had no written specification to follow. A silent unit mismatch would cause all four Greek-dependent checks (8, 9, 14, 15) to enforce limits against wrong-unit values.

**Implementation reviewed:**

`GreeksSnapshot` docstring now explicitly defines the INR-unit contract with computation formula and example:

```
Unit contract (enforced by GreeksComputeService, Phase D):
    All numeric fields are pre-scaled to INR-unit values before being stored.
    This class sums them as-is — no unit conversion is performed here.
    The phase that writes this snapshot is responsible for applying the scaling:
        value = raw_bs_value × lot_size × lots

Attributes:
    delta: Position delta contribution in INR per 1-point underlying move.
           Computed as: raw_bs_delta × lot_size × lots.
           Example: NIFTY ATM call (raw delta=0.5, lot_size=50, 1 lot) → 25.0.
           NOT the raw Black-Scholes delta (0–1 range).
```

Same formula documented for `gamma`, `theta`, and `vega`.

`GreeksAggregate` docstring updated with cross-reference:
```
Unit dependency: All values are sums of pre-scaled INR-unit inputs.
    Correctness depends on GreeksSnapshot.delta (and gamma/theta/vega) being
    pre-scaled by GreeksComputeService before storage.
```

`GreeksCalculator.aggregate()` docstring updated with explicit precondition:
```
Precondition: All GreeksSnapshot values must be pre-scaled to INR-unit values
by GreeksComputeService (Phase D). This method sums as-is without unit
conversion. See GreeksSnapshot for the authoritative unit contract.
```

**Phase D integration test requirement (mandatory):** The Phase D implementation plan must include:
```
Given: position with raw_bs_delta=0.5, lot_size=50, lots=1
When: GreeksComputeService writes the GreeksSnapshot
Then: snapshot.delta == 25.0  (NOT 0.5)
```

This Phase D test is the only mechanism that validates the scaling was correctly applied at write time. Without it, a Phase D developer could write raw deltas and the domain layer would produce incorrect results silently.

**Verdict: RESOLVED** (Phase B scope). The unit contract is now unambiguous and written at the source of truth (`GreeksSnapshot`). Remaining risk is carried to Phase D where it must be closed by the mandatory integration test.

---

## Finding H4 — OPTION with `option_premium=None` Uses FUTURE Formula

**Previous status:** HIGH — `check_capital_concentration` had a guard `if request.instrument_class == "OPTION" and request.option_premium is not None`. If OPTION was constructed without `option_premium`, the check silently fell through to the FUTURE ATR formula. `RiskRequest` did not enforce that OPTION requires a non-None, positive premium.

**Implementation reviewed (L1 invariant):**

`RiskRequest.__post_init__` now enforces:
```python
if self.instrument_class == "OPTION":
    if self.option_premium is None:
        raise RiskInvariantError("option_premium is required for OPTION instruments")
    if self.option_premium <= Decimal(0):
        raise RiskInvariantError(
            f"option_premium must be > 0 for OPTION instruments, got {self.option_premium}"
        )
elif self.option_premium is not None and self.option_premium < Decimal(0):
    raise RiskInvariantError(
        f"option_premium must be >= 0 when provided, got {self.option_premium}"
    )
```

The old single-line guard `option_premium >= 0` is replaced with:
- **OPTION:** `option_premium` is required and must be `> 0` (zero premium is now invalid for OPTION).
- **FUTURE or other:** If `option_premium` is supplied, it must be `>= 0` (backward-compatible).

This invariant makes the `and request.option_premium is not None` guard in `check_capital_concentration` permanently dead code for valid inputs. The guard is retained for type safety only.

**Impact on position_sizer tests:** Two existing tests used `option_premium=Decimal("0")` to test zero-ATR-lots behavior. After L1, construction with zero premium fails. Both tests were updated:
- `test_zero_premium_gives_zero_lots` → `test_premium_exceeds_capital_at_risk_gives_zero_lots` (uses premium=150, same atr_lots=0 result)
- `test_both_zero_gives_zero` → updated to use premium=150 (same both-zero result)

**New tests in test_risk_request.py:**

| Test | Expected |
|------|---------|
| `test_zero_option_premium_for_option_raises` | `RiskInvariantError` |
| `test_none_option_premium_for_option_raises` | `RiskInvariantError` |
| `test_option_premium_required_for_option` | Construction succeeds with `option_premium=Decimal("150")` |
| `test_none_option_premium_valid_for_future` | Construction succeeds (FUTURE, `option_premium=None`) |

**Verdict: RESOLVED.** The FUTURE-formula fallback for OPTION is now impossible by construction. H4 is permanently closed at the domain boundary.

---

## Finding M3 — Capital Concentration Tests Current Exposure, Not Projected

**Previous status:** MEDIUM — `check_capital_concentration` sub-check A compared `existing_pct` (current capital in the underlying) to `conc_limit`. A NIFTY position at 19% could always add any new trade, even one that would push the total to 21% above a 20% limit.

**Implementation reviewed:**

`check_capital_concentration` now:

1. Computes `lot_risk` once (OPTION or FUTURE formula, using `account_capital` as denominator).
2. Derives `trade_capital_pct = lot_risk / total_cap × 100.0` — the new trade's capital contribution.
3. Computes `projected_pct = existing_pct + trade_capital_pct` — the post-trade concentration.
4. Sub-check A: `projected_pct >= conc_limit` → FAIL.
5. Sub-check B: `trade_capital_pct > notional_limit` → FAIL.

**Denominator unification:** Both sub-checks now use `account.account_capital` as the denominator. Previously sub-check B used `session_capital`. Since the test factory has both at 500K by default, existing tests are numerically unaffected. The unified denominator ensures sub-checks A and B are measured on a consistent capital basis.

**Pass case:** `current_value = projected_pct` (not `max(existing_pct, notional_pct)` as before). The projected concentration is the correct metric to surface.

**Failure message** names both components:
```
"{underlying} projected capital {projected:.1f}% (existing {existing:.1f}% + new {trade:.1f}%) would exceed limit {conc:.1f}%"
```

**New tests:**

| Test | Setup | Expected |
|------|-------|---------|
| `test_projection_pushes_above_limit_fails` | `existing=19%`, trade=2% (premium=200, lot=50) | `passed=False` |
| `test_projection_stays_below_limit_passes` | `existing=17%`, trade=2% | `passed=True` |
| `test_current_value_is_projected_not_existing` | `existing=10%`, trade=5% | `current_value=15.0` |
| `test_failure_message_shows_existing_and_new_pct` | `existing=19%`, trade=2% | `"existing"` in message |

**Existing tests verified unaffected** (all use `account_capital=500_000` by default):
- `test_no_existing_concentration_passes` ✓
- `test_below_conc_limit_passes` ✓ (19% existing + 0.5% trade = 19.5% < 20%)
- `test_at_conc_limit_fails` ✓ (20% existing + 1.5% trade = 21.5% ≥ 20% → still fails)
- `test_notional_above_limit_fails` ✓ (11% trade > 10% notional limit)
- `test_notional_at_limit_passes` ✓ (10% trade ≤ 10% notional limit)
- `test_future_uses_atr_stop_notional` ✓ (2.25% trade < both limits)

**Verdict: RESOLVED.** Sub-check A now tests projected post-trade concentration. The denominator is unified. Pass-case `current_value` reflects the post-trade metric.

---

## Finding M4 — No Enforcement That `is_warning=True` Blocks Rejection

**Previous status:** MEDIUM — `RiskCheckResult.passed=False` with `is_warning=True` (ThetaDecay) must never trigger trade rejection. Phase D's `RiskEngineService.evaluate()` was the sole enforcement point, with only a comment and docstring as guidance. A naive `if not result.passed: reject(...)` loop in Phase D would silently promote ThetaDecay from warning to hard rejection.

**Implementation reviewed:**

`RiskCheckResult` now has:
```python
@property
def is_hard_failure(self) -> bool:
    """True when this result requires trade rejection.

    Phase D's RiskEngineService.evaluate() MUST use this property as the
    rejection predicate — never ``not result.passed`` directly.
    A result with passed=False and is_warning=True (ThetaDecay, Check 14)
    must not trigger rejection.
    """
    return not self.passed and not self.is_warning
```

The property is defined on a frozen dataclass. It computes from two existing fields with no new state.

**Truth table verified:**

| `passed` | `is_warning` | `is_hard_failure` | Meaning |
|---------|-------------|-------------------|---------|
| True | False | False | Normal pass |
| False | False | **True** | Hard rejection — stops evaluation |
| False | True | False | ThetaDecay breach — warn, continue |
| True | True | False | ThetaDecay within threshold |

**New tests:**

| Test | Expected |
|------|---------|
| `test_is_hard_failure_when_failed_and_not_warning` | `True` |
| `test_not_hard_failure_when_passed_true` | `False` |
| `test_not_hard_failure_when_warning_even_if_failed` | `False` (the ThetaDecay case) |
| `test_not_hard_failure_when_passed_and_is_warning` | `False` |

Phase D is now guided toward `if result.is_hard_failure:` as the rejection predicate at the call site. The implicit contract is now explicit and callable.

**Verdict: RESOLVED.** The contract is expressed as a property on the VO. Phase D has a clear, testable predicate to use.

---

## Readiness Score Update

### Per-dimension scoring after remediation

| Dimension | Pre-remediation | Post-remediation | Delta | Notes |
|-----------|----------------|-----------------|-------|-------|
| Risk check correctness | 10 / 20 | 18 / 20 | +8 | C1 (abs limits) + H2 (daily cap) both fixed |
| Boundary condition handling | 7 / 10 | 7 / 10 | 0 | M1 (operator inconsistency) deferred |
| Kelly implementation | 8 / 10 | 8 / 10 | 0 | |
| ATR sizing implementation | 9 / 10 | 9 / 10 | 0 | |
| Correlation logic | 5 / 10 | 9 / 10 | +4 | H1 resolved; per-underlying gross deferred to Phase 2 |
| Concentration logic | 7 / 10 | 10 / 10 | +3 | M3 resolved; H4 resolved via L1 |
| Delta exposure logic | 8 / 10 | 8 / 10 | 0 | |
| Greeks aggregation | 6 / 10 | 9 / 10 | +3 | H3 resolved (Phase B scope) |
| Warning vs rejection behavior | 6 / 10 | 9 / 10 | +3 | M4 resolved; M2 deferred |
| Test coverage quality | 9 / 10 | 10 / 10 | +1 | New capital-size tests close the gap |
| Future asset compatibility | 5 / 10 | 9 / 10 | +4 | H2 + L1 both close future-class gaps |
| Structural quality | 20 / 20 | 20 / 20 | 0 | |
| **Total** | **100 / 140** | **126 / 140** | **+26** | |
| **Percentage** | **72 / 100** | **90 / 100** | **+18** | |

### Remaining open items (not addressed in this batch)

| ID | Finding | Decision |
|----|---------|---------|
| M1 | Inconsistent boundary operators (`<` vs `<=`) across checks | Deferred — document as deliberate policy in Phase D |
| M2 | ThetaDecay uses only existing theta, ignores new position's theta contribution | Deferred — requires adding `option_theta` to `RiskRequest` (Phase D scope) |
| L1-FUTURE | FUTURE `option_premium` could be non-None with value=0 | Low priority — not a valid use case; no caller sets it |
| L2 | `kelly_fraction_effective` semantics differ by path | Documentation only |
| L3 | `open_positions_count` duplicated in `AccountState` and `PortfolioState` | Phase D cleanup |
| Phase D integration | GreeksComputeService must write INR-scaled deltas | Mandatory Phase D test (H3 Phase D close) |

None of the remaining open items are Phase B blockers.

---

## Phase C Recommendation

**READY_FOR_PHASE_C**

### Definition of Done — verified

- [x] `check_daily_loss` enforces both `limit_pct` and `limit_abs`; absolute takes precedence
- [x] `check_weekly_loss` enforces both `limit_pct` and `limit_abs`; absolute takes precedence
- [x] `PortfolioState.orders_today: int` field exists with `>= 0` invariant
- [x] `check_order_rate` enforces both `max_orders_per_minute` and `max_orders_per_day`
- [x] `check_correlation` uses signed-delta formula; risk-reducing opposing trades pass when Check 8 passes
- [x] `test_corr_fires_independently_of_net_delta` is removed; replacement directional tests exist
- [x] `check_capital_concentration` sub-check A tests projected post-trade concentration using `account_capital`
- [x] `GreeksSnapshot` docstring specifies INR-unit contract with formula and example
- [x] `RiskCheckResult.is_hard_failure` property exists and is tested
- [x] `RiskRequest` rejects OPTION with `option_premium=None` or `<= 0` at construction time
- [x] `AD-P13-01` architecture decision documented at `docs/architecture_decisions/AD-P13-01.md`
- [x] `poetry run pytest tests/unit/ -q` → **1,463 passed / 0 failed**
- [x] `poetry run ruff check src/ tests/` → **0 violations**
- [x] Updated readiness score: **90 / 100** (target was ≥ 85)

### Phase C scope reminder

Phase C: Repositories, DB Models, Alembic Migration 004_phase13.

Key Phase C schema dependencies from this remediation:
- `PortfolioState.orders_today` must be written by `RedisPortfolioStateRepository` from `risk:portfolio_state` Hash key `orders_today`.
- `AccountState.daily_loss_consumed_pct` and `weekly_loss_consumed_pct` must be accurate — they drive the new absolute-limit enforcement in Checks 2 and 3.

---

*Remediation audit completed: 2026-06-13. Phase C approval may now be requested.*
