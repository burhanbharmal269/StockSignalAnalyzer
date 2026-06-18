# Expiry Day Logic Report — Phase 4

**Date:** 2026-06-18

---

## The Problem

The old system had a flat IV percentile gate: if `iv_percentile > 75`, the signal was
rejected with `"iv_too_expensive"`. This was correct for positional option buying but
**broken for intraday** because:

On expiry day (0-DTE), IV percentile is structurally at the 80–90th percentile.
This is not because options are "expensive" in the traditional sense — it is because
theta decay is accelerating exponentially, compressing time value, which makes the
*implied volatility of the remaining premium* appear high relative to historical levels.

A 0-DTE option that is correctly priced will still show IV percentile at 85–95 on
most expiry days. The old gate would reject all of these.

---

## Solution: DTE-Aware IV Thresholds

Implemented in `signal_scanner_service.py` — computed from nearest available DTE
across chain entries before the IV gate fires.

```python
if _near_dte == 0:   _iv_limit = 95   # expiry day
elif _near_dte == 1: _iv_limit = 88
elif _near_dte in (2, 3): _iv_limit = 80
else:                _iv_limit = 75   # positional original
```

---

## DTE → IV Threshold Rationale

| DTE | IV Pct Typical Range on NSE | Our Limit | Logic |
|---|---|---|---|
| 0 (expiry) | 80–92 | 95 | Only reject structurally broken IV (circuit/manipulation) |
| 1 | 65–80 | 88 | Slightly elevated but not at expiry-day levels |
| 2–3 | 50–70 | 80 | Slightly relaxed — near-term but not expiry |
| 4–7 | 35–60 | 75 | Standard positional gate |
| 8+ | 20–50 | 75 | Standard positional gate |

---

## What Is NOT Changed

The IV percentile gate is NOT removed. It is recalibrated:

- **IV percentile > 95 on expiry day**: STILL rejected. This signals a circuit-breaker
  event, news shock, or data error. Intraday buying in such conditions has negative
  expected value even with directional accuracy.
- **IV percentile > 88 at 1-DTE**: Still rejected. Elevated IV on pre-expiry day
  without a corresponding strong directional catalyst = IV crush risk.

The filter remains meaningful at all DTE levels — it is simply calibrated to the
structural IV levels at each DTE tier.

---

## Implementation Verification

The DTE computation extracts minimum DTE from `chain_data["entries"]` at gate-check
time (before `select()` is called), handling both `str` and `date` expiry formats.
If no valid expiry is parseable, `_near_dte = None` and the threshold defaults to 75.
