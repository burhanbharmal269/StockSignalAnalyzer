# AD-D-01: KillSwitchService Activation Is Idempotent

**Status:** Accepted
**Date:** 2026-06-14
**Phase:** 13 — Risk Engine (Phase D)
**Applies to:** `src/core/application/services/kill_switch_service.py`

---

## Context

`KillSwitchService.activate()` can be called from multiple paths during normal
operation:

- `PortfolioMonitorService` activates when `daily_loss_consumed_pct >= 100.0`
  or `drawdown_from_hwm_pct >= max_drawdown_pct`.
- `DeadMansSwitchService` activates when Redis, DB, or broker connectivity
  fails for more than the configured threshold of consecutive checks.
- Future phases (OMS, Manual Admin API) may add additional call sites.

In practice these paths can fire simultaneously. A drawdown breach detected at
the end of a portfolio monitor cycle and a Redis failure detected by the dead
man's switch may both call `activate()` within the same second.

## Decision

`KillSwitchService.activate()` is **idempotent**. When called while the kill
switch is already active:

1. **No state mutation** — `redis.hset("system:kill_switch", ...)` is NOT
   called. The existing Redis Hash is not overwritten. The original
   `activated_at`, `triggered_by`, `reason`, and `trigger_source` fields are
   preserved exactly as written by the first activator.

2. **No duplicate audit record** — `kill_switch_events_repository.insert_event()`
   is NOT called. The audit log records the first activation only.

3. **No duplicate event** — `event_bus.publish(KillSwitchActivated(...))` is
   NOT called. Downstream consumers receive exactly one `KillSwitchActivated`
   event per activation epoch.

4. **Fast path** — `activate()` checks current state via
   `kill_switch_repository.get_state()` as its first operation. If
   `state.is_active` is `True`, the method returns immediately without
   performing any of the three above operations.

## Implementation Contract

```python
async def activate(
    self,
    reason: str,
    activated_by: str,
    trigger_source: str,
) -> None:
    current = await self._kill_switch_repo.get_state()
    if current.is_active:
        return  # idempotent — already active

    await self._kill_switch_repo.activate(
        reason=reason,
        activated_by=activated_by,
        trigger_source=trigger_source,
    )
    await self._kill_switch_events_repo.insert_event(
        event_type="ACTIVATED",
        triggered_by=activated_by,
        trigger_source=trigger_source,
        reason=reason,
        metadata=None,
        user_id=None,
    )
    await self._event_bus.publish("system.kill_switch.activated", KillSwitchActivated(...))
    logger.critical(
        "kill_switch_activated reason=%s by=%s source=%s", reason, activated_by, trigger_source
    )
```

## Activation Order

Per mandatory architecture rule #11, the sequence within `activate()` when
NOT already active is strictly:

```
1. Redis HSET  (system:kill_switch  is_active="true")
2. DB INSERT   (kill_switch_events)
3. Event Publish (system.kill_switch.activated)
```

Event is never published before the audit record is persisted.

If step 2 (DB INSERT) raises `RiskDecisionPersistenceError`, the kill switch
is already active in Redis (step 1 succeeded). Log CRITICAL and return.
Do NOT publish the event if the audit insert failed — the state is still
ACTIVE in Redis so trading is blocked, and the failure is visible in logs.

## Consequences

### Desired properties

- Concurrent activations from `PortfolioMonitorService` and
  `DeadMansSwitchService` are safe. The first writer wins; subsequent calls
  are no-ops with no side effects.
- Audit log is clean: one `ACTIVATED` record per epoch. Deduplication is
  structural, not query-based.
- Event consumers (OMS stub, Phase 15+ order cancellation) receive exactly
  one `KillSwitchActivated` per epoch, regardless of how many services
  trigger it.

### Known limitation

The idempotency check (`get_state()`) involves one Redis round-trip before
every `activate()` call. This is acceptable because `activate()` is an
exceptional event, not a hot path. Under normal operation it is called zero
times per day.

### TOCTOU window

There is a small time window between `get_state()` returning `is_active=False`
and the subsequent `hset()`. Two concurrent `activate()` calls can both pass
the check and proceed to write. This is acceptable because:

- Both writers produce identical Redis state (`is_active="true"`).
- `kill_switch_events` is an append-only table. Two `ACTIVATED` records for
  the same epoch are visible to operators and carry no operational risk.
- `KillSwitchActivated` being published twice is safe for all known consumers.

This is documented as a known trade-off. A Redis SET NX guard could eliminate
it, but would complicate the audit-first contract (step 1 must always precede
step 2). The current design accepts the rare duplicate in exchange for
simplicity and auditability.

## Deactivation Is Also Idempotent

`deactivate()` follows the same pattern: reads current state first; if already
inactive (`is_active=False`), returns immediately without mutation, audit
insert, or event publication.
