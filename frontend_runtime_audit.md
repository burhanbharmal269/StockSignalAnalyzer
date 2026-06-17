# Frontend Runtime Audit — Phase 12

**Date**: 2026-06-16

---

## Bugs Found & Fixed

### F1 — BrokerView TypeError: Cannot read properties of null (reading 'session_id') [FIXED]
- **File**: `frontend/src/features/broker/broker-view.tsx:216`
- **Cause**: `hasActiveSession` comes from `status.session_status` (broker-status query) while `session` comes from `sessionData` (separate query). These load independently — `hasActiveSession=true` while `session=null` is possible during load.
- **Fix**: Changed guard from `{hasActiveSession ? (` to `{hasActiveSession && session ? (`
- **Stack trace**: `TypeError: Cannot read properties of null (reading 'session_id')` in compiled JS at BrokerView:721

---

## Pages — Load & State Audit

### Broker Page (/broker)
- ✅ Loads broker status
- ✅ Shows CONNECTED / AUTH_REQUIRED / SESSION_EXPIRED
- ✅ Kill switch controls (Activate / Deactivate)
- ✅ Trading mode switch (PAPER / LIVE) with confirmation modal
- ✅ Kite OAuth login → redirect → auto-submit token
- ✅ Null guard on session object (fixed)
- ⚠️ Kill switch badge shown when active — user must click "Deactivate Kill Switch" (paper mode now auto-deactivated at startup)

### Signals Page (/signals)
- ✅ Loads signal list
- ✅ Empty state when no signals
- ⚠️ 0 signals shown — expected until pipeline generates signals (now fixed with kill switch + account state)
- ✅ Manual scan trigger via POST /api/v1/signals/scan

### Orders Page (/orders)
- ✅ Loads order list
- ✅ Empty state handled
- ⚠️ No orders without signals

### Positions Page (/positions)
- ✅ Loads position list
- ✅ Empty state handled

### Analytics Page (/analytics)
- ✅ Portfolio P&L chart
- ⚠️ No data without filled orders

### AI Insights Page (/ai-insights)
- ✅ Market analysis on demand
- ✅ Strategy recommendation
- ✅ Handles empty news feed gracefully

### System Health Page (/health)
- ✅ Redis connectivity
- ✅ Database connectivity
- ✅ Broker session status
- ✅ Kill switch state

---

## WebSocket Audit

| Event | Producer | Consumer | Status |
|-------|---------|---------|--------|
| `broker.status` | Broker health check | BrokerView | ✅ |
| `kill_switch.activated` | KillSwitchService | BrokerView | ✅ |
| `kill_switch.deactivated` | KillSwitchService | BrokerView | ✅ |
| `signal.created` | SignalEngineService | SignalsView | ✅ |
| `score.calculated` | ScoringEngineService | Signals overlay | ✅ |

---

## API Error Handling

| Endpoint | Error Case | Frontend Handling |
|---------|-----------|-------------------|
| `POST /broker/callback` | Token expired | Shows `toast.error` with detail message |
| `GET /broker/status` | Redis down | Shows error state in StatusIndicator |
| `GET /broker/session` | No session | `session=null` → auth required UI |
| `POST /signals/scan` | Kill switch active | Returns rejection summary |
| `POST /market/fetch` | Invalid symbol | 422 validation error shown |
