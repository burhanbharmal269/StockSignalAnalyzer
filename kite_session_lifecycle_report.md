# Kite Session Lifecycle & Daily Authentication — Audit Report

**Date:** 2026-06-16  
**Auditor:** Automated code audit  
**Scope:** Broker session lifecycle, daily expiration handling, safety controls, broker dashboard

---

## Executive Summary

The platform had a **correct but incomplete** Kite session implementation. The core cryptographic and storage layers were sound (AES-256-GCM token encryption, DB persistence, correct 06:00 IST expiry calculation). However, four **critical gaps** existed that could have allowed live trading with an expired session and provided no operator visibility into session state. All gaps have been remediated.

---

## Audit Findings

### GAP-001 — CRITICAL: No startup session validation

**Status:** FIXED  
**File:** `src/app.py`

The `startup_check()` method only validated the kill switch state. It did **not** inspect the stored `broker_sessions` table. A session persisted from the previous day with `is_active=True` would remain in the DB without detection.

**Scenario:** Backend restarted at 08:00 IST (after 06:00 expiry). Stored session shows `is_active=True` but `expires_at` is in the past. No warning. Kill switch stays OFF. If a live order is attempted, it fails silently at `_authenticated_kite()`.

**Fix:** `SessionExpiryWatcher.startup_validate()` is now called at lifespan startup. It fetches the active Kite session, checks `is_expired()`, deactivates the session in DB, and activates the kill switch with reason "Startup validation: Kite access token expired."

---

### GAP-002 — CRITICAL: No background session expiry detection

**Status:** FIXED  
**File:** `src/core/application/services/broker/session_expiry_watcher.py` (new)

No background task watched for the 06:00 IST expiry moment while the platform was running. At 06:00 IST, sessions expire silently. The kill switch was not activated. Live orders placed after 06:00 would reach `_authenticated_kite()` and raise `BrokerSessionExpiredError`, causing OMS to reject them — but no proactive safety action was taken.

**Fix:** `SessionExpiryWatcher.run()` polls every 60 seconds. On detecting an expired live session: deactivates it in DB, activates kill switch, logs `CRITICAL` audit event. Registered as a supervised background task alongside the other safety workers.

---

### GAP-003 — HIGH: `/broker/status` returned no session state

**Status:** FIXED  
**File:** `src/core/presentation/api/v1/routers/broker_router.py`

The `GET /api/v1/broker/status` endpoint returned only `broker_name`, `status`, `kill_switch`, `latency_ms`, `details`, `checked_at`. The frontend had **no way to determine** whether the session was Connected, Expired, or missing — without making a separate `/broker/session` call and checking it client-side.

Additionally, `broker_health_service.check()` was called without a session argument, meaning only the connectivity probe (Kite instruments endpoint) ran. Auth, orders, positions, and margin probes **never ran** from the status endpoint.

**Fix:** The `/status` endpoint now:
- Fetches the active session from DB (fast, no API call)
- Computes `session_status`: `CONNECTED | DISCONNECTED | AUTH_REQUIRED | SESSION_EXPIRED | ERROR`
- Passes session to `broker_health_service.check(session=...)` when live and valid (runs all 5 probes)
- Returns `authenticated_user`, `session_expires_at`, `session_created_at`
- Returns per-capability status: `market_data_status`, `order_placement_status`, `historical_data_status`

---

### GAP-004 — HIGH: No global warning banner for expired session

**Status:** FIXED  
**File:** `frontend/src/components/shared/session-warning-banner.tsx` (new)

When the Kite session expired, no UI feedback was shown outside the `/broker` page. Users on the signals, orders, or dashboard pages had no indication that live trading was disabled.

**Fix:** `SessionWarningBanner` component is mounted in the dashboard layout above `<main>`. It polls `/broker/status` every 30 seconds. When `mode=LIVE` AND `session_status` is `SESSION_EXPIRED` or `AUTH_REQUIRED`, it renders a red banner: *"Kite authentication expired. Live trading disabled until reconnection."* with a direct link to `/broker`.

---

### GAP-005 — HIGH: Authenticated user name not stored or displayed

**Status:** FIXED  
**Files:** `src/core/domain/entities/broker_session.py`, `src/core/infrastructure/database/models/broker_session_models.py`, `src/core/infrastructure/broker/broker_session_manager.py`, migration `20260616_1200`

After login, the platform had no record of which Zerodha user authenticated. The broker dashboard showed no "Authenticated As" field.

**Fix:** `BrokerSessionManager.create_session()` now calls `broker.get_profile(session)` after login and stores `user_name` (Zerodha full name) on the `BrokerSession` entity and in the `broker_sessions.user_name` DB column. Surfaced in `/broker/status` as `authenticated_user` and shown in the broker dashboard.

---

### GAP-006 — MEDIUM: Broker dashboard lacked required capability fields

**Status:** FIXED  
**File:** `frontend/src/features/broker/broker-view.tsx`

The broker page showed only broker name, health status, and latency. It was missing: authenticated user, session creation time, session expiry time, last validation time, market data status, order placement status, historical data status.

**Fix:** The broker card now displays all required fields in a structured grid. Connection status badge uses all 5 states. Capability row shows OK/DEGRADED/UNAVAILABLE per capability in color-coded labels.

---

## Verified Correct (No Changes Required)

| Item | Status | Location |
|---|---|---|
| Token expiry calculation | ✅ Correct | `kite_broker.py:_next_kite_expiry()` → next 06:00 IST |
| Access token encryption | ✅ AES-256-GCM | `token_encryptor.py` |
| `is_expired()` check before use | ✅ Present | `_authenticated_kite()` raises `BrokerSessionExpiredError` |
| `ExecutionGuardService` session check | ✅ Present | `_check_session()` blocks expired/inactive sessions |
| Kill switch blocks all orders | ✅ Present | Guard runs before every order submission |
| Login flow (OAuth URL + callback) | ✅ Correct | `/broker/login` + `/broker/callback` |
| `deactivate_all()` on new login | ✅ Present | Old sessions invalidated before new session created |
| Paper mode exempt from session | ✅ Correct | `PaperBrokerAdapter` needs no session |
| Token never stored plaintext | ✅ Correct | Only `encrypted_access_token` in DB |

---

## Session Lifecycle: Verified Flow

```
User clicks "Connect to Kite"
    → GET /broker/login → returns OAuth URL
    → User completes Zerodha login in popup
    → Zerodha redirects with request_token
    → User pastes request_token in UI
    → POST /broker/callback { request_token }
        → BrokerSessionManager.create_session()
            → deactivate_all("kite")           [invalidate old sessions]
            → KiteBroker.login()
                → kite.generate_session()      [Kite REST: token exchange]
                → AES-256-GCM encrypt token
                → BrokerSession.create(expires_at=next_06:00_IST)
            → get_profile(session)             [store user_name]
            → session_repository.save()
        → 200 OK: session_id, expires_at, user_name

Next day at 06:00 IST:
    → SessionExpiryWatcher._check_expiry()
        → get_active("kite") → session.is_expired() == True
        → session.deactivate() + save()
        → kill_switch_service.activate(reason="Kite access token expired")
        → LOG CRITICAL: session_expiry_watcher.session_expired

Frontend:
    → SessionWarningBanner detects session_status=SESSION_EXPIRED
    → Renders: "Kite authentication expired. Live trading disabled."
    → User clicks "Reconnect Kite" → goes to /broker → repeats flow
```

---

## Daily Expiration Scenario: What Happens Now

| Time | Event | System Response |
|---|---|---|
| Yesterday 14:00 | User authenticates | Session created, expires_at = today 06:00 IST |
| Today 00:00 | App restarted | `startup_validate()` runs: session not yet expired → OK |
| Today 06:01 | Token expires | `SessionExpiryWatcher` detects within 60s, activates kill switch |
| Today 06:01 | Any live order attempt | Kill switch is active → `ExecutionGuardError: kill_switch` |
| Today 06:01 | UI on any page | `SessionWarningBanner` shows red banner |
| Today 06:01 | Broker page | Shows `SESSION_EXPIRED` badge, "Reconnect Kite" button |
| Today 09:00 | User reconnects | Completes OAuth → new session → kill switch deactivated manually |

---

## `kite_connectivity_report.md` Reference

A runtime connectivity report is generated on demand via the enriched `/api/v1/broker/status` endpoint. The `details` field in the response contains:

```json
{
  "connectivity": "ok",
  "connectivity_latency_ms": 234.5,
  "auth": "ok",
  "orders": "ok",
  "positions": "ok",
  "margin": "ok"
}
```

| Probe | Endpoint Used | Pass Condition |
|---|---|---|
| Connectivity | `kite.instruments("NSE")` — no auth required | HTTP 200, latency < timeout |
| Auth | `kite.profile()` | HTTP 200, returns user_id |
| Orders | `kite.orders()` | HTTP 200 |
| Positions | `kite.positions()` | HTTP 200 |
| Margin | `kite.margins()` | HTTP 200 |

Overall status: `HEALTHY` (all pass), `DEGRADED` (connectivity+auth pass, others fail), `DOWN` (connectivity or auth fails).

---

## Files Modified

| File | Change |
|---|---|
| `alembic/versions/20260616_1200_broker_session_user_name.py` | Migration: add `user_name` column |
| `src/core/domain/entities/broker_session.py` | Added `user_name: str = ""` field |
| `src/core/infrastructure/database/models/broker_session_models.py` | Added `user_name` ORM column |
| `src/core/infrastructure/database/repositories/broker_session_repository.py` | Map `user_name` in save/load |
| `src/core/infrastructure/broker/broker_session_manager.py` | Fetch profile on login, store `user_name` |
| `src/core/domain/value_objects/broker_health.py` | Added `authenticated_user: str \| None` |
| `src/core/application/services/broker/broker_health_service.py` | Capture user from profile probe |
| `src/core/application/services/broker/session_expiry_watcher.py` | **New** — startup validate + 60s loop |
| `src/core/presentation/api/v1/schemas/broker.py` | Enriched `BrokerStatusResponse` + `BrokerSessionResponse` |
| `src/core/presentation/api/v1/routers/broker_router.py` | Enriched `/status` endpoint |
| `src/container.py` | Added `session_expiry_watcher` singleton |
| `src/app.py` | Startup validate + register background task |
| `frontend/src/types/index.ts` | Updated `BrokerStatus`, `BrokerSessionInfo` types |
| `frontend/src/components/shared/session-warning-banner.tsx` | **New** — global warning banner |
| `frontend/src/app/(dashboard)/layout.tsx` | Mount `SessionWarningBanner` |
| `frontend/src/features/broker/broker-view.tsx` | Enriched broker dashboard |
