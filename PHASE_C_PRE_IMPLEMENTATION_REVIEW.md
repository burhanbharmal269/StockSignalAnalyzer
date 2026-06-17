# Phase C Pre-Implementation Review

**Date:** 2026-06-14  
**Scope:** Targeted review — schema completeness, repository boundaries, migration reversibility, Redis schema safety, auditability  
**Source documents:** PHASE_13_IMPLEMENTATION_PLAN.md · PHASE_13_FINAL_READINESS_REVIEW.md · PHASE_B_REMEDIATION_AUDIT.md · AD-P13-01.md · Phase C Pre-Implementation Plan  
**Constraint:** Architecture is locked. This review does not propose architectural changes. All findings are scoped to Phase C implementation decisions.

---

## Executive Summary

| Finding | Area | Classification |
|---------|------|----------------|
| F1 — Missing GRANT statements in upgrade() | Migration | SHOULD_FIX_NOW |
| F2 — Malformed `is_active` value causes FAIL_OPEN | Redis Safety | SHOULD_FIX_NOW |
| F3 — Hash present, `is_active` field absent, treated as inactive | Redis Safety | SHOULD_FIX_NOW |
| F4 — Malformed datetime field raises unhandled ValueError | Redis Safety | SHOULD_FIX_NOW |
| F5 — Timeout policy inside repository violates boundary constraint | Repository Boundary | SHOULD_FIX_NOW |
| F6 — Missing `portfolio_snapshot` JSONB in `risk_decisions` | Schema Completeness | SHOULD_FIX_NOW |
| F7 — No `config_hash` in `risk_decisions` | Auditability | CAN_DEFER |
| F8 — No `evaluated_latency_ms` in `risk_decisions` | Observability | CAN_DEFER |

**BLOCKER count: 0**

**Verdict: READY_FOR_PHASE_C_IMPLEMENTATION**

SHOULD_FIX_NOW items must be incorporated into Phase C before coding begins. They are required amendments to the Phase C plan — not blockers that prevent Phase C from starting.

---

## Section 1 — Schema Completeness

### F6 — Missing `portfolio_snapshot` JSONB in `risk_decisions`

**Classification: SHOULD_FIX_NOW**

**Finding:**

The `risk_decisions` table stores `account_snapshot` (the `AccountState` at evaluation time) but does not store a corresponding `portfolio_snapshot` (the `PortfolioState`).

Six of the 15 pre-trade checks depend on `PortfolioState` as their primary input:

| Check | PortfolioState fields consumed |
|-------|-------------------------------|
| Check 5 — OpenPositions | `open_positions_count` |
| Check 6 — SymbolConcentration | `positions_per_underlying` |
| Check 7 — CapitalConcentration | `capital_per_underlying_pct` |
| Check 8 — NetDelta | `net_delta` |
| Check 9 — Correlation | `net_delta` |
| Check 13 — OrderRate | `orders_last_minute`, `orders_today` |
| Check 15 — VegaExposure | `net_vega` |

The `checks` JSONB stores the output `current_value` for each check. This captures the result but not the raw portfolio inputs. For Check 8 (NetDelta), you can see `current_value` = the measured exposure, but you cannot determine what `portfolio.net_delta` was before the trade was added.

**12-month audit gap:**

An auditor questioning whether Check 8 (NetDelta) applied the correct portfolio baseline cannot reconstruct `portfolio.net_delta` from `risk_decisions` alone. The signals table does not store portfolio state. The positions table retains current state, not point-in-time snapshots from 12 months ago.

**Why expensive to add after Phase C:**

Adding `portfolio_snapshot` after Phase C requires:
1. New Alembic migration (`005_add_portfolio_snapshot`)
2. `RiskDecisionModel` ORM update
3. `RiskDecision` frozen dataclass — new field `portfolio_snapshot: PortfolioState`
4. `SqlAlchemyRiskDecisionRepository.insert()` — serialize and store
5. All `RiskDecision` construction sites updated (Phase D: ~7 construction paths in `RiskEngineService`)
6. All `_make_approved()` / `_make_rejected()` test factories updated

Adding it now costs exactly items 1, 2, and 4 (the domain object and test factories are Phase D scope). The column can be nullable: `portfolio_snapshot JSONB` — and populated in Phase D when `RiskDecision` gains the field.

**Required change:**

Add `portfolio_snapshot JSONB` (nullable) to `risk_decisions` in migration `004_phase13`. Store nothing for now (Phase D populates it). This reserves the column at zero implementation cost in Phase C while avoiding a post-Phase D schema migration.

The `PortfolioState` serialization contract for `portfolio_snapshot`:
- `open_positions_count: int`
- `positions_per_underlying: dict[str, int]`
- `capital_per_underlying_pct: dict[str, float]`
- `net_delta: float`
- `net_vega: float`
- `net_theta_daily: float`
- `orders_last_minute: int`
- `orders_today: int`
- `captured_at: str` (ISO 8601)

---

### F7 — No `config_hash` in `risk_decisions`

**Classification: CAN_DEFER**

**Finding:**

There is no configuration fingerprint stored with each `risk_decisions` record. The auditor cannot directly determine what risk limits were configured at the time of evaluation.

**Partial mitigation (accepted):**

The `checks` JSONB stores `limit_value` for every check that ran. For any fully-evaluated decision (all 15 checks completed), the effective limits are derivable from the 15 `limit_value` fields. For decisions rejected at Check 1 (kill switch), only the kill switch state is captured — not the limits for unrun checks.

**Why deferred:**

- Adding `config_hash` requires the domain `RiskDecision` object to carry the hash, or requires the repository to compute it from an injected config singleton. Both require cross-cutting changes.
- The `limit_value` fields in the JSONB provide 95%+ of the audit coverage needed.
- Git history of `config/risk.yaml` provides the full change timeline and is authoritative.

**Future path:** Add `risk_yaml_version: VARCHAR(10) DEFAULT '2.0'` as a cheap placeholder now if config-version traceability is valued. This requires no domain object change — the repository populates it from the injected config. Decision deferred to Phase D.

---

### F8 — No `evaluated_latency_ms` in `risk_decisions`

**Classification: CAN_DEFER**

**Finding:**

The `evaluated_at` column marks evaluation time but there is no end-time or duration column. DB-level P99 latency analysis for the `risk_decisions` INSERT SLO (< 50ms) is not possible beyond Prometheus retention (~15 days).

**Why deferred:**

Prometheus with a 90-day retention policy covers the operational monitoring window. Historical latency for audit purposes is not a regulatory requirement. If Prometheus retention is extended, the gap is addressed without schema change.

If latency tracking is needed: add `evaluation_duration_ms INTEGER` (nullable) to the migration now. The repository computes `(db_return_time - evaluated_at) × 1000`. This is low cost to add now and cannot be backfilled.

---

## Section 2 — Repository Boundaries

### F5 — Timeout Policy Inside Repository Violates Boundary Constraint

**Classification: SHOULD_FIX_NOW**

**Finding:**

The Phase C Pre-Implementation Plan (§4.1) states:

> "The repository takes `timeout_seconds` as a parameter and enforces it internally via `asyncio.wait_for(self._do_insert(session, row), timeout=timeout_seconds)`."

The user's Phase C constraint explicitly states:

> "Ensure repositories do NOT contain: timeout policies"

These are directly contradictory. The `asyncio.wait_for` call inside `SqlAlchemyRiskDecisionRepository.insert()` IS a timeout policy. The 100ms timeout is a business rule sourced from `config.db.risk_decisions_insert_timeout_ms` — it does not belong in the infrastructure layer.

**Correct design:**

Timeout ownership belongs in **Option B: the caller (Phase D RiskEngineService)**.

```python
# Phase D — RiskEngineService.evaluate() (correct pattern)
timeout_s = self._config.db.risk_decisions_insert_timeout_ms / 1000.0
decision_id = await asyncio.wait_for(
    self._risk_decision_repository.insert(decision, timeout_s),
    timeout=timeout_s,
)
```

The repository implementation does NOT call `asyncio.wait_for` internally. It performs the INSERT directly. `timeout_seconds` is accepted by the repository's interface signature (for contractual documentation and testing) but is not enforced by the repository.

**Impact on Phase C tests:**

Tests `test_insert_timeout_raises_asyncio_timeout_error` and `test_insert_timeout_parameter_is_respected` (items #25–26 in the Phase C plan test matrix) must test that `asyncio.TimeoutError` propagates through the repository correctly when raised by an external `asyncio.wait_for`, not by internal wrapping. The test pattern becomes:

```python
async def test_insert_timeout_propagates():
    # Slow mock session — the TEST wraps externally
    async def slow_insert(*_): await asyncio.sleep(1.0)
    session_factory = mock_session(commit=slow_insert)
    repo = SqlAlchemyRiskDecisionRepository(session_factory)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(repo.insert(decision, 0.01), timeout=0.01)
```

**Interface docstring note (informational — not a required change):**

`IRiskDecisionRepository` docstring says "The caller wraps insert() with asyncio.wait_for(timeout=...)". This is consistent with the corrected design. The Phase C plan §4.1 that said "repository enforces internally" was incorrect and is superseded by this finding.

---

### Repository Boundary: Other Checks

**`SqlAlchemyRiskDecisionRepository`:** No business logic concern. Serialization of domain objects to JSONB is a legitimate infrastructure responsibility. The `_to_dict()` serialization helper (converting Decimal, datetime, UUID, Enum) is pure data mapping. ✓

**`SqlAlchemyKillSwitchEventsRepository`:** Pure INSERT with no logic. ✓

**`RedisKillSwitchRepository`:**
- `get_state()`: HGETALL → parse to domain object. Pure data mapping. ✓
- `activate()`: Clears deactivation fields when activating (sets `deactivated_at=""`, etc.). This is Redis Hash field management, not business logic. The repository knows the structure of `system:kill_switch` and is responsible for maintaining its consistency. ✓
- `deactivate()`: Symmetric pattern. ✓
- No retry policies in any method. ✓

---

## Section 3 — Migration Reversibility

### F1 — Missing GRANT Statements in `upgrade()`

**Classification: SHOULD_FIX_NOW**

**Finding:**

The upgrade() REVOKEs UPDATE and DELETE from `app_user` on both tables but never GRANTs SELECT or INSERT.

```sql
-- Current plan (incomplete)
REVOKE UPDATE, DELETE ON risk_decisions FROM app_user;
REVOKE UPDATE, DELETE ON kill_switch_events FROM app_user;
```

In PostgreSQL, when a table is created by the `migration_user` role (the role that runs Alembic), `app_user` does not automatically receive any permissions unless:
- `ALTER DEFAULT PRIVILEGES` has been configured to grant INSERT/SELECT to `app_user` on new tables, OR
- `app_user` and `migration_user` are the same role (table owner).

If neither condition holds, the application will receive `permission denied for table risk_decisions` on the first INSERT. This failure would occur at runtime, not at migration time, making it a hard-to-diagnose production incident.

**Required change — add to upgrade() before the REVOKE statements:**

```sql
GRANT SELECT, INSERT ON risk_decisions TO app_user;
GRANT USAGE, SELECT ON SEQUENCE risk_decisions_id_seq TO app_user;
GRANT SELECT, INSERT ON kill_switch_events TO app_user;
GRANT USAGE, SELECT ON SEQUENCE kill_switch_events_id_seq TO app_user;
REVOKE UPDATE, DELETE ON risk_decisions FROM app_user;
REVOKE UPDATE, DELETE ON kill_switch_events FROM app_user;
```

The SEQUENCE grants are required for BIGSERIAL autoincrement — without `USAGE` on the sequence, the INSERT fails on the `nextval()` call.

**Downgrade impact:**

`downgrade()` drops both tables via `DROP TABLE IF EXISTS`, which cascades to drop any grants on those tables. The grants are automatically removed. No `REVOKE` needed in downgrade. ✓

**Note:** If the production deployment uses a single `app_user` that also runs migrations (owner = app_user), these GRANTs are redundant but harmless.

---

### Hypertable Reversibility

**No issue, but documented for clarity:**

`DROP TABLE IF EXISTS risk_decisions` in downgrade() correctly drops a TimescaleDB hypertable and all its chunks. TimescaleDB overrides `DROP TABLE` to include chunk cleanup. The downgrade is clean. ✓

However: downgrade destroys all `risk_decisions` data permanently. This is expected migration behavior and is acceptable. The docstring in the migration file should state this explicitly.

**TimescaleDB extension guard (R1 from Phase C plan — confirmed required):**

The `create_hypertable` call must be guarded. If TimescaleDB is absent, the migration must not fail — it should proceed with a standard table (no hypertable). Recommended implementation:

```python
# In upgrade(), after creating tables and indexes:
op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'
        ) THEN
            PERFORM create_hypertable(
                'risk_decisions',
                'evaluated_at',
                chunk_time_interval => INTERVAL '1 day',
                if_not_exists => TRUE
            );
        END IF;
    END
    $$;
""")
```

This is already identified in the Phase C plan (R1). Confirmed required.

---

### Other Migration Items

**Index downgrade:** Tables dropped via `DROP TABLE IF EXISTS` cascade to all indexes automatically. No explicit `DROP INDEX` needed in downgrade(). ✓

**`kill_switch_events.user_id FK` to `users`:** The `users` table is created in `002_phase6`. The FK is nullable (`user_id INTEGER REFERENCES users(id)`). Dropping `kill_switch_events` removes the FK constraint automatically. No issue. ✓

**Permission downgrade:** The REVOKE statements from the corrected upgrade() are implicit no-ops in downgrade (the tables are dropped, so the grants and revokes cease to exist). No explicit REVOKE needed in downgrade. ✓

---

## Section 4 — Redis Schema Safety

### F2 — Malformed `is_active` Causes FAIL_OPEN

**Classification: SHOULD_FIX_NOW**

**Finding:**

The Phase C plan specifies `get_state()` parses `is_active` as:

```python
is_active = raw["is_active"] == "true"
```

Any value other than the exact string `"true"` evaluates to `False`. This includes:
- `"True"` (capital T) → `False` — kill switch silently treated as **inactive**
- `"1"`, `"yes"`, `"active"` → `False` — kill switch silently treated as **inactive**
- `"TRUE"` → `False` — kill switch silently treated as **inactive**

This is a **FAIL_OPEN** scenario for the safety-critical kill switch. Redis hashes are plain-text key-value stores. Operator tooling (Redis Insight, redis-cli, monitoring scripts) may write values with incorrect casing. A human operator running `redis-cli HSET system:kill_switch is_active True` (capital T) silently disables the kill switch.

**Required change:**

```python
raw_is_active = raw.get("is_active", "")
if raw_is_active == "true":
    is_active = True
elif raw_is_active == "false":
    is_active = False
else:
    # Unrecognized value — FAIL_CLOSED: unknown state = treat as active
    raise DataSourceUnavailableError(
        source="kill_switch",
        message=f"system:kill_switch.is_active has unrecognized value: {raw_is_active!r}. "
                f"Expected 'true' or 'false'. Treating as FAIL_CLOSED."
    )
```

The caller (`KillSwitchService.get_state()` → `RiskLimitChecker.check_kill_switch()`) already treats `DataSourceUnavailableError` as FAIL_CLOSED. This exception routes correctly.

---

### F3 — Hash Present but `is_active` Field Absent Treated as Inactive

**Classification: SHOULD_FIX_NOW**

**Finding:**

The Phase C plan distinguishes:
- HGETALL returns `{}` (empty dict) → key missing → first startup → `is_active=False` ✓ (correctly treated as inactive per the spec)
- HGETALL returns non-empty dict → key exists

But when the hash exists and `is_active` is absent from the returned dict (e.g., someone ran `HDEL system:kill_switch is_active` while the kill switch was active), the current plan uses `raw.get("is_active", "false")`. The default `"false"` means a hash with a missing `is_active` field silently treats the kill switch as inactive.

This is distinct from F2. F2 is about a wrong VALUE. F3 is about a missing FIELD in a present hash.

**Required change:**

```python
raw = await redis_client.hgetall("system:kill_switch")

if not raw:
    # Key does not exist — first-ever startup, treat as inactive (not an outage)
    return KillSwitchState(is_active=False, ...)

if "is_active" not in raw:
    # Hash exists but is_active field is absent — corrupted hash
    raise DataSourceUnavailableError(
        source="kill_switch",
        message="system:kill_switch hash is present but missing 'is_active' field. "
                "FAIL_CLOSED applied."
    )

# Proceed with normal parsing
```

---

### F4 — Malformed Datetime Field Raises Unhandled ValueError

**Classification: SHOULD_FIX_NOW**

**Finding:**

`get_state()` parses optional datetime fields:

```python
activated_at = datetime.fromisoformat(raw["activated_at"]) if raw.get("activated_at") else None
```

If `raw["activated_at"]` is a non-empty string that is NOT valid ISO 8601 (e.g., `"CORRUPTED"`, `"2026-13-45T99:99:99"`), `datetime.fromisoformat()` raises `ValueError`.

The `IKillSwitchRepository.get_state()` contract declares:
```
Raises:
    DataSourceUnavailableError: On Redis ConnectionError or any read failure.
```

`ValueError` from malformed datetime is a read failure not covered by `ConnectionError`. It bubbles up as an unhandled exception through the evaluation flow. The asyncio.gather() in Phase D uses `return_exceptions=True`, so it becomes a non-exception result that the exception inspection code must handle — but if the inspection code only checks for `DataSourceUnavailableError`, a `ValueError` may pass through without triggering FAIL_CLOSED.

**Required change:**

Wrap all datetime parsing in `get_state()`:

```python
def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise DataSourceUnavailableError(
            source="kill_switch",
            message=f"system:kill_switch contains malformed datetime: {value!r}"
        ) from exc
```

Apply `_parse_datetime()` to `activated_at` and `deactivated_at`. This converts any hash corruption into a `DataSourceUnavailableError`, which routes correctly to FAIL_CLOSED.

---

### Redis Safety: Additional Validation Recommendations

The three findings above (F2, F3, F4) are all validated in `get_state()`. Implementing all three converts `get_state()` from a trusting parser to a defensive reader that fails explicitly on corruption.

**Summary of required `get_state()` validation behavior:**

| Hash condition | Current behavior | Required behavior |
|----------------|-----------------|------------------|
| Key absent (empty HGETALL) | Returns inactive default | Returns inactive default ✓ (no change) |
| `is_active = "true"` | Returns `is_active=True` | Same ✓ |
| `is_active = "false"` | Returns `is_active=False` | Same ✓ |
| `is_active = "True"` (capital T) | Returns `is_active=False` ← FAIL_OPEN | Raises `DataSourceUnavailableError` |
| `is_active` field absent (hash present) | Returns `is_active=False` ← FAIL_OPEN | Raises `DataSourceUnavailableError` |
| `activated_at = "CORRUPTED"` | Raises `ValueError` (unhandled) | Raises `DataSourceUnavailableError` |
| `ConnectionError` | Raises `DataSourceUnavailableError` | Same ✓ |

---

## Section 5 — Auditability Review

**Scenario: A risk decision is questioned 12 months later.**

### What decision was made

`approved: boolean` ✓  
`rejection_code: VARCHAR(50)` ✓  
`rejection_reason: TEXT` ✓

**Verdict: Covered.**

### Why it was made

`checks: JSONB` — stores `check_name`, `passed`, `current_value`, `limit_value`, `message`, `is_warning` for all checks that ran ✓  
`failed_data_sources: JSONB` — stores which infrastructure sources failed ✓  
`rejection_code` — machine-readable rejection cause ✓

**Verdict: Covered for all executed checks.**

### Which configuration produced it

`checks` JSONB stores `limit_value` per check for all executed checks ✓ (partial)

**Gap:** For decisions rejected at Check 1 (kill switch), the only executed check is the kill switch check (`limit_value = null`). Limits for checks 2–15 are not captured. This is the 5% gap not covered by F6 deferral of config_hash.

**Verdict: Substantially covered. Gap acknowledged and deferred (F7).**

### Which checks passed / which failed

`checks` JSONB — check-by-check pass/fail for all executed checks ✓  
`is_hard_failure` property exists on `RiskCheckResult` to distinguish hard failures from ThetaDecay warnings ✓

**Verdict: Covered for executed checks. Checks that never ran (fast-exit on rejection) are absent — this is expected behavior.**

### Historical reproducibility

**Gap: No `portfolio_snapshot` (F6 — SHOULD_FIX_NOW)**

`account_snapshot: JSONB` stores `AccountState` at evaluation time ✓  
No `portfolio_snapshot` for `PortfolioState` ✗

To reproduce a Check 8 (NetDelta) decision from 12 months ago, the auditor needs `portfolio.net_delta` at evaluation time. The `checks` JSONB shows `current_value` (the post-addition effective delta) but not the pre-trade `portfolio.net_delta`. These differ by `new_delta_signed` — which requires knowing the position's lot_size and direction from the signal table join.

This is a reproducibility gap. Adding `portfolio_snapshot JSONB` (nullable) to `risk_decisions` now costs one column in the migration. It becomes populated in Phase D at zero additional cost (the `PortfolioState` is already available in the evaluation flow).

---

## Required Changes (SHOULD_FIX_NOW)

The following changes are required amendments to the Phase C plan. They do not change the architecture, interfaces, or domain layer. All changes are within Phase C scope.

### RC-1: Add GRANT statements to migration upgrade()

Add before the REVOKE statements in `upgrade()`:

```sql
GRANT SELECT, INSERT ON risk_decisions TO app_user;
GRANT USAGE, SELECT ON SEQUENCE risk_decisions_id_seq TO app_user;
GRANT SELECT, INSERT ON kill_switch_events TO app_user;
GRANT USAGE, SELECT ON SEQUENCE kill_switch_events_id_seq TO app_user;
```

### RC-2: Add `portfolio_snapshot JSONB` to `risk_decisions`

Add to the `CREATE TABLE risk_decisions` DDL in upgrade():

```sql
portfolio_snapshot  JSONB,
```

Column is nullable. Phase D populates it. Phase C repository stores `None` / null.

Add corresponding `portfolio_snapshot: Mapped[dict | None]` to `RiskDecisionModel`.

### RC-3: Implement strict `is_active` validation in `get_state()`

`RedisKillSwitchRepository.get_state()` must:
1. Reject any `is_active` value that is not exactly `"true"` or `"false"` → raise `DataSourceUnavailableError`
2. If hash is non-empty but `is_active` field is absent → raise `DataSourceUnavailableError`

### RC-4: Wrap datetime parsing in `get_state()`

All `datetime.fromisoformat()` calls in `get_state()` must be wrapped in try/except ValueError → raise `DataSourceUnavailableError`.

### RC-5: Remove internal `asyncio.wait_for` from `SqlAlchemyRiskDecisionRepository`

The repository does NOT call `asyncio.wait_for` internally. The `timeout_seconds` parameter is accepted but not enforced by the repository. Timeout is enforced by Phase D's `RiskEngineService` via external `asyncio.wait_for`.

Update Phase C plan test matrix items #25–26: these tests apply `asyncio.wait_for` externally in the test body, not inside the repository under test.

---

## Recommended Changes (CAN_DEFER)

These do not affect Phase C correctness. Record for Phase D or Phase 16 backlog.

### REC-1: Add `evaluated_latency_ms INTEGER` to `risk_decisions`

Low-cost addition at Phase C. Cannot be backfilled. Populated by Phase D repository with `int((end_time - evaluated_at).total_seconds() * 1000)`.

### REC-2: Add `risk_yaml_version VARCHAR(10) DEFAULT '2.0'` to `risk_decisions`

Populated by Phase D repository from injected `RiskConfig.version`. Zero domain impact. Provides minimal config-version traceability without requiring config hash computation.

---

## Risk Assessment

| Risk | Severity | Mitigated by |
|------|----------|-------------|
| Missing GRANT causes runtime INSERT failure at first deployment | HIGH | RC-1 |
| Corrupted `is_active` silently disables kill switch (FAIL_OPEN) | HIGH | RC-3 |
| Missing hash field treated as inactive (FAIL_OPEN) | HIGH | RC-3 |
| Malformed datetime crashes evaluation flow | MEDIUM | RC-4 |
| Timeout policy in repository creates Phase D architectural confusion | MEDIUM | RC-5 |
| Missing `portfolio_snapshot` requires post-Phase D schema migration | MEDIUM | RC-2 |
| No config fingerprint for early-rejected decisions | LOW | Deferred — checked JSONB partially covers |
| No DB-level latency history beyond Prometheus retention | LOW | Deferred — Prometheus retention is operational choice |

---

## Final Verdict

```
READY_FOR_PHASE_C_IMPLEMENTATION

No BLOCKER findings.

Required before first line of Phase C code:
  RC-1  Add GRANT statements to migration upgrade()
  RC-2  Add portfolio_snapshot JSONB column to risk_decisions DDL
  RC-3  Strict is_active validation — FAIL_CLOSED on unrecognized values
  RC-4  Datetime parsing wrapped in DataSourceUnavailableError conversion
  RC-5  asyncio.wait_for removed from repository; timeout owned by Phase D caller

These are amendments to the Phase C plan, not architecture changes.
All five changes are within Phase C implementation scope.
```

---

*Review completed: 2026-06-14.*  
*Next step: Implement Phase C with all five required changes incorporated.*  
*Phase D dependency noted: `portfolio_snapshot` column populated in Phase D when `RiskDecision.portfolio_snapshot: PortfolioState` is added to the domain object.*
