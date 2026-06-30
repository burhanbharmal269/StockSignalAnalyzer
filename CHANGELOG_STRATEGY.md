# CHANGELOG_STRATEGY.md — Strategy Change Log

All changes to the signal generation strategy, risk parameters, targets, confidence logic,
scoring, filters, indicators, option selection, and regime logic must be recorded here.

**CURRENT STATUS: FROZEN** — No entries expected until ≥ 500 completed trades.

## How to Record a Change

Only record changes that cleared all 7 governance gates and were deployed to production.
Reference the experiment ID from the `experiments` table.

```
## [STRATEGY_VERSION] — YYYY-MM-DD

**Experiment:** EXP-XXXXX
**Author:** <name>
**Approved by:** <admin>
**p-value:** <value>  |  **Improvement:** <pct>%  |  **Trades in experiment:** <n>

### What Changed
- ...

### Why
...

### Validation Summary
- Control win rate: X%  |  Treatment win rate: Y%
- Z-score: Z  |  p-value: P  |  Confidence: C%

### Rollback
...
```

---

## [25.0.0] — 2026-06-30

**Initial frozen baseline.** Platform frozen at this version.
No strategy changes. Experiment framework established.

**Versions:**
- strategy_version: 25.0.0
- risk_version: 25.0.0
- target_version: 25.0.0
- confidence_version: 25.0.0
- overlay_version: 25.0.0

**Freeze threshold:** 500 completed trades required before any strategy change.

---

*All future entries must follow the template above.*
