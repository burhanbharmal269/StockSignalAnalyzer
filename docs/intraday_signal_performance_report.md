# Intraday Signal Performance Report — Phase 11

**Date:** 2026-06-18

---

## Current Outcome Tracking Infrastructure

`SignalOutcomeTrackerService` already runs as a background task, polling every 15 minutes.
It uses `HistoricalDataService` to fetch candle data for each tracked signal and computes
outcome metrics stored in the signal analytics layer.

---

## Metrics Tracked Per Signal

| Metric | Tracked? | Location |
|---|---|---|
| Target hit | ✓ | SignalAnalyticsService.record() |
| Stop hit | ✓ | SignalAnalyticsService.record() |
| MFE (Maximum Favorable Excursion) | ✓ | OutcomeTracker fetches OHLC after entry |
| MAE (Maximum Adverse Excursion) | ✓ | OutcomeTracker fetches OHLC after entry |
| Return at 30 min | ✓ | Computed from 2 candles after signal |
| Return at 1 hour | ✓ | Computed from 4 candles after signal |
| Return at EOD | ✓ | Computed from close-of-day candle |

All metrics are tracked regardless of execution mode (MANUAL or AUTOMATIC).

---

## Intraday Performance KPIs

Once live signals accumulate (target: 30+ signals per strategy), evaluate:

| KPI | Target | Concern Threshold |
|---|---|---|
| Win Rate (target hit before stop) | > 55% | < 45% → strategy review |
| Profit Factor (gross profit / gross loss) | > 1.5 | < 1.0 → immediate strategy review |
| Average R achieved | > 0.8R | < 0.5R → entries too late in move |
| MFE/MAE ratio | > 2.0 | < 1.2 → signal direction wrong |
| Signal-to-noise (accepted/scanned) | 5–15% | > 30% → gates too loose |
| IV crush loss rate | < 10% | > 20% → IV gate needs tightening |

---

## Grade Performance Split

Track separately by grade:

| Grade | Expected Win Rate | Notes |
|---|---|---|
| A (score ≥ 65) | > 60% | Multiple confirmation — should outperform |
| B (score 40-64) | > 50% | Single factor — acceptable but monitor |

If Grade B win rate < 45% over 30+ signals → consider raising gate to 50.

---

## Rejection Reason Tracking

Each gate returns a string reason code. The signal analytics service should track
rejection reason distribution to identify if any gate is too aggressive:

| Rejection Code | Meaning | Acceptable Rate |
|---|---|---|
| `rsi_extreme` | RSI > 75 (LONG) or < 25 (SHORT) | 5–15% of signals |
| `iv_too_expensive` | IV percentile above DTE threshold | 10–25% on expiry days |
| `no_contract` | No liquid option contract found | < 5% for index; up to 20% for stocks |
| `rsi_weak` | Weak RSI gate in TrendComponent | Normal — part of scoring |

---

## How to Access Performance Data

1. **Dashboard**: Analytics tab — strategy performance by type and regime
2. **API**: `GET /api/v1/analytics/strategy-performance`
3. **DB**: `signal_analytics` table — query by `strategy_type`, `regime`, `signal_type`

---

## Review Schedule

- **After first 10 signals**: Visual inspection only — too few for statistics
- **After 30 signals per strategy**: Compute win rate, profit factor
- **After 100 signals total**: Full KPI review — adjust config if needed
- **Monthly**: Regime performance split — check if TRENDING regime still outperforms
