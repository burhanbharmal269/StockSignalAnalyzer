# OPERATIONS HANDBOOK — StockSignalAnalyzer

**Version:** Phase 24 — Operations Mode  
**Frozen since:** 2026-06-27  
**Architecture status:** FROZEN (no strategy changes until 500+ completed trades)

---

## Table of Contents

1. [Architecture Freeze Policy](#1-architecture-freeze-policy)
2. [Deployment Stage Progression](#2-deployment-stage-progression)
3. [Daily Startup Procedure](#3-daily-startup-procedure)
4. [Daily Shutdown Procedure](#4-daily-shutdown-procedure)
5. [Pre-Market Checklist (Manual)](#5-pre-market-checklist-manual)
6. [Market Hours Operations](#6-market-hours-operations)
7. [Post-Market Operations](#7-post-market-operations)
8. [Weekly Review Procedure](#8-weekly-review-procedure)
9. [Incident Management](#9-incident-management)
10. [Recovery Procedures](#10-recovery-procedures)
11. [Monitoring & Observability](#11-monitoring--observability)
12. [Deployment & Rollback](#12-deployment--rollback)
13. [Database Operations](#13-database-operations)
14. [Disaster Recovery](#14-disaster-recovery)

---

## 1. Architecture Freeze Policy

**The architecture is FROZEN as of Phase 24 (2026-06-27).**

### What is frozen

| Module | Frozen | Reason |
|--------|--------|--------|
| `signal_engine_service` | YES | Core pipeline |
| `signal_scanner_service` | YES | Gate logic |
| `risk_engine_service` | YES | Risk math |
| `position_sizer` | YES | Sizing logic |
| `overlay_pipeline` | YES | Attribution |
| `market_context_engine` | YES | Context |
| `mtf_confirmation` | YES | Multi-timeframe |
| All scoring components | YES | Score weights |
| `signal_config` (thresholds) | YES | Gate values |

### What is allowed

- Bug fixes (correcting incorrect behavior)
- Operational improvements (monitoring, alerting)
- Logging additions (never gating)
- Documentation updates
- Performance optimization (not behavioral changes)
- Deployment automation

### Unfreeze condition

Architecture can be unfrozen after **500+ completed trades** that validate the current system statistically. Run `/api/v1/research/freeze-check` before any proposed change.

---

## 2. Deployment Stage Progression

```
DEV → PAPER → ONE_LOT → TWO_LOTS → SCALED
```

| Stage | Description | Readiness Score Required |
|-------|-------------|--------------------------|
| DEV | Local development, no trades | Any |
| PAPER | Paper trading, order simulation | ≥ 40 (LIMITED) |
| ONE_LOT | 1 lot live trades per signal | ≥ 60 (READY_FOR_SMALL_CAPITAL) |
| TWO_LOTS | 2 lots live trades | ≥ 70 |
| SCALED | Full position sizing | ≥ 80 (READY_FOR_SCALING) |

Stage is set in `signal_config.py` → `execution_mode` and validated by `DeploymentReadinessService`.

---

## 3. Daily Startup Procedure

### Prerequisites
- Docker Desktop running
- VPN connected (if applicable)
- Kite Zerodha session active

### Steps

1. **Start Docker containers**
   ```
   docker-compose up -d
   ```
   Wait for `ssa_backend` to show `healthy`.

2. **Verify startup logs**
   ```
   docker logs ssa_backend --tail 50
   ```
   Look for:
   - `startup.postgres_ready`
   - `startup.redis_ready`
   - `background_task_registry started tasks=...`
   - `live_feed.startup_subscribed count=47`

3. **Authenticate Kite session**
   - Open frontend → Broker page
   - Click "Connect Kite" → complete OAuth flow
   - Verify session shows "Active"

4. **Run pre-market checklist**
   - Navigate to Operations → Pre-Market tab
   - Click "Run Checklist Now"
   - All checks must show green before market open

5. **Verify platform readiness**
   - Navigate to Operations → Platform Readiness
   - Overall status must be READY or WARNING (not NOT_READY)
   - Any NOT_READY component: see Recovery Procedures

6. **Set execution lock**
   - Navigate to Settings → Execution Lock
   - Set to AUTOMATIC only when Kite is authenticated and platform is READY
   - Otherwise keep MANUAL (orders blocked)

---

## 4. Daily Shutdown Procedure

1. **Lock execution** — Set execution lock to MANUAL
2. **Verify no open positions** — Check Positions page
3. **Stop Docker containers**
   ```
   docker-compose down
   ```
4. **Check EOD logs** — Verify outcome tracker and replay ran

---

## 5. Pre-Market Checklist (Manual)

Run at 08:45–09:00 IST every trading day. The platform auto-runs at 09:00 IST via `PreMarketChecklistService`.

| Check | Pass Condition |
|-------|----------------|
| Database | Query returns in < 200ms |
| Redis | PING responds in < 100ms |
| Kite Auth | Active session, not expired |
| WebSocket | `live_feed:connected = 1` in Redis |
| Scanner | Last scan < 10min ago (or first scan today) |
| Option Chain | Snapshot < 30min old |
| Candles | Latest candle < 30min old during market hours |

---

## 6. Market Hours Operations

**Market hours:** 09:15–15:30 IST, Monday–Friday

### What runs automatically
- Signal scanner: every 5 minutes
- Option chain poller: every 2 minutes  
- Portfolio monitor: every 30 seconds
- Broker reconciliation: every 60 seconds
- Dead man's switch: continuous
- Auto kill-switch: continuous

### What to monitor
- **Operations → Scan Metrics**: signal count, avg score, gate failures
- **Operations → Platform Readiness**: check for any WARNING/NOT_READY
- **System Health page**: background task heartbeats

### Intraday signal check (13:00–14:00 IST)
- If signals_generated = 0 for 3+ consecutive cycles: check Kite auth
- If avg_score < 30 consistently: normal (gate threshold is 70)
- If scanner idle > 15min during market hours: SCANNER_IDLE incident

### Kill switch
- Activated automatically on: daily loss > 2%, drawdown > 5%, rogue order detected
- Manual deactivation from: Trading Safety page → Kill Switch
- Does NOT block new signal generation (only order execution)

---

## 7. Post-Market Operations

Run after 15:30 IST.

### Automatic (background tasks)
- Signal outcome tracker: marks signals as win/loss
- Market close exit service: closes all open positions

### Manual (run from UI)
1. **Post-Trade Analysis** — Post-Trade page → run all sections
2. **Weekly Report** (Fridays only) — Research page → Generate Weekly Report
3. **Validation** — Validation page → review all 5 sections

---

## 8. Weekly Review Procedure

Run every Friday after market close.

### Steps
1. Navigate to Research page → Generate Weekly Report
2. Review cohort performance by dimension
3. Check Validation → Milestones (are we progressing toward 500 trades?)
4. Review Operations → Incidents from the week
5. Review Operations → Scan Metrics 7-day summary
6. Check Validation → Drift (production vs baseline)
7. Document findings — **do NOT modify architecture** without freeze-check

### Key metrics to track
- Win rate trend (Wilson CI should be tightening)
- Avg score trend (target: meaningful portion approaching 70+)
- Data quality score (target: ≥ 0.7)
- Kite auth interruptions (count incidents)

---

## 9. Incident Management

### Incident Types

| Type | Severity | Auto-Detected | Recovery |
|------|----------|---------------|---------|
| KITE_AUTH_EXPIRED | HIGH | Platform Readiness | Re-authenticate from Broker page |
| SCANNER_IDLE | HIGH | Platform Readiness | Check Kite auth → restart scanner |
| MARKET_DATA_STALE | HIGH | Platform Readiness | Check Kite auth |
| REDIS_DISCONNECTED | CRITICAL | Platform Readiness | Restart Redis container |
| DB_CONNECTION_LOST | CRITICAL | Platform Readiness | Restart PostgreSQL container |
| EXECUTION_HALTED | MEDIUM | Manual | Check kill switch + execution lock |
| KILL_SWITCH_TRIGGERED | HIGH | Manual | Investigate trigger, deactivate when safe |
| OPTION_CHAIN_STALE | MEDIUM | Platform Readiness | Check option chain poller |
| SIGNAL_GATE_FAILURE | MEDIUM | Manual | Check Kite auth (causes stale candles → gate failure) |
| VIX_SPIKE | LOW | Manual | VIX > 22 gates all scans — normal behavior |
| RISK_BREACH | HIGH | Manual | Review portfolio heat / drawdown |
| WEBSOCKET_DISCONNECTED | MEDIUM | Platform Readiness | Live feed will reconnect automatically |

### Logging an incident
1. Navigate to Operations → Incidents → Log Incident
2. Fill: type, severity, title, root cause, impact
3. Save — incident is time-stamped

### Resolving an incident
1. Find the incident in the list
2. Click "Resolve"
3. Fill: resolution description
4. Save — duration is auto-computed

---

## 10. Recovery Procedures

### Kite Session Recovery
1. Broker page → "Disconnect"
2. Broker page → "Connect Kite" → complete OAuth
3. Wait for `session_expiry_watcher` to detect new session (< 60s)
4. Verify: Platform Readiness → Kite shows READY
5. Log incident: KITE_AUTH_EXPIRED with resolution

### Redis Recovery
```
docker restart ssa_redis
docker logs ssa_redis --tail 20
```
Wait for `ready to accept connections`. Backend will reconnect automatically.

### PostgreSQL Recovery
```
docker restart ssa_postgres
docker logs ssa_postgres --tail 20
```
Wait for `database system is ready to accept connections`. Backend will reconnect.

### Scanner Restart
```
docker restart ssa_backend
```
All background tasks restart with supervised backoff. Verify via `docker logs ssa_backend --tail 50`.

### Market Data Recovery
- Root cause is almost always Kite auth expiry
- Reconnect Kite session → wait 5 minutes → candles populate
- Scanner stale candle gate will clear on next cycle

### WebSocket Recovery
- Live feed reconnects automatically via `live_feed_service`
- Check: `docker logs ssa_backend | grep live_feed`
- If still failing after 5min: `docker restart ssa_backend`

### Option Chain Recovery
- Option chain poller runs every 2min
- If stale: check Kite auth (option chain requires Kite API)
- Verify recovery: Platform Readiness → Option Chain shows READY

### Kill Switch Recovery
1. Identify trigger (check logs: `kill_switch.triggered reason=...`)
2. Resolve the underlying issue
3. Trading Safety page → Kill Switch → Deactivate
4. Log incident with root cause and resolution

### Full Platform Recovery (Docker restart)
```
docker-compose down
docker-compose up -d
```
Wait 60 seconds, then run pre-market checklist.

---

## 11. Monitoring & Observability

### Platform Readiness (Operations page)
Primary health dashboard. Refresh every 30 seconds automatically. Shows READY/WARNING/NOT_READY per component.

### Key Prometheus metrics (`/metrics`)
- `scanner_cycle_duration_seconds` — scan cycle wall time
- `signals_generated_total` — cumulative signals
- `signals_gate_rejected_total` — gate rejections
- `orders_placed_total` — orders submitted
- `kill_switch_active` — 1 if kill switch is on

### Log locations (inside container)
```
docker logs ssa_backend --follow
docker logs ssa_redis
docker logs ssa_postgres
```

### Background task supervision
All 12 background tasks restart on failure with exponential backoff (1s → 60s). Failures logged at ERROR level. No silent failures.

---

## 12. Deployment & Rollback

### Deploy new version
```
git pull origin main
docker-compose build backend
docker-compose up -d --no-deps backend
docker logs ssa_backend --follow --tail 30
```
Verify: startup logs show all services ready.

### Run migrations after deploy
```
docker exec ssa_backend alembic upgrade head
```
Verify: migration completes without errors.

### Rollback procedure
```
git checkout <previous-tag>
docker-compose build backend
docker-compose up -d --no-deps backend
```
If DB migration needs rollback:
```
docker exec ssa_backend alembic downgrade -1
```

### Pre-deploy checklist
- [ ] All tests pass: `docker exec ssa_backend python -m pytest --tb=short`
- [ ] No open positions
- [ ] Execution lock set to MANUAL
- [ ] DB backup taken (see Database Operations)
- [ ] Change is NOT a frozen-module change (run freeze-check)

---

## 13. Database Operations

### Backup
```
docker exec ssa_postgres pg_dump -U trading trading > backup_$(date +%Y%m%d_%H%M).sql
```

### Restore
```
docker exec -i ssa_postgres psql -U trading trading < backup_YYYYMMDD_HHMM.sql
```

### Check migration status
```
docker exec ssa_backend alembic current
docker exec ssa_backend alembic history --verbose
```

### Run pending migrations
```
docker exec ssa_backend alembic upgrade head
```

### Common queries
```sql
-- Signal count by outcome today
SELECT outcome, COUNT(*) FROM signals
WHERE created_at::date = CURRENT_DATE
GROUP BY outcome;

-- Scan metrics last 24h
SELECT AVG(signals_generated), AVG(avg_score), COUNT(*)
FROM scan_cycle_metrics
WHERE cycle_at > NOW() - INTERVAL '24 hours';

-- Open incidents
SELECT id, incident_type, severity, title, start_time
FROM incidents WHERE is_resolved = false
ORDER BY start_time DESC;
```

---

## 14. Disaster Recovery

### Full data loss (DB)
1. Restore from latest backup: see Database Operations → Restore
2. Run migrations to latest: `alembic upgrade head`
3. Restart backend: `docker-compose restart backend`
4. Log incident: DB_CONNECTION_LOST (CRITICAL)

### Redis data loss
Redis is ephemeral for all non-critical data. After restart:
1. Execution lock seeds from `signal_config.py` default
2. Kill switch auto-deactivates at startup
3. Account state re-seeds from DB
4. No trades or signals are lost (source of truth is PostgreSQL)

### Complete container data loss
1. PostgreSQL data is in Docker volume `ssa_pgdata`
2. Redis data is ephemeral (intentional)
3. Restore DB from external backup if volume lost
4. All application state is in DB — Redis is a cache layer only

### Broker position mismatch after recovery
1. Broker page → Reconciliation → Run Full Reconciliation
2. Review discrepancies
3. Manually match any orphaned positions
4. Log incident: RISK_BREACH if significant mismatch

---

## Key URLs

| Resource | URL |
|----------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Metrics | http://localhost:8000/metrics |
| Platform Readiness | http://localhost:8000/api/v1/platform/readiness |
| Health | http://localhost:8000/api/v1/health |

---

*This handbook covers operational procedures only. Architecture decisions, strategy design, and system design are documented in the phase implementation notes.*
