# Market Close Exit Report — Phase 6

**Date:** 2026-06-18

---

## Requirement

No intraday option position should be carried overnight. Options bought on 0-DTE
lose all time value at close. On 1-3 DTE contracts, overnight risk includes gap
risk, news events, and FII flows that can move the underlying against position
before market opens. The system must enforce a hard exit.

---

## Implementation: `MarketCloseExitService`

**File:** `src/core/application/services/market_close_exit_service.py`

**Class:** `MarketCloseExitService`

**Registered as:** `"market_close_exit"` background task in `BackgroundTaskRegistry`

---

## Behavior

```
Poll every 30 seconds
  ├── IST time < 15:20 → sleep
  └── IST time >= 15:20 AND not yet fired today
        ├── Find all signals in RISK_APPROVED or RISK_PENDING state
        ├── Bulk update state → EXPIRED
        ├── Publish SignalExpired event for each
        └── Mark today as fired (prevents double-fire)
```

---

## Cutoff Time

**15:20 IST** — 10 minutes before exchange close (15:30).

Rationale:
- NSE market closes at 15:30
- 10-minute buffer allows the broker execution pipeline (if AUTOMATIC) to process
  exit orders before the exchange session ends
- MIS (Margin Intraday Square-off) product on Kite already auto-squares at ~15:15–15:20
  for MIS positions; this service aligns with that window

---

## Execution Mode Handling

| Mode | Action |
|---|---|
| MANUAL | Signal state → EXPIRED. User sees status change on dashboard as exit alert. |
| AUTOMATIC | Signal state → EXPIRED + `SignalExpired` event published → `PipelineEventHandler` routes exit order if position is open |

No new broker coupling is needed. The existing `SignalExpired → OMS` event flow
handles AUTOMATIC mode. The `MarketCloseExitService` only manages signal state.

---

## Daily Reset

`_cutoff_fired_date` resets automatically when a new trading day begins (midnight IST
rollover detected by date string comparison). The service is always running —
no restart needed at market open.

---

## Configuration

```yaml
signal:
  intraday_risk:
    cutoff_time: "15:20:00"   # change to "15:15:00" for earlier exit
```

Parsed at startup via `IntradayRiskConfig.cutoff_time`. No restart needed if
changed via config and backend restart.

---

## Validation

The service logs at WARNING level when it fires:

```
market_close_exit.cutoff_fired ist=15:20:01 IST expired_signals=3 — no intraday carry-over
```

Each expired signal is logged at INFO:

```
market_close_exit.signal_expired signal_id=<uuid>
```
