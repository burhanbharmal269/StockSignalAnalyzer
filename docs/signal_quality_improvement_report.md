# Signal Quality Improvement Report — Phase 9

**Date:** 2026-06-18

---

## Active Hard Gates (Implemented)

These gates fire before option contract selection and return early with a rejection
code. They are logged at WARNING level and tracked in signal analytics.

| Gate | Condition | Return Code | Rationale |
|---|---|---|---|
| RSI Extreme | LONG + RSI > 75 or SHORT + RSI < 25 (15m) | `rsi_extreme` | Buying into exhausted momentum — chasing, not leading |
| IV Too Expensive | IV percentile > DTE-adjusted limit | `iv_too_expensive` | IV crush risk structural — poor option buyer entry |
| No Contract | Option play selection returns None | `no_contract` | Signal not actionable without a contract |

---

## Quality Filters Already in Scoring

The scoring engine implicitly filters by quality:

| Filter | Implementation |
|---|---|
| Trend quality | ADX gate: score = 0 if ADX < 15.0 (hard gate in TrendComponent) |
| Volume expansion | VolumeComponent: vol ratio < 0.5 returns score 3/15 (minimal) |
| OI confirmation | OIBuildupComponent: ambiguous OI now scores only 1.5 pts (reduced from 4 pts) |
| Market regime alignment | Regime multipliers penalize wrong strategies in wrong regimes |
| Liquidity threshold | OptionStrikeSelector: OI >= 100, LTP >= ₹1 on all candidates |

---

## Signal Gate Thresholds (Config-Driven)

```yaml
signal:
  gate:
    min_score: 40        # minimum total score to proceed
    min_confidence: 35   # minimum confidence floor
```

For intraday, these are appropriate. A score of 40 with 35% confidence represents a
single strong confirming factor (e.g., ADX trend alone). The signal will have reduced
sizing (Grade B) but is still valid.

---

## R:R Gate

**R:R >= 1.75:1** is enforced through the intraday_risk config:
- Grade A: 35% target / 20% SL = 1.75:1
- Grade B: 28% target / 15% SL = 1.87:1

No signal can generate a play where target < SL (minimum LTP = ₹1 and both SL/target
are multipliers of entry, so R:R is structurally enforced).

---

## Recommended Future Improvements

These are NOT implemented (would require architecture changes) but are noted for the
roadmap:

1. **Liquidity score component**: Add a dedicated scoring component for option chain
   liquidity (spread, depth) — currently proxied by OI in the selector.

2. **Opening range breakout detector**: First-candle high/low tracking as a binary
   signal tag — allows strategy-type-level filtering in analytics.

3. **FII options data**: When SEBI/NSE makes live FII options OI data available,
   the OIBuildupComponent already has an `fii_adjustment` method ready to use.
