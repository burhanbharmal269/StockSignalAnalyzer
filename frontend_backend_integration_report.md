# Frontend ↔ Backend Integration Report

**Date:** 2026-06-16  
**Auditor:** Platform Audit (automated)  
**Scope:** All frontend pages and service calls vs backend API routes

---

## Executive Summary

17 frontend pages audited. 4 integration issues found and fixed. 1 type conflict resolved. All critical paths align after fixes.

---

## Page-by-Page Audit

### Dashboard (`/dashboard`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Broker status | `brokerService.getStatus()` | `GET /api/v1/broker/status` | ✅ |
| Broker mode | `brokerService.getMode()` | `GET /api/v1/broker/mode` | ✅ |
| Health | `healthService.get()` | `GET /api/v1/health` | ✅ |
| Effective account state | `capitalService.getEffectiveAccountState()` | `GET /api/v1/effective-account-state` | ✅ |
| Positions (open) | `usePositions({ state: "OPEN" })` | `GET /api/v1/positions?state=OPEN` | ✅ Fixed |
| Signals (pending) | `useSignals({ state: "PENDING" })` | `GET /api/v1/signals?state=PENDING` | ✅ Fixed |

**Issue fixed:** Dashboard was calling `usePositions({ status: "OPEN" })` and `useSignals({ status: "PENDING" })`. Backend routers use `state` param, not `status`. Fixed to `{ state: "OPEN" }` and `{ state: "PENDING" }`.

---

### Signals (`/signals`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| List signals | `signalService.list(params)` | `GET /api/v1/signals` | ✅ |
| Get signal | `signalService.getById(id)` | `GET /api/v1/signals/{id}` | ✅ |
| Approve signal | `signalService.approve(id)` | `POST /api/v1/signals/{id}/approve` | ✅ |
| Reject signal | `signalService.reject(id, reason)` | `POST /api/v1/signals/{id}/reject` | ✅ |

**TS types:** `Signal`, `SignalListResponse` — aligned with backend `SignalResponse`, `SignalListResponse`.

---

### Orders (`/orders`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| List orders | `orderService.list(params)` | `GET /api/v1/orders` | ✅ |
| Get order | `orderService.getById(id)` | `GET /api/v1/orders/{id}` | ✅ |
| Cancel order | `orderService.cancel(id)` | `POST /api/v1/orders/{id}/cancel` | ✅ |

**Issue fixed:** Backend `list_orders` now accepts `trading_mode` query param (previously ignored).

---

### Positions (`/positions`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| List positions | `positionService.list(params)` | `GET /api/v1/positions` | ✅ |
| Get position | `positionService.getById(id)` | `GET /api/v1/positions/{id}` | ✅ |
| Close position | `positionService.close(id, price)` | `POST /api/v1/positions/{id}/close` | ✅ |

**Issue fixed:** Backend `list_positions` now accepts `trading_mode` and `state` query params.

---

### Broker (`/broker`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Get status | `brokerService.getStatus()` | `GET /api/v1/broker/status` | ✅ |
| Get mode | `brokerService.getMode()` | `GET /api/v1/broker/mode` | ✅ |
| Set mode | `brokerService.setMode(mode, reason)` | `POST /api/v1/broker/mode` | ✅ Added |
| Get session | `brokerService.getSession()` | `GET /api/v1/broker/session` | ✅ |
| Get login URL | `brokerService.getLoginUrl()` | `GET /api/v1/broker/login` | ✅ |
| Submit callback | `brokerService.submitCallback(token)` | `POST /api/v1/broker/callback` | ✅ |
| Activate kill switch | `brokerService.activateKillSwitch(reason)` | `POST /api/v1/broker/kill-switch/activate` | ✅ |
| Deactivate kill switch | `brokerService.deactivateKillSwitch(note)` | `POST /api/v1/broker/kill-switch/deactivate` | ✅ |

---

### Market Overview (`/market-overview`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Get breadth | `marketService.getBreadth()` | `GET /api/v1/market/breadth` | ✅ |
| Get sentiment | `newsService.getMarketSentiment()` | `GET /api/v1/news/sentiment/market` | ✅ |

---

### AI Insights (`/ai-insights`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Get market insight | `aiService.getMarketInsight()` | `GET /api/v1/ai/market` | ✅ |
| Generate insight | `aiService.generateInsight()` | `POST /api/v1/ai/market/generate` | ✅ |
| Get history | `aiService.getInsightHistory()` | `GET /api/v1/ai/market/history` | ✅ |
| Strategy rec | `aiService.getStrategyRecommendation()` | `GET /api/v1/ai/strategy/{symbol}` | ✅ |

---

### Opportunities (`/opportunities`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Get opportunities | `opportunitiesService.getOpportunities()` | `GET /api/v1/opportunities` | ✅ |
| Run scan | `opportunitiesService.runScan()` | `POST /api/v1/opportunities/scan` | ✅ |

---

### Backtest (`/backtest`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Run backtest | `backtestService.runBacktest()` | `POST /api/v1/backtest/run` | ✅ |
| List runs | `backtestService.listRuns()` | `GET /api/v1/backtest/runs` | ✅ |
| Get trades | `backtestService.getTrades(runId)` | `GET /api/v1/backtest/runs/{runId}/trades` | ✅ |

---

### Analytics (`/analytics`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Execution summary | `analyticsService.getExecutionSummary()` | `GET /api/v1/analytics/execution/summary` | ✅ |
| Execution records | `analyticsService.listExecutionRecords()` | `GET /api/v1/analytics/execution/records` | ✅ |
| Paper trading reports | `analyticsService.getPaperTradingReports()` | `GET /api/v1/paper-trading/reports/{type}` | ✅ |

---

### Paper Trading (`/paper-trading`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| List positions (PAPER) | `usePositions({ trading_mode: "PAPER" })` | `GET /api/v1/positions?trading_mode=PAPER` | ✅ Fixed |
| List orders (PAPER) | `useOrders({ trading_mode: "PAPER" })` | `GET /api/v1/orders?trading_mode=PAPER` | ✅ Fixed |

---

### Paper Daemon (`/paper-daemon`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Get status | `paperDaemonService.getStatus()` | `GET /api/v1/paper/status` | ✅ |
| Start | `paperDaemonService.start()` | `POST /api/v1/paper/start` | ✅ |
| Stop | `paperDaemonService.stop()` | `POST /api/v1/paper/stop` | ✅ |
| Get journal | `paperDaemonService.getJournal()` | `GET /api/v1/paper/journal` | ✅ |
| Get performance | `paperDaemonService.getPerformance()` | `GET /api/v1/paper/performance` | ✅ |

---

### Universe (`/universe`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| List symbols | `universeService.list()` | `GET /api/v1/market/universe` | ✅ |

---

### Risk (`/risk`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| List profiles | `riskService.listProfiles()` | `GET /api/v1/risk-profiles` | ✅ |
| Get active | `riskService.getActiveProfile()` | `GET /api/v1/risk-profiles/active` | ✅ |
| Create | `riskService.createProfile()` | `POST /api/v1/risk-profiles` | ✅ |
| Activate | `riskService.activateProfile(id)` | `POST /api/v1/risk-profiles/{id}/activate` | ✅ |

---

### Capital (`/capital`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| List allocations | `capitalService.listAllocations()` | `GET /api/v1/capital-allocations` | ✅ |
| Active allocation | `capitalService.getActiveAllocation()` | `GET /api/v1/capital-allocations/active` | ✅ |
| Effective account state | `capitalService.getEffectiveAccountState()` | `GET /api/v1/effective-account-state` | ✅ |

---

### Settings (`/settings`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Change password | `authService.changePassword()` | `POST /api/v1/auth/change-password` | ✅ |

---

### System Health (`/system-health`)

| API Call | Frontend Service | Backend Route | Status |
|---|---|---|---|
| Health check | `healthService.get()` | `GET /api/v1/health` | ✅ |

---

## TypeScript Type Issues

### CRITICAL — Resolved: `BrokerSessionStatus` name collision

| Issue | File | Fix |
|---|---|---|
| `BrokerSessionStatus` defined as both union type and interface | `frontend/src/types/index.ts` | Renamed interface to `BrokerSessionResponse` |
| `brokerService.getSession()` used wrong type | `frontend/src/services/broker.service.ts` | Updated to `BrokerSessionResponse` |
| `broker-view.tsx` implicit type reference | `frontend/src/features/broker/broker-view.tsx` | Updated query to explicit `<BrokerSessionResponse>` |

---

## Summary of Fixes Applied

| Fix | File(s) | Type |
|---|---|---|
| `BrokerSessionStatus` type conflict resolved | `types/index.ts`, `broker.service.ts`, `broker-view.tsx` | TypeScript |
| `useSignals({ state })` param corrected (was `status`) | `dashboard-view.tsx` | API alignment |
| `usePositions({ state })` param corrected (was `status`) | `dashboard-view.tsx` | API alignment |
| `POST /api/v1/broker/mode` endpoint added | `broker_router.py` | New endpoint |
| `trading_mode` filter added to orders router | `order_router.py` | Backend |
| `trading_mode` + `state` filters added to positions router | `position_router.py` | Backend |
| `brokerService.setMode()` added | `broker.service.ts` | Frontend |

---

## Remaining Notes

- `riskService.listDecisions()` returns a hardcoded empty list (intentional stub, documented in service)
- WebSocket events use `signal.new`/`signal.updated` — backend event bus should emit matching event types
- All auth-protected endpoints require valid JWT; frontend handles 401 by redirecting to login
