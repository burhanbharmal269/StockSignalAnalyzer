# Option Contract Selection Report — Phase 3

**Date:** 2026-06-18

---

## Previous Selection Logic

```python
# Old: simple ATM selection
strike_entry = min(expiry_entries, key=lambda e: abs(float(e["strike"]) - underlying_price))
```

Only ATM by price proximity. No liquidity ranking. Would select an illiquid strike
if it happened to be numerically closest.

---

## New Selection Logic

### `_best_contract()` — OI-Ranked Selection

```python
# New: rank ATM±2 candidates by OI, fallback to absolute ATM
candidates = entries within ATM ± 2 strikes with OI >= 100
best = max(candidates, key=(OI desc, distance to ATM asc))
```

**Evaluation window:** ATM ± 2 strikes (configurable via `_MAX_STRIKE_SPREAD = 2`)

**Ranking criteria:**
1. **Primary:** OI descending — highest open interest = most liquid = tightest effective spread
2. **Secondary:** proximity to ATM — prefer at-the-money for delta exposure

**Minimum OI floor:** 100 contracts (`_MIN_OI_FLOOR = 100`) — screens ghost/adjusted strikes

**Fallback:** If no candidate meets the OI floor, absolute ATM is selected
(preserves original behavior — never returns None due to OI filter alone).

---

## Contract Evaluation Window (ATM ± 2)

For a NIFTY signal at 24,000:

| Strike | Distance | OI (example) | Selected? |
|---|---|---|---|
| 23,950 | 50 (2 strikes OTM PE) | 800,000 | Candidate |
| 24,000 | 0 (ATM) | 1,200,000 | ✓ Winner (highest OI) |
| 24,050 | 50 (1 strike OTM CE) | 950,000 | Candidate |
| 24,100 | 100 (2 strikes OTM CE) | 300,000 | Candidate |
| 24,150 | 150 (3 strikes OTM) | 50,000 | Out of window |

Result: 24,000 CE selected (highest OI at ATM).

---

## Parameters Excluded (Not in Chain Data)

The following liquidity metrics are not available in `option_chain_snapshots.entries`:

| Metric | Status | Proxy Used |
|---|---|---|
| Bid-ask spread | ❌ Not in schema | OI as proxy |
| Volume (intraday) | ❌ Not in schema | OI as proxy |
| IV per strike | ❌ Not per entry | chain-level iv_percentile |

**OI is the best available proxy** for intraday liquidity. High OI = market makers
actively quoting = tighter spreads in practice.

---

## Minimum LTP Filter

`_MIN_LTP = 1.0` — eliminates deep OTM strikes with LTP < ₹1 that have no
practical tradability due to minimum tick size.
