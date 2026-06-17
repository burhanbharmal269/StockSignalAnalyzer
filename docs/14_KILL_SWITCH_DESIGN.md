# 14 — Kill Switch Design

## Purpose

Define the architecture, trigger conditions, behavioral contract, recovery procedure, and audit requirements for the platform's emergency stop mechanism. The Kill Switch is the most operationally critical safety component in the system. It must be simple, fast, reliable, and impossible to bypass — including by bugs, process crashes, or race conditions.

---

## Design Principles

- The kill switch state is persisted in Redis AND in the database. A process restart does not reset it.
- The kill switch is checked synchronously before every order submission. There is no code path to the broker that does not pass through this check.
- Activation is idempotent. Triggering it multiple times has no additional effect.
- Deactivation is manual-only. There is no automatic reactivation under any condition.
- The kill switch operates on event bus messages. It does not depend on the OMS, risk engine, or any other component being healthy to activate.
- Simple is safe. The kill switch implementation must have no external dependencies beyond Redis and the database.

---

## State Model

### Kill Switch State

```
KillSwitchState:
    is_active:           bool
    activated_at:        datetime | None   (UTC)
    activated_by:        str | None        ('operator', 'risk_engine', 'dead_mans_switch', 'system')
    activation_reason:   str | None
    deactivated_at:      datetime | None   (UTC)
    deactivated_by:      str | None        (user_id of the operator who deactivated)
    deactivation_note:   str | None        (mandatory explanation)
```

### Redis Key

```
Key:   system:kill_switch
Type:  Redis Hash
TTL:   None (persists indefinitely until manually cleared)
```

The Redis hash stores all fields of `KillSwitchState`. On process restart, the application reads this key before initializing any trading components. If `is_active = true`, all trading components initialize in blocked state.

### Database Audit Table

Every activation and deactivation is written to `kill_switch_events`. This table is append-only.

```
kill_switch_events
─────────────────────────────────────────────────────────
id                  BIGSERIAL        PRIMARY KEY
event_type          VARCHAR(20)      NOT NULL  (ACTIVATED, DEACTIVATED)
triggered_by        VARCHAR(50)      NOT NULL
trigger_source      VARCHAR(30)      NOT NULL  (MANUAL, RISK_ENGINE, DEAD_MANS_SWITCH, SYSTEM)
reason              TEXT             NOT NULL
metadata            JSONB                      (signal_id, loss_amount, position snapshot at activation)
created_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW()
user_id             INTEGER                    FK → users (for manual actions)
```

The application DB user has INSERT permission only on this table. No UPDATE or DELETE is permitted.

---

## Trigger Conditions

### Manual Triggers

| Source | Mechanism | Auth Required |
|---|---|---|
| Dashboard UI | "Emergency Stop" button with confirmation modal | Admin role |
| REST API | `POST /api/v1/system/kill-switch/activate` | Admin JWT + IP allowlist |
| CLI | `python -m app.cli kill-switch activate --reason "..."` | Admin credentials |

Manual activation requires a mandatory `reason` string (minimum 10 characters).

### Automatic Triggers

| Condition | Threshold | Source |
|---|---|---|
| Daily loss limit reached | `risk.daily_loss_limit` consumed 100% | RiskEngine |
| Weekly loss limit reached | `risk.weekly_loss_limit` consumed 100% | RiskEngine |
| Maximum drawdown reached | `risk.max_drawdown_pct` from rolling 30-day high-water mark | RiskEngine |
| Net portfolio delta breach | Net delta > `risk.max_net_delta` | RiskEngine |
| Dead Man's Switch timeout | Heartbeat missing > 2 minutes during market hours | DeadMansSwitch |
| Broker disconnect (prolonged) | Broker WS disconnected > 5 minutes during market hours | WebSocketManager |
| Rapid loss sequence | 3 consecutive losses > 1% each within 10 minutes | RiskEngine |
| Order rejection storm | > 5 order rejections within 60 seconds | OMS |

Each automatic trigger produces a `risk.limit.breached` event on the event bus, which the `KillSwitchService` consumes.

---

## Activation Sequence

The activation sequence is designed to be fast and atomic. The critical path (Steps 1–3) must complete in under 200ms.

```
Step 1: Atomic Redis write
    HSET system:kill_switch is_active true activated_at <timestamp> ...
    This is the authoritative state change.
    All components reading this key will see it within one polling interval.

Step 2: Publish event (non-blocking)
    Publish system.kill_switch.activated to event bus (Redis Streams).
    Consumers act asynchronously.

Step 3: Direct OMS block (synchronous, in-process)
    If OMS is in the same process: set OMS.blocked = True immediately.
    OMS checks this flag synchronously before every order submission.
    This is an in-memory flag set — zero latency.

Step 4: Cancel all open orders (async, best-effort, 15-second timeout)
    Call broker.cancel_all_orders() for each active broker session.
    Retry up to 3 times with 3-second intervals.
    If cancellation fails: log CRITICAL, alert operator.
    Do not re-activate. Positions remain open — operator manages manually.

Step 5: Database write (async, non-blocking)
    Insert into kill_switch_events.

Step 6: Alert
    Send notification to Telegram + email with:
    - Activation reason and source
    - Current P&L snapshot
    - List of open positions at activation time
    - List of orders that were cancelled / failed to cancel
```

**Order of operations is critical:** the Redis write (Step 1) must happen before everything else. If the process crashes after Step 1 but before Step 4, the platform restarts in blocked state (startup reads the Redis key).

---

## OMS Integration

The OMS checks the kill switch synchronously before every **new order submission**:

```
Before calling broker.place_order():
    if oms.kill_switch_flag:  # in-memory flag
        raise KillSwitchActiveError(reason=state.activation_reason)
        log: order blocked by kill switch
        publish order.rejected with reason=KILL_SWITCH
        return
```

This check is an in-memory flag read (set at startup from Redis, updated asynchronously on event). It adds zero measurable latency to the order path.

**Redis connectivity loss during trading:** the last known state is used, defaulting to blocked if state is unknown. Unknown state is always safe — block first, investigate later.

### Cancellation Bypass Rule (Critical Safety Invariant)

**`broker.cancel_order()` and `broker.cancel_all_orders()` MUST bypass the kill switch gate.**

The kill switch activation sequence (Step 4) calls `cancel_all_orders()`. If cancellations were routed through the standard OMS kill switch check, they would be blocked by the same flag they are trying to execute under — a deadlock.

Implementation contract:
```
OMS exposes two internal paths:
  submit_order(order)   → passes through kill_switch_flag check (blocked when active)
  cancel_order(order)   → bypasses kill_switch_flag check (always permitted)
  cancel_all_orders()   → bypasses kill_switch_flag check (always permitted)
```

Cancellation calls log `kill_switch_bypass=True` in the order event for audit trail.
Cancellation calls are **never** subject to order rate limiting when kill switch is active.

### Kill Switch Active + Heartbeat Interaction

When the kill switch is active, `HeartbeatService` must continue publishing heartbeats.  
`DeadMansSwitch` must NOT re-fire when kill switch is already active — it gates its watchdog on `kill_switch.is_active == False`. This prevents alert storms from a second DMS trigger while the operator is managing the situation.

---

## Dead Man's Switch

The Dead Man's Switch is a watchdog that ensures the system is actively running. It prevents the scenario where the process appears alive but has silently stopped processing (deadlock, CPU spin, event loop starvation, or silent exception swallowing).

### Heartbeat

The `HeartbeatService` publishes a `system.heartbeat` event every 30 seconds containing:
```json
{
  "timestamp":         "<UTC now>",
  "signals_processed": 14,
  "ticks_processed":   4820,
  "active_positions":  3,
  "oms_queue_depth":   0
}
```

### Watchdog

The `DeadMansSwitch` service consumes `system.heartbeat` events. It runs as an independent async task that does not depend on the main signal pipeline.

**Trigger condition:** no heartbeat received within 120 seconds during market hours:
1. Activate the kill switch with `trigger_source = DEAD_MANS_SWITCH`.
2. Send CRITICAL alert.

### Market Hours Gate

The Dead Man's Switch is active only during market hours (09:00–15:35 IST on trading days). Missing heartbeats outside market hours are logged but do not trigger the kill switch.

---

## Recovery Procedure

Deactivation is strictly manual. There is no automatic reactivation.

### Deactivation Steps (Operator)

1. Investigate the activation reason from `kill_switch_events` table and alert logs.
2. Confirm the underlying condition is resolved (e.g., loss limits not breached, broker connected).
3. Review all positions that were open at activation time and their current broker status.
4. If open positions require intervention: close them manually via broker terminal before reactivating.
5. Call `POST /api/v1/system/kill-switch/deactivate` with a mandatory `note` field explaining why it is safe to resume.

The API performs these checks before deactivating:
- Verifies admin role + IP allowlist.
- Verifies the triggering condition is no longer active OR the operator explicitly acknowledges it (see same-day deactivation rule below).
- Sets Redis `is_active = false`.
- Inserts DEACTIVATED record into `kill_switch_events`.
- Publishes `system.kill_switch.deactivated` event.
- Sends confirmation alert including operator's note.

### Same-Day Deactivation After Daily Loss Trigger

If the kill switch fired because the **daily loss limit** was reached at, say, 14:00 IST, the daily loss cannot decrease on the same trading day. The standard "verify loss < limit" check would permanently block deactivation until midnight. This is the correct default behavior — do not resume trading after a full-day loss.

However, operators may have a legitimate reason to resume (e.g., a fat-finger loss that was reversed, a broker settlement correction). The deactivation API supports an explicit override:

```
POST /api/v1/system/kill-switch/deactivate
Body:
  note: str (mandatory, minimum 20 characters)
  override_loss_check: bool (default false)
  override_reason: str (required when override_loss_check = true)
```

When `override_loss_check = true`:
- The loss limit check is skipped.
- The override reason is persisted in `kill_switch_events.metadata`.
- A CRITICAL-severity alert is sent regardless of outcome.
- The deactivation is flagged in the audit log as `MANUAL_OVERRIDE`.
- Platform resumes in **PAPER mode only** for the remainder of the trading day — it cannot resume LIVE trading on the same day a loss override was used.

### Post-Recovery Validation

Before the platform processes new signals after deactivation:
1. Run position reconciliation against the broker.
2. Recompute current daily/weekly P&L.
3. Verify loss limits are not already breached.
4. If any check fails: re-activate the kill switch automatically.

**All signals queued since activation are discarded** — they are not replayed. The market has moved; stale signals are dangerous.

---

## Testing Requirements

- Unit tests: verify activation sets Redis flag; OMS blocks orders after flag is set.
- Integration tests: simulate each automatic trigger and verify kill switch activates within 200ms.
- Chaos test: kill the process after Redis write but before DB write. Verify restart correctly reads kill switch state from Redis and initializes in blocked state.
- Load test: verify kill switch check adds < 1ms to order submission path under 1,000 orders/second.
- Manual test before every live trading session: activate and deactivate via dashboard; verify alerts received; verify OMS blocks and unblocks correctly.

---

## Observability

| Metric | Type | Description |
|---|---|---|
| `kill_switch_active` | Gauge | 1 if active, 0 otherwise |
| `kill_switch_activations_total` | Counter | Labelled by `trigger_source` |
| `kill_switch_activation_duration_seconds` | Histogram | Time from trigger to Redis write |
| `kill_switch_cancel_orders_duration_seconds` | Histogram | Time to cancel all open orders |
| `kill_switch_cancel_orders_failed_total` | Counter | Orders that failed to cancel |
| `dead_mans_switch_last_heartbeat_age_seconds` | Gauge | Seconds since last heartbeat |

**Alert rule:** `kill_switch_active == 1` triggers immediate Telegram + email notification. This alert must never be silenced or suppressed.
