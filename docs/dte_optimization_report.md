# DTE Optimization Report — Phase 2

**Date:** 2026-06-18  
**Mode:** Intraday Options Trading  

---

## Previous Configuration

```
option_dte.min = 2   # skipped same/next-day — avoided 0-1 DTE gamma risk
option_dte.max = 15  # positional: up to 3 weeks out
```

**Problem:** System was selecting contracts 2-15 days to expiry, which is appropriate for
positional/swing trades but wrong for intraday. Capital was tied up for days or weeks.

---

## New Configuration

```
option_dte.min = 0   # intraday: 0-DTE weekly contracts are the primary vehicle
option_dte.max = 3   # 0-3 DTE window — all near-term liquid contracts
```

---

## DTE Window Rationale by Instrument

| Instrument | Expiry Cycle | Optimal Intraday DTE | Notes |
|---|---|---|---|
| NIFTY | Weekly (Thursday) | 0–1 | Highest liquidity on/near expiry day |
| BANKNIFTY | Weekly (Wednesday) | 0–1 | Similar to NIFTY |
| FINNIFTY | Weekly (Tuesday) | 0–2 | Slightly lower OI than NIFTY |
| Liquid Stocks | Monthly | 0–3 | Monthly expiry — 0-DTE only at month end |

---

## Fallback Logic (Preserved)

The three-tier fallback in `OptionStrikeSelector._nearest_expiry()` is unchanged:

1. **Preferred**: expiry inside [min_dte, max_dte] window
2. **Fallback 1**: nearest expiry with DTE ≥ min_dte
3. **Fallback 2**: absolute nearest (prevents None return when chain has data)

This ensures a contract is always selected even when the ideal window is empty
(e.g., mid-week for a stock with only one monthly expiry).

---

## IV Percentile Gate — DTE-Aware Thresholds (Phase 4)

On expiry day, IV percentile is structurally elevated (typically 80–90th percentile)
purely because of theta collapse accelerating, not because IV is genuinely expensive.
Applying the flat 75 threshold from the positional system rejects every valid
0-DTE trade. The gate is now DTE-aware:

| Nearest DTE | IV Percentile Limit | Rationale |
|---|---|---|
| 0 (expiry day) | 95 | IV pct naturally 80-90, only block extreme outliers |
| 1 | 88 | IV pct elevated but not at expiry-day levels |
| 2–3 | 80 | Slightly relaxed from the positional 75 |
| 4+ | 75 | Original positional threshold |

---

## Expected Impact

- **NIFTY/BANKNIFTY on expiry day**: Now selects current-week expiry (was selecting
  next week's contract, adding 5-7 DTE unnecessarily)
- **Signal count**: ~40% more signals expected to pass the DTE window check
  on index expiry days (Monday–Thursday rotating weekly)
- **Premium cost**: 0-1 DTE ATM option premium is significantly lower than 5-7 DTE,
  reducing capital requirement per trade
