# 17 — Portfolio Risk Engine

## Purpose

Define the complete risk architecture including pre-trade signal evaluation, real-time position monitoring, portfolio-level Greeks tracking, volatility-adjusted position sizing, graduated loss response, and the full hard limits matrix. The Risk Engine is the most critical safety system after the Kill Switch. No signal reaches the OMS without passing through it.

---

## Design Principles

- The Risk Engine is the last gate before order submission. There is no code path to the broker that bypasses it.
- Every risk decision (approve or reject) is persisted with full context. No silent rejections.
- Risk limits are configuration, not code. Changing a limit requires no deployment.
- The Risk Engine operates on two time horizons: pre-trade (signal time) and real-time (continuous position monitoring).
- Correlation-aware: two correlated positions count as amplified directional exposure at portfolio level.
- Greeks-aware: for FnO positions, net delta is tracked at portfolio level, not just per-position notional.

---

## Two Operating Modes

### Mode 1: Pre-Trade Check (Signal Evaluation)

Invoked synchronously for every `signal.confidence.computed` event before publishing `signal.risk.approved` or `signal.risk.rejected`.

All 15 checks must pass. One failure = signal rejected with a specific reason code.

### Mode 2: Real-Time Portfolio Monitor (Continuous)

Runs as an independent async loop every 30 seconds during market hours. Does not block signal generation.

Monitors:
- MTM P&L vs daily/weekly loss limits
- Net portfolio Greeks
- Margin utilization vs available margin
- Individual position stop-loss proximity
- Portfolio drawdown from high-water mark

Actions:
- Limit approach (threshold 1): emit `risk.drawdown.alert`, reduce new position size
- Limit breach (threshold 2): activate kill switch

---

## Risk Limit Configuration

All limits are in `risk_parameters` table and `config/risk.yaml`. The table takes precedence over the file, allowing runtime adjustment without restart.

```yaml
risk:
  # Loss Limits
  daily_loss_limit_pct:          2.0    # % of account capital
  daily_loss_limit_abs:          10000  # INR; whichever triggers first
  weekly_loss_limit_pct:         5.0
  weekly_loss_limit_abs:         25000

  max_drawdown_pct:              10.0   # from rolling 30-day high-water mark

  # Graduated Response Thresholds (as % of respective loss limit)
  reduce_size_at_pct:            50     # → 50% position size
  paper_mode_at_pct:             75     # → paper trading mode
  kill_switch_at_pct:            100    # → kill switch activation

  # Position Limits
  max_open_positions:            10
  max_positions_per_underlying:  3
  max_capital_per_underlying_pct: 20
  max_notional_per_trade_pct:    10

  # Greeks Limits (FnO)
  max_net_delta:                 0.5    # delta units (delta × lots × lot_size × price)
  max_net_gamma_pct:             0.1    # as % of portfolio value
  max_net_vega_pct:              5.0
  max_theta_daily_decay_pct:     0.5    # max daily theta burn as % of capital

  # Order Rate Limiting
  max_orders_per_minute:         5
  max_orders_per_day:            50

  # Margin
  margin_utilization_limit_pct:  80     # alert at 80%; block new positions at 90%
  min_free_margin_pct:           20

  # Risk-Reward
  min_risk_reward_ratio:         1.5
  max_risk_reward_ratio:         10.0   # unusually high R:R may indicate data error

  # Position Sizing
  risk_per_trade_pct:            1.0    # max % of capital to risk per trade
  max_position_size_lots:        50
  kelly_fraction:                0.25   # fractional Kelly
```

---

## Position Sizing Formula

Position sizing is volatility-adjusted. The system computes both ATR-derived and Kelly-derived sizes and uses the smaller.

### ATR-Based Sizing

```
ATR             = Average True Range over 14 periods on signal timeframe
Stop Distance   = abs(entry_price - stop_loss_price)
Capital at Risk = account_capital × risk_per_trade_pct / 100

For option buying:
    Max Premium Outlay = Capital at Risk
    Lots = floor(Max Premium Outlay / (option_premium × lot_size))

For futures:
    Lots = floor(Capital at Risk / (Stop Distance × lot_size))

Lots = min(Lots, max_position_size_lots)
```

### Fractional Kelly Sizing

```
Win Rate       = strategy_win_rate_30d
Win_Loss_Ratio = avg_winner_pnl / avg_loser_pnl   (from StrategyPerformanceRepo)

Kelly Fraction = Win_Rate - ((1 - Win_Rate) / Win_Loss_Ratio)
Adj Kelly      = Kelly Fraction × kelly_fraction_config

Capital        = account_capital × Adj Kelly
Lots           = floor(Capital / (option_premium × lot_size))
Lots           = min(Lots, max_position_size_lots)
```

### Final Sizing

```
Final Lots = min(ATR_derived_lots, Kelly_derived_lots)
```

If Final Lots = 0: signal is rejected with `POSITION_SIZE_ZERO`.

### Graduated Size Reduction

```
Normal operation:         Final Lots × 1.0
At reduce_size threshold: Final Lots × 0.5 (rounded down to nearest lot)
At paper_mode threshold:  0 (signal generated but not executed)
```

---

## Portfolio Greeks Tracking

### Greeks Calculation (Black-Scholes)

For each open FnO position:

```
Inputs:
    S  = current underlying LTP (from Redis cache)
    K  = strike price
    T  = DTE / 365.0
    r  = 0.065  (RBI repo rate, configurable)
    σ  = current IV of the specific option (from option chain cache)

Outputs:
    Delta = ∂V/∂S
    Gamma = ∂²V/∂S²
    Theta = ∂V/∂t  (daily decay in INR)
    Vega  = ∂V/∂σ  (per 1% change in IV)
```

For long positions: Delta, Gamma, Vega are positive; Theta is negative.
For short positions: all signs are reversed.

### Portfolio-Level Aggregation

```
Portfolio Net Delta = Σ (position.delta × position.lots × lot_size × underlying_price / 100)
                     expressed in INR

Portfolio Net Gamma = Σ (position.gamma × position.lots × lot_size × underlying_price² / 100)
                     expressed in INR per 1% underlying move

Portfolio Net Theta = Σ (position.theta × position.lots × lot_size)
                     expressed in INR per calendar day

Portfolio Net Vega  = Σ (position.vega × position.lots × lot_size)
                     expressed in INR per 1% IV change
```

### Greeks Update Frequency

- On every tick received for a held underlying (via event bus)
- On the real-time monitor loop (every 30 seconds as a minimum)
- After every order fill event

Greeks are stored in Redis with TTL 60 seconds for sub-millisecond read by pre-trade checks.

---

## Correlation-Adjusted Exposure

### Correlation Matrix

A pairwise correlation matrix is computed daily using 60-day rolling returns for all covered underlyings. Updated at 07:45 IST and stored in Redis as a JSON object.

```
Example correlations (illustrative values):
    NIFTY50   ↔ BANKNIFTY:  0.85
    NIFTY50   ↔ SENSEX:     0.98
    NIFTY50   ↔ RELIANCE:   0.45
    NIFTY50   ↔ USDINR:    -0.35
    RELIANCE  ↔ ONGC:       0.62
```

### Correlation Check in Pre-Trade

Before approving a new signal, the risk engine computes the Effective Concentration Ratio:

```
Effective Concentration = new_signal.position_delta
                        + Σ (existing_position.delta × correlation(existing.underlying, new.underlying))

If Effective Concentration > max_net_delta_limit: reject signal
```

This ensures a portfolio already at 0.4 net delta cannot add a 0.3-delta position in a correlated instrument even if each individual position is within limits.

---

## Real-Time MTM and Loss Monitoring

### MTM P&L Calculation

```
MTM P&L    = Σ (position.quantity × (current_ltp - position.avg_cost) × lot_size)
Realized   = Σ (closed_trade.pnl) for the current trading day
Total P&L  = MTM P&L + Realized P&L
```

MTM is recomputed on every tick received for a held instrument.

### Loss Limit Monitoring Loop (every 30 seconds)

```
1. Compute Total Daily P&L
2. Daily Loss Consumed % = abs(Total Daily P&L) / daily_loss_limit_abs × 100
   (only when P&L is negative)

3. If consumed % >= kill_switch_at_pct (100%):
   → Activate kill switch immediately
   → Publish risk.limit.breached event

4. If consumed % >= paper_mode_at_pct (75%):
   → Set trading_mode = PAPER in Redis
   → Publish risk.drawdown.alert
   → Send notification

5. If consumed % >= reduce_size_at_pct (50%):
   → Set position_size_multiplier = 0.5 in Redis
   → Publish risk.drawdown.alert (severity=WARNING)
```

### Drawdown Monitoring

```
High Water Mark (HWM) = peak account value in rolling 30-day window
Current Drawdown %    = (HWM - current_account_value) / HWM × 100

If Drawdown % >= max_drawdown_pct:
    → Activate kill switch
```

---

## Pre-Trade Risk Check Flow

```
RiskEngine.evaluate(signal: Signal) -> RiskDecision:

 1. kill_switch_check()                  → FAIL if kill switch active
 2. daily_loss_limit_check()             → FAIL if daily loss at 100%
 3. weekly_loss_limit_check()            → FAIL if weekly loss at 100%
 4. drawdown_check()                     → FAIL if max drawdown reached
 5. open_positions_check()               → FAIL if max_open_positions reached
 6. symbol_concentration_check()         → FAIL if max_positions_per_underlying reached
 7. capital_concentration_check()        → FAIL if max_capital_per_underlying_pct exceeded
 8. net_delta_check()                    → FAIL if new position would breach max_net_delta
 9. correlation_check()                  → FAIL if effective concentration breached
10. margin_check()                       → FAIL if insufficient margin (real-time broker query)
11. risk_reward_check()                  → FAIL if signal R:R < min_risk_reward_ratio
12. position_size_check()                → FAIL if computed lots = 0
13. order_rate_check()                   → FAIL if order rate limit exceeded
14. theta_decay_check()                  → WARN (not a hard block; recorded in decision)
15. vega_exposure_check()                → FAIL if net vega breaches limit

→ All checks passed: RiskDecision(approved=True, position_size=final_lots, ...)
→ Any check failed: RiskDecision(approved=False, rejection_code=<first_failure>, all_checks=[...])
```

---

## RiskDecision Schema

```
RiskDecision:
    signal_id:            UUID
    approved:             bool
    rejection_reason:     str | None
    rejection_code:       RiskRejectionCode
    position_size_lots:   int | None         (approved size, if approved)
    size_reduction_pct:   float              (0 if no reduction, 50 if at reduce threshold)
    checks:               list[RiskCheckResult]
    account_state:        AccountState       (snapshot at evaluation time)
    evaluated_at:         datetime
```

```
RiskCheckResult:
    check_name:      str
    passed:          bool
    current_value:   float | None    (e.g., 45.2 for 45.2% daily loss consumed)
    limit_value:     float | None    (e.g., 100.0)
    message:         str
```

---

## Risk Audit Table

```
risk_decisions
─────────────────────────────────────────────────────────
id                  BIGSERIAL        PRIMARY KEY
signal_id           UUID             NOT NULL    FK → signals
approved            BOOLEAN          NOT NULL
rejection_reason    TEXT
rejection_code      VARCHAR(50)
position_size_lots  INTEGER
size_reduction_pct  NUMERIC(5,2)
checks              JSONB            NOT NULL
account_state       JSONB            NOT NULL
evaluated_at        TIMESTAMPTZ      NOT NULL
```

This table is append-only. No updates or deletes.

---

## Account State Snapshot

Captured at each pre-trade check and stored in `risk_decisions.account_state`:

```
AccountState:
    account_capital:           Decimal
    available_margin:          Decimal
    used_margin:               Decimal
    margin_utilization_pct:    float
    daily_pnl:                 Decimal    (realized + MTM)
    daily_loss_consumed_pct:   float
    weekly_pnl:                Decimal
    weekly_loss_consumed_pct:  float
    drawdown_from_hwm_pct:     float
    open_positions_count:      int
    net_portfolio_delta:       float
    net_portfolio_theta:       float      (daily decay in INR)
    net_portfolio_vega:        float
    position_size_multiplier:  float      (1.0, 0.5, or 0.0)
    trading_mode:              TradingMode  (LIVE, PAPER, BLOCKED)
    captured_at:               datetime
```

---

## Weekly Loss Tracking

Weekly loss is tracked on a rolling 5-trading-day basis, not a calendar week. This prevents resetting limits mid-drawdown at the calendar week boundary.

```
Rolling 5-Day P&L = sum of realized P&L for the last 5 trading days
                  + current day unrealized MTM
```

---

## Settlement Risk (Phase 2+)

For equity delivery positions (Phase 2), the risk engine tracks:
- T+1 pay-in obligation: amount due for settlement
- T+2 delivery obligation: shares to deliver on short sales

The risk engine blocks new equity delivery positions if T+1 obligations exceed 90% of available cash.

---

## Observability

| Metric | Type | Labels | Description |
|---|---|---|---|
| `risk_checks_total` | Counter | `check_name`, `result` | All check outcomes |
| `risk_signals_approved_total` | Counter | `symbol`, `direction` | Approved signals |
| `risk_signals_rejected_total` | Counter | `rejection_code` | Rejected signals by reason |
| `risk_daily_loss_pct` | Gauge | | Daily loss as % of limit |
| `risk_weekly_loss_pct` | Gauge | | Weekly loss as % of limit |
| `risk_drawdown_pct` | Gauge | | Drawdown from HWM |
| `risk_portfolio_delta` | Gauge | | Net portfolio delta |
| `risk_portfolio_theta_daily` | Gauge | | Daily theta decay in INR |
| `risk_portfolio_vega` | Gauge | | Net portfolio vega |
| `risk_margin_utilization_pct` | Gauge | | Margin used / available |
| `risk_open_positions` | Gauge | | Current open position count |
| `risk_position_size_multiplier` | Gauge | | Current size multiplier |
| `risk_engine_check_duration_seconds` | Histogram | | Pre-trade check latency |

**SLO:** Pre-trade risk check must complete in P99 < 200ms, including real-time margin query from broker.
