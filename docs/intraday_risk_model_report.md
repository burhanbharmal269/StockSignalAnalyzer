# Intraday Risk Model Report — Phase 5

**Date:** 2026-06-18

---

## Positional vs Intraday Risk Parameters

| Parameter | Old (Positional) | New (Intraday) | Rationale |
|---|---|---|---|
| Grade A SL | 30% | 20% | Intraday premium decays fast — tight SL prevents overnight-style losses in same-day |
| Grade A Target | 60% | 35% | Realistic intraday move; 60% target on 0-DTE takes multiple hours to hit |
| Grade B SL | 25% | 15% | Even tighter on lower-conviction setups |
| Grade B Target | 45% | 28% | Still 1.87:1 R:R at lower premium multiple |
| R:R Ratio (A) | 2:1 | 1.75:1 | Slight reduction accepted — intraday frequency compensates |
| R:R Ratio (B) | 1.8:1 | 1.87:1 | Grade B R:R actually improves slightly |

---

## Config Location

All parameters in `config/signal.yaml` under `intraday_risk:`. No hardcoding.

```yaml
intraday_risk:
  grade_a_min_score: 65.0
  grade_a_sl_pct: 0.20
  grade_a_target_pct: 0.35
  grade_b_sl_pct: 0.15
  grade_b_target_pct: 0.28
  trailing_stop_enabled: true
  breakeven_enabled: true
  position_timeout_minutes: 90
  cutoff_time: "15:20:00"
```

---

## Grade Classification

**Grade A** (score ≥ 65): High conviction signal.
- Multiple confirming indicators (OI + trend + VWAP alignment)
- Wider target appropriate — move has momentum behind it
- 20% SL allows premium fluctuation without premature stop-out

**Grade B** (score 40–64): Moderate conviction.
- Single strong indicator or partial confirmation
- Tighter SL — less tolerance for adverse moves
- 28% target still achievable within 2-3 hour intraday window

---

## Trailing Stop Logic (Alert-Based)

`trailing_stop_enabled: true` is a flag for future alert generation.
Current implementation: signals are marked with their SL at entry time.
The outcome tracker monitors price movement — when premium retraces > 50% of
gained premium, a trailing stop alert is generated in logs.

**Breakeven logic**: when option LTP reaches halfway to target, SL is conceptually
moved to entry. This is tracked in outcome monitoring — no broker order modification
currently (MANUAL mode: user acts on the alert).

---

## Position Timeout

`position_timeout_minutes: 90` — if a signal in RISK_APPROVED state has not been
acted upon within 90 minutes, the `SignalExpiryWorker` will expire it at the next
poll cycle. This prevents stale signals from being traded late in the session when
the setup has already invalidated.

---

## Capital Impact

Example: NIFTY at 24,000, ATM CE at ₹80 premium, lot size 75.

| Grade | SL | Capital at Risk | Target | Net at Target |
|---|---|---|---|---|
| A | 20% = ₹16/lot → ₹1,200/lot | ₹1,200 | 35% = ₹28/lot → ₹2,100/lot | +₹900 |
| B | 15% = ₹12/lot → ₹900/lot | ₹900 | 28% = ₹22.40/lot → ₹1,680/lot | +₹780 |

With ₹1,50,000 capital: ~12 Grade A lots or ~16 Grade B lots possible simultaneously.
