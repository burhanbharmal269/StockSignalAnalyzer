# Phase B Risk Logic Audit

**Date:** 2026-06-13  
**Auditor:** Claude (Sonnet 4.6)  
**Scope:** Phase B domain implementation — `risk_limit_checker.py`, `position_sizer.py`, `greeks_aggregate.py`, `greeks_calculator.py` and all Phase B unit tests  
**Reference documents:** `docs/17_PORTFOLIO_RISK_ENGINE.md`, `docs/PHASE_13_IMPLEMENTATION_PLAN.md`, `docs/PHASE_13_FINAL_READINESS_REVIEW.md`, `docs/PHASE_13_REMEDIATION_PLAN.md`, `config/risk.yaml`

---

## Executive Summary

Phase B domain code is architecturally clean: pure functions, no I/O, frozen value objects, correct layering, 0 ruff violations, 137 tests passing. The structural quality is high. However, the risk logic itself has **one Critical safety deficiency**, **four High findings**, and **five Medium findings** that must be resolved before Phase C generates persistent audit records against this logic.

**Architecture Readiness Score: 72 / 100**

**Recommendation: NOT_READY_FOR_PHASE_C**

Blocker summary:
- **C1** — Absolute loss limits (`limit_abs`) are dead config. Daily and weekly loss checks enforce only the percentage limit.
- **H1** — GROSS correlation formula incorrectly rejects risk-reducing opposing-direction trades when the portfolio delta is near the limit.
- **H2** — `max_orders_per_day` is permanently unenforceable because `PortfolioState` has no daily order count field.

---

## Finding Index

| ID | Severity | Area | Title |
|----|----------|------|-------|
| C1 | **Critical** | Risk Check Correctness | `limit_abs` dead — daily and weekly loss absolute thresholds not enforced |
| H1 | High | Correlation Logic | GROSS formula falsely rejects risk-reducing opposing-direction trades |
| H2 | High | Risk Check Correctness | `max_orders_per_day` config is dead — Check 13 enforces per-minute limit only |
| H3 | High | Greeks Aggregation | Greek unit contract unvalidated across Phase B / Phase D boundary |
| H4 | High | Concentration Logic | OPTION with `option_premium=None` silently uses FUTURE formula in CapConc |
| M1 | Medium | Boundary Conditions | Inconsistent boundary operators (`<` vs `<=`) across 15 checks |
| M2 | Medium | Warning vs Rejection | ThetaDecay (Check 14) evaluates existing portfolio theta, not projected post-trade theta |
| M3 | Medium | Concentration Logic | Capital concentration tests current exposure, not projected post-trade exposure |
| M4 | Medium | Warning vs Rejection | No enforcement that Phase D must respect `is_warning=True` before rejecting |
| M5 | Medium | Risk Check Correctness | Pre-computed `daily_loss_consumed_pct` / `weekly_loss_consumed_pct` fields exist but are never read |
| L1 | Low | Future Asset Compatibility | `RiskRequest` does not enforce OPTION must carry `option_premium` |
| L2 | Low | Kelly Implementation | `kelly_fraction_effective` has different semantics in normal vs fallback path |
| L3 | Low | Risk Check Correctness | `AccountState.open_positions_count` duplicates `PortfolioState.open_positions_count`; drift possible |
| L4 | Low | Risk Check Correctness | `assert session_cap > 0.0` in PositionSizer vs conditional guard in loss checks — inconsistent defensive coding |

---

## Critical Findings

---

### C1 — `limit_abs` Dead: Daily and Weekly Loss Absolute Thresholds Not Enforced

**Severity:** Critical  
**Area:** Risk Check Correctness (Check 2, Check 3)  
**Files:** `src/core/domain/risk/risk_limit_checker.py:87–106`, `risk_limit_checker.py:114–133`

#### Description

`check_daily_loss` and `check_weekly_loss` enforce only the percentage-of-capital limit. The absolute INR limits defined in `config/risk.yaml` (`daily_loss.limit_abs: 10000` and `weekly_loss.limit_abs: 25000`) are **never read, never checked, never enforced.**

Doc 17 explicitly states: _"whichever triggers first (pct or abs)"_. The implementation violates this.

#### Evidence

```python
# check_daily_loss (line 88-95 of risk_limit_checker.py)
session_cap = float(account.session_capital)
if session_cap > 0.0 and account.daily_pnl < Decimal(0):
    current_loss_pct = float(abs(account.daily_pnl)) / session_cap * 100.0
else:
    current_loss_pct = 0.0
limit = config.daily_loss.limit_pct   # ← only pct limit used
passed = current_loss_pct < limit     # ← limit_abs never checked
```

`config.daily_loss.limit_abs` is loaded into `RiskConfig` but has zero callers in Phase B.

#### Why It Is Invisible With Default Config

With `total_capital: 500000` and `limit_pct: 2.0`, the pct trigger fires at:  
`500,000 × 2% = 10,000 INR = limit_abs`

The two limits are **coincidentally identical** for the default 500K capital. The bug is invisible until the operator increases capital:

| Capital | limit_pct trigger | limit_abs trigger | Which fires first |
|---------|------------------|-------------------|-------------------|
| 500K | 10,000 INR | 10,000 INR | Same |
| 1M | 20,000 INR | 10,000 INR | **limit_abs fires first — but is never checked** |
| 5M | 100,000 INR | 10,000 INR | **limit_abs fires first — but is never checked** |

A 1M-capital account can absorb 20,000 INR daily loss before the pct check triggers, but the design intent is to stop at 10,000 INR. The absolute limit is the fixed INR cap — it exists precisely because for larger accounts the percentage is too permissive.

#### Pre-Computed Fields Are Ignored

`AccountState` already carries `daily_loss_consumed_pct: float` which is documented as:
> `abs(daily_pnl) / daily_loss_limit_abs × 100 (only when negative)`

This field, when it reaches 100.0, means the absolute limit is consumed. But `check_daily_loss` never reads it — it recomputes its own percentage from `daily_pnl / session_capital`, which is the percentage limit, not the absolute limit.

The same problem exists for `weekly_loss_consumed_pct`.

#### Risk

An operator who configures `limit_abs` trusting it will protect them will receive no protection above the `limit_pct` trigger level. For larger accounts, this represents a multi-thousand INR safety gap that grows linearly with account size.

#### Recommended Fix

```python
def check_daily_loss(account: AccountState, config: RiskConfig) -> RiskCheckResult:
    session_cap = float(account.session_capital)
    if session_cap > 0.0 and account.daily_pnl < Decimal(0):
        current_loss_pct = float(abs(account.daily_pnl)) / session_cap * 100.0
    else:
        current_loss_pct = 0.0

    pct_limit = config.daily_loss.limit_pct
    pct_breached = current_loss_pct >= pct_limit

    # Absolute limit check: use pre-computed field or re-derive
    abs_breached = (
        account.daily_pnl < Decimal(0)
        and abs(account.daily_pnl) >= Decimal(config.daily_loss.limit_abs)
    )

    passed = not (pct_breached or abs_breached)
    ...
```

The same pattern must be applied to `check_weekly_loss` using `config.weekly_loss.limit_abs`.

**New tests required:** Add cases where `session_capital = 1,000,000`, loss = 15,000 INR (above limit_abs=10,000 but below limit_pct × 1M = 20,000 INR). Should fail.

---

## High Findings

---

### H1 — GROSS Correlation Formula Incorrectly Rejects Risk-Reducing Opposing-Direction Trades

**Severity:** High  
**Area:** Correlation Logic (Check 9)  
**Files:** `src/core/domain/risk/risk_limit_checker.py:332–388`

#### Description

The implemented GROSS correlation formula:
```
correlated_exposure = (|portfolio.net_delta| + |new_delta_abs|) × max_rho
```

This formula adds the absolute values of both the portfolio delta and the new position's delta before applying the correlation coefficient. It does not distinguish between a new position that increases risk (same direction as portfolio delta) versus one that reduces risk (opposing direction).

#### The False Rejection Case

**Setup:** Portfolio is heavily short. A new LONG trade would reduce net delta.

```
portfolio.net_delta = -2,490   (just 10 below the 2,500 limit, short side)
new LONG CALL: option_delta = 0.5, lot_size = 50 → new_delta = +25
same underlying: max_rho = 1.0
```

**Check 8 (NetDelta):**
```
projected = -2,490 + 25 = -2,465
|projected| = 2,465 < 2,500 → PASS  ✓
```

**Check 9 (Correlation):**
```
total_corr_exposure = (|-2,490| + 25) × 1.0 = 2,515 > 2,500 → FAIL  ✗
```

The correlation check **rejects a trade that reduces portfolio risk**. The net delta check correctly passes it. The correlation check fires because it ignores directionality.

#### Trigger Conditions

The false rejection fires when:
1. Portfolio delta is within `[limit - new_delta_abs, limit]` of the limit, in one direction
2. The new trade is in the opposing direction (risk-reducing)
3. `max_rho = 1.0` (same underlying, or any miss in the correlation matrix)

The window is small but real: for a new trade with delta contribution of 25 units against a 2,500 limit, the trigger window is portfolios in `[2,475, 2,500]` or `[-2,500, -2,475]`.

#### Design Intent vs. Implementation

The approved GROSS deviation was intended to catch the scenario where a portfolio near the limit ADDS exposure in the same direction. It does. But it also incorrectly fires when adding opposing-direction exposure.

The documented test case `test_corr_fires_independently_of_net_delta` tests the correct case (risk-increasing). There is no test for the risk-reducing case. The false rejection is undetected by the current test suite.

#### Risk

A trader with a near-limit short delta portfolio cannot add ANY long exposure via the correlation check, even though that exposure would be risk-reducing and passes the net delta check. This creates a situation where the two checks have contradictory outcomes and the more restrictive (incorrect) one wins.

#### Recommended Fix

Option A (directional gross exposure):
```python
# Use signed delta, not absolute, when computing gross exposure
new_delta_signed = option_delta * lot_size * direction_sign  # per check 8 formula
correlated_exposure = abs(portfolio.net_delta + new_delta_signed * max_rho)
```

This preserves the correlation-weighted nature while correctly handling opposing directions.

Option B (document as accepted deviation with explicit bounds): Add a formal deviation note specifying the trigger window and confirm it is acceptable for Phase 1 signal rates, with a ticket to revisit for Phase 2.

---

### H2 — `max_orders_per_day` Config Is Dead: Check 13 Enforces Per-Minute Limit Only

**Severity:** High  
**Area:** Risk Check Correctness (Check 13)  
**Files:** `src/core/domain/risk/risk_limit_checker.py:487–504`, `src/core/domain/risk/portfolio_state.py`

#### Description

`config.order_rate.max_orders_per_day: 50` is loaded into `RiskConfig`, but:

1. `PortfolioState` has **no field for daily order count** — only `orders_last_minute: int`
2. `check_order_rate` reads only `portfolio.orders_last_minute`
3. `config.order_rate.max_orders_per_day` has **zero callers** in Phase B

```python
def check_order_rate(portfolio: PortfolioState, config: RiskConfig) -> RiskCheckResult:
    current = portfolio.orders_last_minute
    limit = config.order_rate.max_orders_per_minute   # max_orders_per_day never touched
    passed = current < limit
```

#### Risk

A bot can place orders at the maximum per-minute rate continuously for the entire trading session. At 4 orders/minute × 375-minute session = 1,500 orders. The per-day cap of 50 intended by the operator is completely unenforceable. An operator who sets `max_orders_per_day: 50` receives no protection.

#### Recommended Fix

Add `orders_today: int` to `PortfolioState`. Check it in `check_order_rate`:

```python
def check_order_rate(portfolio: PortfolioState, config: RiskConfig) -> RiskCheckResult:
    rate_ok = portfolio.orders_last_minute < config.order_rate.max_orders_per_minute
    daily_ok = portfolio.orders_today < config.order_rate.max_orders_per_day
    passed = rate_ok and daily_ok
```

The `PortfolioStateRepository` (Phase C/D) must populate this field from Redis.

---

### H3 — Greek Unit Contract Unvalidated Across Phase B / Phase D Boundary

**Severity:** High  
**Area:** Greeks Aggregation  
**Files:** `src/core/domain/risk/greeks_snapshot.py`, `src/core/domain/risk/greeks_aggregate.py`, `src/core/domain/risk/greeks_calculator.py`

#### Description

`GreeksCalculator.aggregate()` sums `GreeksSnapshot.delta` values and stores the result in `GreeksAggregate.net_delta`. The `GreeksAggregate` docstring claims:
> `net_delta: Sum of per-position delta values (INR/point of underlying).`

For this to be true, each `GreeksSnapshot.delta` must already represent the **scaled INR/point contribution** of that position, i.e., `raw_delta × lot_size`.

If `GreeksComputeService` (Phase D) stores the raw Black-Scholes delta (0–1 range for calls) instead of the pre-scaled value:
- `GreeksAggregate.net_delta` would be in raw-delta units, not INR/point
- `PortfolioState.net_delta` (written from GreeksAggregate by PortfolioMonitor, Phase D) would be wrong
- `check_net_delta` (Check 8) would compare INR/point limits against raw-delta values — apples to oranges
- `check_vega_exposure` and `check_theta_decay` would have the same unit mismatch

**The Phase B implementation assumes this invariant but provides no enforcement mechanism.** `GreeksSnapshot` has no validator for delta range. `GreeksCalculator` cannot distinguish a pre-scaled 500.0 from a raw 0.5.

#### Risk

If Phase D implements `GreeksComputeService` incorrectly, all four Greek-dependent checks (8, 9, 14, 15) pass or fail on the wrong basis. The unit mismatch is silent — tests pass, no exception is raised, and risk limits are enforced with the wrong scale. This cannot be detected from Phase B alone.

#### Recommended Fix

1. Document in `GreeksSnapshot` that `delta`, `gamma`, `theta`, `vega` are **position-level INR-unit values** (pre-multiplied by lot_size), not raw Black-Scholes outputs. Add an explicit docstring example.
2. Add a comment in `GreeksCalculator.aggregate()` stating the unit precondition.
3. In Phase D integration tests, assert that a known position with `lot_size=50`, `delta=0.5` produces a `GreeksSnapshot.delta` of 25.0 (not 0.5).

---

### H4 — OPTION with `option_premium=None` Silently Uses FUTURE ATR Formula in CapConc Check

**Severity:** High  
**Area:** Concentration Logic (Check 7)  
**Files:** `src/core/domain/risk/risk_limit_checker.py:240–251`

#### Description

In `check_capital_concentration`, sub-check B computes the capital-at-risk for one lot:

```python
if request.instrument_class == "OPTION" and request.option_premium is not None:
    lot_risk = float(request.option_premium) * request.lot_size
else:
    lot_risk = (
        request.atr_14
        * config.position_sizing.atr_stop_multiplier
        * request.lot_size
    )
```

If `instrument_class == "OPTION"` but `option_premium is None`, the code falls through to the `else` branch and uses the FUTURE ATR formula. `RiskRequest` does not enforce that OPTION must carry `option_premium` — it only requires `option_premium >= 0` if not None.

#### Consequences

For an ATM NIFTY call at premium=200 with lot_size=50: correct lot_risk = 10,000 INR.  
With the fallback ATR formula (atr_14=100, multiplier=1.5, lot_size=50): lot_risk = 7,500 INR.

The ATR formula understates the capital at risk for options. The CapConc check passes when it may not have, and the audit record shows a smaller notional risk than actual.

Also, `PositionSizer` handles this case differently — `cost_per_lot = 0.0` for OPTION with no premium → `atr_lots_raw = 0` → the trade is rejected by Check 12. But the audit trail shows `CapConc: PASS (correct formula)` when the correct formula was not applied.

#### Recommended Fix

Enforce in `RiskRequest.__post_init__` that OPTION must carry `option_premium`:

```python
if self.instrument_class == "OPTION" and self.option_premium is None:
    raise RiskInvariantError("instrument_class='OPTION' requires option_premium to be set")
```

Alternatively, raise `UnsupportedInstrumentClassError` in `check_capital_concentration` when OPTION has no premium, rather than silently falling through.

---

## Medium Findings

---

### M1 — Inconsistent Boundary Operators Across 15 Checks (`<` vs `<=`)

**Severity:** Medium  
**Area:** Boundary Conditions

#### Description

The 15 checks apply different boundary semantics at exactly the configured limit:

| Check | Operator | At-limit behavior |
|-------|----------|-------------------|
| DailyLoss, WeeklyLoss, Drawdown | `current < limit` | At limit → **FAIL** |
| OpenPositions, SymbolConcentration | `current < limit` | At limit → **FAIL** |
| CapConc Sub-check A | `existing_pct < conc_limit` | At limit → **FAIL** |
| NetDelta, Correlation | `current_value < limit` | At limit → **FAIL** |
| OrderRate | `current < limit` | At limit → **FAIL** |
| CapConc Sub-check B | `notional_pct <= notional_limit` | At limit → **PASS** |
| Margin (utilization) | `post_util <= limit_pct` | At limit → **PASS** |
| RiskReward | `min_r <= rr <= max_r` | At both bounds → **PASS** |
| ThetaDecay | `current_decay <= max_theta_abs` | At limit → **PASS** |
| VegaExposure | `current_value <= max_vega_abs` | At limit → **PASS** |

There is no consistent philosophy. The two sub-checks within `check_capital_concentration` use different operators (`<` for sub-check A, `<=` for sub-check B).

#### Risk

Operators calibrating limits may be surprised that a configuration of `max_open_positions: 10` means the system allows 9 (not 10) simultaneous positions. Conversely, `margin_utilization_limit_pct: 80` means 80% utilization is allowed (passes with `<=`), while `daily_loss_limit_pct: 2.0` means exactly 2.0% fails. The distinction is non-obvious and not documented.

#### Recommended Fix

Adopt a project-wide policy and document it in a comment block at the top of `risk_limit_checker.py`:

> "Soft limits (margin, theta, vega, R:R) use `<=` so that the exact limit value is still valid. Hard limits (positions, loss, drawdown, delta) use `<` so that reaching the limit blocks new activity."

Then audit each check against this policy and fix any violations.

---

### M2 — ThetaDecay (Check 14) Evaluates Existing Theta, Not Projected Post-Trade Theta

**Severity:** Medium  
**Area:** Warning vs Rejection Behavior (Check 14)  
**Files:** `risk_limit_checker.py:512–548`

#### Description

`check_theta_decay` reads `portfolio.net_theta_daily` (current portfolio theta) and warns if it exceeds the threshold. It does **not** add the new position's theta contribution.

Compare with Check 15 (VegaExposure):
```python
# Vega: projects post-trade
new_vega = request.option_vega * request.lot_size * direction_sign
projected_vega = portfolio.net_vega + new_vega
```

And Check 8 (NetDelta):
```python
# Delta: projects post-trade
new_delta = request.option_delta * request.lot_size * direction_sign
projected = portfolio.net_delta + new_delta
```

ThetaDecay:
```python
# Theta: current portfolio only — no new position contribution
current_decay = abs(portfolio.net_theta_daily)
```

`RiskRequest` carries no `option_theta` field, so the new position's theta cannot be computed at the check level. The architectural gap is that `RiskRequest` is missing `option_theta: float | None`.

#### Risk

Since ThetaDecay is warn-only, this is not a safety risk. But the warning fires too late — a trade that would push theta over the threshold doesn't trigger a warning for THAT trade; the warning appears on the NEXT evaluation (which reads the updated portfolio theta).

#### Recommended Fix

Add `option_theta: float | None` to `RiskRequest` (None for futures) and compute the projected theta in `check_theta_decay`. This would make all Greek checks consistent in projecting post-trade state.

---

### M3 — Capital Concentration Tests Current Exposure, Not Projected Post-Trade Exposure

**Severity:** Medium  
**Area:** Concentration Logic (Check 7)  
**Files:** `risk_limit_checker.py:235–240`

#### Description

Sub-check A of `check_capital_concentration`:
```python
existing_pct = portfolio.capital_per_underlying_pct.get(request.underlying, 0.0)
conc_ok = existing_pct < conc_limit
```

This checks whether the existing capital in the underlying is already over the limit. It does NOT compute what the concentration would be AFTER adding the new position.

**Scenario:** NIFTY capital = 19%. Limit = 20%. A new trade adds 2% capital to NIFTY → post-trade = 21%.
- The check sees 19% < 20% → PASS
- After the trade, the next evaluation would see 21% → FAIL

The check prevents adding to an already-overconcentrated position, but allows a single trade to push through the limit by a small margin. Sub-check B (per-trade notional) provides the per-trade control, but the two sub-checks serve different concerns.

#### Mitigation (existing)

Sequential evaluation (Constraint 1/C-1 resolution) ensures the portfolio state is updated before the next evaluation. The violation window is bounded to one trade. Sub-check B limits how much that one trade can add (max 10% per trade).

#### Risk

Medium: with `max_capital_per_underlying_pct: 20` and `max_notional_per_trade_pct: 10`, a single trade can push concentration from 19% to 29% (if sub-check B passed). The concentration would then fail for the next trade, but the first trade already exceeded the limit.

#### Recommended Fix

Sub-check A should verify: `existing_pct + notional_pct_of_existing < conc_limit`. However, this requires knowing the capital value of one lot relative to existing capital — which requires the `lot_risk` value already computed for sub-check B. The fix is to combine the checks:

```python
projected_pct = existing_pct + notional_pct  # project post-trade
conc_ok = projected_pct < conc_limit
```

---

### M4 — No Enforcement That Phase D Must Respect `is_warning=True` Before Rejecting

**Severity:** Medium  
**Area:** Warning vs Rejection Behavior  
**Files:** `src/core/domain/risk/risk_decision.py:85`, `risk_limit_checker.py:512–548`

#### Description

`RiskCheckResult.is_warning: bool = False` is set to `True` only by `check_theta_decay`. This field signals that a `passed=False` result must not cause a trade rejection.

**Phase B has no enforcement mechanism for this.** The `RiskCheckResult` VO cannot enforce its own semantics — only `RiskEngineService` (Phase D) can. If Phase D iterates over check results and uses `not result.passed` as the rejection predicate without checking `is_warning`, ThetaDecay breaches become hard rejections.

The test `test_is_warning_always_true` verifies the flag is set, but cannot test that Phase D will respect it — Phase D does not exist yet.

#### Risk

If Phase D contains:
```python
if not result.passed:
    return reject(result.check_name)  # wrong — ignores is_warning
```

Instead of:
```python
if not result.passed and not result.is_warning:
    return reject(result.check_name)  # correct
```

Theta breaches silently become hard rejections. Since theta is warn-only per the design document, this would change the behavior without any compilation or test error.

#### Recommended Fix

Add a helper method to `RiskCheckResult`:

```python
@property
def is_hard_failure(self) -> bool:
    """True when this result requires trade rejection (passed=False and not a warning)."""
    return not self.passed and not self.is_warning
```

Phase D should then use `result.is_hard_failure` rather than `not result.passed`. This forces the intent to be explicit and correct at the call site.

---

### M5 — Pre-Computed Consumed-Percentage Fields Exist But Are Never Read

**Severity:** Medium  
**Area:** Risk Check Correctness  
**Files:** `src/core/domain/risk/account_state.py:49–50`, `risk_limit_checker.py:87–106`

#### Description

`AccountState` carries:
- `daily_loss_consumed_pct: float` — `abs(daily_pnl) / daily_loss_limit_abs × 100`
- `weekly_loss_consumed_pct: float` — `abs(weekly_pnl) / weekly_loss_limit_abs × 100`

These are documented as the percentage of the **absolute limit** consumed. At 100.0, the absolute loss limit is reached.

`check_daily_loss` and `check_weekly_loss` do not read these fields. They recompute a percentage using `session_capital` as the denominator (which gives the percentage-of-capital check, not the absolute-limit check). The two computations produce different results and serve different checks.

This also connects directly to **C1**: if the checker read `daily_loss_consumed_pct >= 100.0` as its absolute-limit check, the fix for C1 would require zero arithmetic.

#### Risk

`daily_loss_consumed_pct` and `weekly_loss_consumed_pct` are written to the database as part of `account_snapshot` in `risk_decisions`. They correctly reflect absolute-limit consumption. The pre-trade check does not enforce the same limit these fields represent, creating an inconsistency between what's stored and what's enforced.

#### Recommended Fix

The `check_daily_loss` implementation should be:
```python
# Percentage-of-capital limit
pct_breached = current_loss_pct >= config.daily_loss.limit_pct
# Absolute INR limit (use pre-computed field)
abs_breached = account.daily_loss_consumed_pct >= 100.0
passed = not (pct_breached or abs_breached)
```

This resolves C1 with the minimum code change.

---

## Low Findings

---

### L1 — `RiskRequest` Does Not Enforce That OPTION Must Carry `option_premium`

**Severity:** Low  
**Area:** Future Asset Compatibility  
**Files:** `src/core/domain/risk/risk_request.py:67–117`

`RiskRequest.__post_init__` allows `instrument_class="OPTION"` with `option_premium=None`. The schema enforces only `option_premium >= 0 if not None`. An OPTION without a premium is semantically invalid but structurally accepted.

Downstream consequence: `check_capital_concentration` silently uses the FUTURE formula (H4), and `PositionSizer` returns 0 lots → Check 12 rejects with `POSITION_SIZE_ZERO`. Safe outcome, but the wrong check fires and the audit trail is misleading.

**Recommended fix:** Add to `RiskRequest.__post_init__`:
```python
if self.instrument_class == "OPTION" and self.option_premium is None:
    raise RiskInvariantError("instrument_class='OPTION' requires option_premium")
```

---

### L2 — `kelly_fraction_effective` Has Different Semantics in Normal vs Fallback Path

**Severity:** Low  
**Area:** Kelly Implementation  
**Files:** `src/core/domain/risk/position_sizer.py:101–120`

In the **normal Kelly path**, `kelly_fraction_effective` is stored as the multiplier applied to raw Kelly capital:
```python
kelly_fraction_effective = sizing_cfg.kelly_fraction  # e.g., 0.25
kelly_capital = session_cap * raw_kelly * kelly_fraction_effective
# actual % of capital = raw_kelly × 0.25 (varies with win statistics)
```

In the **fallback path**, `kelly_fraction_effective` is the direct fraction of capital committed:
```python
kelly_fraction_effective = kelly_fraction * kelly_min_sample_fallback  # e.g., 0.0125
kelly_capital = session_cap * kelly_fraction_effective
# actual % of capital = exactly 1.25% (fixed)
```

The field stores "the Kelly multiplier" in one case and "the fraction of capital" in the other. An analytics consumer reading `kelly_fraction_effective=0.25` cannot know if this means "25% of capital" (it doesn't) or "fractional Kelly multiplier applied to raw Kelly" (it does).

The `sizing_note` field disambiguates the path, but the field semantics should be consistent or explicitly documented.

**Recommended fix:** Rename or add `raw_kelly_fraction: float | None` field to `SizingResult` to store the raw Kelly output (e.g., 0.5 for a 50% Kelly fraction) so the audit trail is interpretable without path-conditional logic.

---

### L3 — `open_positions_count` Duplicated Across `AccountState` and `PortfolioState`

**Severity:** Low  
**Area:** Risk Check Correctness  
**Files:** `account_state.py:52`, `portfolio_state.py:34`

Both `AccountState` and `PortfolioState` carry `open_positions_count: int`. Check 5 (`check_open_positions`) reads `portfolio.open_positions_count`. `account.open_positions_count` is never read by any check.

If the two values drift (e.g., one is stale), the check uses portfolio state while the account state stored in the audit record shows a different value. This creates an audit inconsistency.

**Recommended fix:** Remove `open_positions_count` from `AccountState` (it is portfolio-level data) and standardize on `PortfolioState` as the source of truth for position counts.

---

### L4 — Inconsistent Defensive Coding Pattern for Zero Session Capital

**Severity:** Low  
**Area:** Risk Check Correctness  
**Files:** `position_sizer.py:66`, `risk_limit_checker.py:88–92`

`PositionSizer.compute()` uses an assert:
```python
assert session_cap > 0.0, "session_capital must be > 0 for position sizing"
```

`check_daily_loss` and `check_weekly_loss` use a conditional:
```python
if session_cap > 0.0 and account.daily_pnl < Decimal(0):
    current_loss_pct = ...
else:
    current_loss_pct = 0.0   # zero capital → loss treated as 0%
```

For zero session capital: the loss checks silently pass (treating any loss as 0%), while the sizer raises an `AssertionError`. `AccountState` allows `session_capital >= 0` (zero is valid per the invariant), so this inconsistency can occur in practice.

**Recommended fix:** Standardize on raising `RiskInvariantError` when session_capital is zero, or add `session_capital > 0` as an `AccountState` invariant (the cleaner fix). Zero-capital trading is not a valid state.

---

## Risks

### R1 — Silent Miscalibration Risk for Operators With Capital > 500K

The coincidence of `limit_pct × 500K = limit_abs` means the C1 bug is invisible at the default config. An operator who increases capital to 2M and keeps the default `limit_abs: 10000` will never benefit from the absolute limit. Without a comment in `risk.yaml` documenting this dependency, operators may not realize the limit is unchecked.

### R2 — Cross-Phase Assumption Accumulation

Phase B assumes Greeks are pre-scaled (H3). Phase B assumes Phase D will respect `is_warning` (M4). Phase B assumes Phase D will update `portfolio_state` fast enough that the capital concentration check is meaningful (M3). These are cross-phase assumptions with no formal contract. Each one adds a failure mode that Phase B tests cannot detect.

### R3 — Audit Record Accuracy

Phase C persists `RiskDecision` records. If C1 is not fixed before Phase D begins, audit records will show approved and rejected decisions where the `limit_abs` check was not enforced. These records are append-only. Decisions made with incomplete risk logic cannot be retroactively corrected.

### R4 — Test Suite Gap for Capital > 500K Scenarios

All 87 risk limit checker tests use `session_capital=Decimal("500000")`. No test exercises the scenario where `limit_abs` fires before `limit_pct`. This gap is structural — the default config makes it invisible unless capital is varied.

---

## Future Concerns

### FC1 — Sequential Evaluation Is the Sole TOCTOU Protection

The C-1 resolution (parallelism=1, `asyncio.Lock`) eliminates TOCTOU races for Phase 1. When Phase 2 requires horizontal scaling (Doc 11: >200 instruments threshold), all five TOCTOU-sensitive checks (5, 6, 7, 8, 10) need Redis-atomic reservation logic. The migration path must be documented in the implementation plan before Phase 14 design begins.

### FC2 — Delta Units Are Simplified

The `max_net_delta: 2500` limit is calibrated to the simplified formula `delta × lot_size` (without `× underlying_price / 100`). Doc 17's Portfolio Aggregation section shows the full formula with the price factor. If a future phase adopts the full formula for more accurate risk measurement, `max_net_delta` must be recalibrated by the operator. This dependency should be documented explicitly.

### FC3 — GreeksAggregate Is Not Connected to PortfolioState

`GreeksCalculator.aggregate()` produces `GreeksAggregate`. `PortfolioMonitor` (Phase D) is the intended consumer that writes this aggregate's values into `PortfolioState`. This loop is not yet closed. If `PortfolioMonitor` stores raw Black-Scholes deltas rather than scaled values, all Greek-dependent checks fail silently (see H3).

### FC4 — Option ATR Sizing Does Not Use ATR

For `instrument_class="OPTION"`, the "ATR sizing" formula is:
```
lots = floor(capital_at_risk / (option_premium × lot_size))
```

`atr_14` is not used at all for option sizing. The naming `TestOptionATRSizing` in the test suite is misleading. The design doc (Doc 17) calls this "Max Premium Outlay" sizing, not ATR sizing. If a future phase adds ATR-stop-based option sizing, the current structure may be mistaken for already implementing it.

### FC5 — `max_orders_per_day` Requires PortfolioState Schema Change

Fixing H2 requires adding `orders_today: int` to `PortfolioState`. This is a schema change to a domain value object that Phase D's `RedisPortfolioStateRepository` must write. The Phase D implementation plan should include this field; without it, H2 cannot be fixed.

---

## Architecture Readiness Score

| Dimension | Score | Notes |
|-----------|-------|-------|
| Structural quality (clean arch, pure domain, no I/O) | 20/20 | Exemplary |
| Risk check correctness | 10/20 | C1 (limit_abs), H2 (daily cap), M5 (unused fields) |
| Boundary condition handling | 7/10 | M1 (inconsistency), L4 (zero cap) |
| Kelly implementation | 8/10 | L2 (semantic ambiguity in audit field) |
| ATR sizing implementation | 9/10 | FC4 (naming misleads) |
| Correlation logic | 5/10 | H1 (false rejection), deviation from spec |
| Concentration logic | 7/10 | H4 (option fallback), M3 (projected vs current) |
| Delta exposure logic | 8/10 | Correct for intended simplified formula |
| Greeks aggregation | 6/10 | H3 (unit contract unvalidated) |
| Warning vs rejection behavior | 6/10 | M2 (no projected theta), M4 (no enforcement) |
| Test coverage quality | 9/10 | Good structure; L2 capital-size gap |
| Future asset compatibility | 5/10 | H2 (dead config), L1 (OPTION invariant gap) |

**Total: 100/140 → Architecture Readiness Score: 72 / 100**

---

## Final Recommendation

### NOT_READY_FOR_PHASE_C

**Phase C must not begin until the following are resolved:**

---

**Blocker 1 — C1 (Critical): Fix absolute loss limit enforcement**

`check_daily_loss` and `check_weekly_loss` must enforce `limit_abs` in addition to `limit_pct`. The simplest fix uses the pre-computed `daily_loss_consumed_pct >= 100.0` already present on `AccountState`. Two new tests must be added: loss above `limit_abs` but below `limit_pct × session_capital` (requires `session_capital > 500K` in test). Must be fixed before Phase C because Phase D will persist decisions made with incomplete loss limit logic to an append-only table.

---

**Blocker 2 — H1 (High): Resolve GROSS correlation formula false rejection**

Either fix the GROSS formula to correctly handle opposing-direction trades (Option A in the finding), or formally accept it as a deviation with explicit documentation of its trigger conditions and a plan to revisit for Phase 2. The current state — a documented deviation that has an undocumented false-rejection case — is insufficient for a production system.

---

**Recommended Before Phase C (Non-Blocking):**

- **H2:** Add `orders_today: int` to `PortfolioState` schema before Phase C generates the DB models that derive from portfolio state. Retroactively changing this field after Phase C is a schema migration.

- **H4:** Add OPTION-requires-premium invariant to `RiskRequest`. This is a 3-line fix that closes a silent audit-trail gap.

- **M4:** Add `RiskCheckResult.is_hard_failure` property. Phase D will be written against this interface; making it explicit now costs nothing and prevents a class of Phase D bugs.

---

**Phase B issues that CAN be fixed in parallel with Phase C (do not block):**

L1, L2, L3, L4, M1, M2, M3, M5 — these are correctness refinements and documentation improvements that do not affect what Phase C generates (DB models, migration, repositories). They should be resolved before Phase D begins.

---

*Audit completed: 2026-06-13. All findings derived from direct code review of Phase B implementation against Phase 13 design documents. No code was modified.*
