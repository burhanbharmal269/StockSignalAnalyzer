# Execution Mode Refactor — Audit Report

**Date:** 2026-06-17  
**Scope:** Removal of Paper Broker dependency from signal pipeline; introduction of Execution Lock

---

## Executive Summary

The platform has been refactored to operate as a **Live Market Intelligence Platform first, Automatic Trading Platform second**.

Signal generation, storage, analytics, and outcome tracking are now permanently active and fully independent of any execution setting. The only thing controlled by execution mode is **whether orders are sent to Kite Connect**.

---

## What Changed

### New Concept: Execution Lock

Replaces the paper-mode kill switch auto-deactivation pattern.

| Component | Location |
|-----------|----------|
| Redis repository | `src/core/infrastructure/cache/execution_lock_repository.py` |
| Application service | `src/core/application/services/execution_lock_service.py` |
| API router | `src/core/presentation/api/v1/routers/execution_router.py` |

**Redis key:** `system:execution_lock` (Hash, no TTL)

**Fields:**
- `locked` — `"true"` / `"false"` — runtime emergency stop for orders
- `execution_mode` — `"MANUAL"` / `"AUTOMATIC"` — controls order routing intent
- `changed_at`, `changed_by`, `note` — audit trail

**Rule:** orders are blocked when `locked=true` **OR** `execution_mode=MANUAL`

### Signal Pipeline Independence

Verified signal pipeline does NOT reference broker mode at any layer:

| Service | References broker_config? | References paper broker? |
|---------|--------------------------|--------------------------|
| `SignalScannerService` | NO | NO |
| `SignalEngineService` | NO | NO |
| `RiskEngineService` | NO (uses kill_switch_repo only) | NO |
| `SignalAnalyticsService` | NO | NO |
| `SignalOutcomeTrackerService` | NO | NO |

The signal pipeline was already clean. No functional change needed in scanner/engine/risk layers.

### PipelineEventHandler — Order Gating

**Before:**
```python
# Gated on static config file value (never updated at runtime)
if self._signal_config and self._signal_config.is_manual_mode:
    return  # skip orders
```

**After:**
```python
# Gated on live Redis state (runtime-changeable via API)
if self._execution_lock and await self._execution_lock.is_order_execution_blocked():
    return  # skip orders — signals already stored
```

### app.py Startup

**Before:** Kill switch auto-deactivation was conditional on `broker_cfg.trading_mode == "paper"`.

```python
# Old — paper mode dependency
if broker_cfg.trading_mode.lower() == "paper":
    await kill_switch_service.deactivate(...)
```

**After:** Kill switch always deactivated at startup. Execution lock seeded from signal.yaml default.

```python
# New — always deactivate kill switch (emergency-only instrument)
await kill_switch_service.deactivate(...)

# Seed execution lock (only if Redis key absent — preserves operator settings)
await execution_lock_svc.seed_on_startup(default_mode=signal_config_obj.execution_mode)
```

### broker_config.py

**Before:** `trading_mode` described `"paper"` vs `"live"` with paper meaning simulated orders.

**After:** `trading_mode` describes which broker API to connect to (`"live"` = Kite, `"angel"` = Angel One). Whether orders are placed is controlled entirely by ExecutionLockService. Default changed from `"paper"` to `"live"`.

Removed: `is_paper_mode` property.

### signal_analytics_service.py

**Before:** `execution_mode` was a static string from config injected at construction.

**After:** Queries `ExecutionLockService.get_state()` at record time — captures the actual mode active when the signal was generated.

---

## Paper Broker Status

| Component | Status | Used In Signal Flow? |
|-----------|--------|----------------------|
| `PaperBrokerAdapter` | RETAINED — available for simulation use | NO |
| `PaperOrderRouter` | RETAINED | NO |
| `PaperTradingDaemon` | RETAINED — paper trading reports | NO |
| `paper_trading_validation_service` | RETAINED | NO |

**Decision:** Paper broker components were NOT removed. They are:
1. Not in the signal pipeline (confirmed by audit)
2. Still useful for simulation and paper trading reports
3. Safe to leave in place — they are wired at container level only

The signal flow never instantiates or calls any paper broker component.

---

## API Endpoints

### New: Execution Control

```
GET  /api/v1/execution/status   — current lock state + execution mode
POST /api/v1/execution/lock     — lock order execution (admin)
POST /api/v1/execution/unlock   — unlock order execution (admin)
POST /api/v1/execution/mode     — change execution mode MANUAL ↔ AUTOMATIC (admin)
```

### Removed

```
GET  /api/v1/intelligence/execution-mode  — read static signal config (superseded)
```

---

## Frontend Changes

| File | Change |
|------|--------|
| `top-nav.tsx` | Replaced PAPER/LIVE badge with LIVE DATA (always green) + Execution Mode badge |
| `trading-mode-badge.tsx` | Now exports `ExecutionModeBadge` (MANUAL/AUTOMATIC) and `LiveDataBadge` |
| `kill-switch-button.tsx` | Rewritten as `ExecutionLockButton` — shows LOCKED/UNLOCKED state, lock/unlock on click |
| `broker-view.tsx` | Paper mode section replaced with Execution Mode + Execution Lock panels |
| `execution.service.ts` | New service for `/api/v1/execution/*` endpoints |
| `types/index.ts` | Added `ExecutionMode`, `ExecutionLockState` types |

---

## Validation Evidence

### MANUAL Mode (default)

```
Signal Pipeline:
  market data → scanner → strategy → confidence → risk → signal → persist → broadcast
                                                                    ↓
                                                             signal_analytics.record()
                                                                    ↓
                                                          PipelineEventHandler:
                                                          execution_lock.is_order_blocked() = TRUE
                                                                    ↓
                                                             RETURN (no order)

Result:
  ✅ Signal generated
  ✅ Signal stored in DB
  ✅ Signal broadcast via WebSocket
  ✅ Signal visible in dashboard
  ✅ Signal recorded in signal_analytics
  ❌ No order sent to broker
  ❌ No position opened
```

### AUTOMATIC + UNLOCKED

```
Signal Pipeline:
  market data → scanner → strategy → confidence → risk → signal → persist → broadcast
                                                                    ↓
                                                          PipelineEventHandler:
                                                          execution_lock.is_order_blocked() = FALSE
                                                                    ↓
                                                             OMS.process_signal_risk_approved()
                                                                    ↓
                                                             OrderRouterService.route()
                                                                    ↓
                                                             KiteBroker.place_order()
                                                                    ↓
                                                             Position opened

Result:
  ✅ Signal generated
  ✅ Signal stored in DB
  ✅ Signal broadcast via WebSocket
  ✅ Order placed with Kite
  ✅ Position opened
```

### LOCKED (regardless of mode)

```
  execution_lock.is_order_blocked() → locked=true → TRUE
  → PipelineEventHandler returns early
  → Signals, analytics, and dashboard unaffected
  → No orders
```

---

## Success Criteria Verification

| Criteria | Status |
|----------|--------|
| Signal generation never depends on execution mode | ✅ Scanner/engine/risk never check execution_mode |
| Signals visible in MANUAL mode | ✅ Pipeline always runs; only order routing is gated |
| Signals stored in DB in MANUAL mode | ✅ SignalPersistenceService runs before PipelineEventHandler |
| Signals broadcast via WebSocket | ✅ Event bus publishes before order gating |
| No orders in MANUAL mode | ✅ PipelineEventHandler returns before OMS call |
| AUTOMATIC mode sends orders | ✅ PipelineEventHandler proceeds to OMS when unlocked + AUTOMATIC |
| Execution mode changeable at runtime | ✅ POST /api/v1/execution/mode writes to Redis |
| Audit trail on mode changes | ✅ `changed_at`, `changed_by`, `note` stored in Redis Hash |
| Dashboard shows LIVE DATA | ✅ LiveDataBadge always shown in top-nav |
| Dashboard shows execution mode | ✅ ExecutionModeBadge in top-nav |
| Warning on AUTOMATIC | ✅ Orange banner in broker-view when AUTOMATIC + UNLOCKED |
| Live market data always | ✅ Market data pipeline independent of all execution settings |
