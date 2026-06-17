# 23 — Security Baseline

**Platform:** NSE · Indian Equity FnO  
**Classification:** Required — no component may be deployed without satisfying this document  
**Version:** 1.0  

---

## Design Principles

> **Security is not a feature. It is a constraint on every feature.**

- No secret is ever stored in plaintext in a file, environment variable, or database column.
- No service has broader database permissions than its minimum functional requirement.
- No external surface is unauthenticated.
- Every credential has a defined rotation policy.
- Any breach of these rules is a P0 blocker — the platform does not go live until resolved.

---

## 1. Encryption Key Management

### 1.1 Broker Access Token Encryption

Kite access tokens are encrypted at the application layer using AES-256-GCM before being stored in the database or Redis. The encryption key is **not** stored in the database.

**Key storage tiers (choose one per deployment environment):**

| Environment | Key Source | Notes |
|-------------|-----------|-------|
| Local development | `.env` (git-ignored, never committed) | Only for local dev. Not for any shared environment. |
| Staging | AWS Secrets Manager or HashiCorp Vault | Fetched at startup, held in process memory only |
| Production | AWS KMS (envelope encryption) or HashiCorp Vault | HSM-backed; key never leaves the KMS boundary |

**Envelope encryption pattern (production):**
1. Platform generates a per-session Data Encryption Key (DEK) in memory.
2. DEK is encrypted by the KMS Key Encryption Key (KEK) → stored as `encrypted_dek` in Redis.
3. Broker token is encrypted using DEK in memory.
4. On restart: fetch `encrypted_dek` from Redis, decrypt with KMS to get DEK, decrypt tokens.
5. DEK is never written to disk in plaintext.

**Key rotation:**
- DEK: rotate daily at 06:00 IST (aligned with Kite token expiry cycle).
- KEK: rotate annually or on suspected compromise. Rotation requires re-encrypting all stored DEKs.
- Rotation events are logged to `key_rotation_events` table (append-only, admin-only access).

### 1.2 Database Credentials

- Database password is never hardcoded. Sourced from Secrets Manager / Vault at startup.
- PgBouncer connection string is stored in the infrastructure secrets store (not in application config files).
- Password rotation: every 90 days, or immediately on team member departure.

### 1.3 API Keys (OpenAI, News Provider, etc.)

- Stored in Secrets Manager. Never in `.env` for staging/production.
- Never logged (structlog must have a secrets scrubber that redacts known key patterns).
- Budget controls enforce spending limits even if a key is compromised (see Doc 15).

---

## 2. First-Run Initialization Protocol

The platform has no hardcoded default credentials. On first launch:

```
Startup sequence (first run detected: no admin user in DB):

1. Generate random admin password:
   password = secrets.token_urlsafe(32)   (Python secrets module)

2. Hash with Argon2id (not bcrypt, not MD5):
   password_hash = argon2id.hash(password, memory=65536, iterations=3, parallelism=4)

3. Store hashed password in users table (admin user, role=ADMIN, force_change=True)

4. Print ONCE to stdout (visible in deployment logs for operator to capture):
   ╔══════════════════════════════════════════════════════════╗
   ║  ADMIN CREDENTIALS — COPY NOW, NOT SHOWN AGAIN          ║
   ║  Username: admin                                         ║
   ║  Password: <generated_password>                          ║
   ║  This password must be changed at first login.          ║
   ╚══════════════════════════════════════════════════════════╝

5. password is immediately zeroed from memory after printing.

6. force_change = True: any API call with this account returns HTTP 403 with
   {"error": "PASSWORD_CHANGE_REQUIRED", "redirect": "/api/v1/auth/change-password"}
   until the password is changed.
```

**The password is never stored in plaintext anywhere, at any time.**

---

## 3. Redis Security

Redis holds kill switch state, position Greeks, LTP cache, and session tokens — all operationally critical.

### 3.1 Authentication

```
# redis.conf
requirepass <strong_random_password_from_secrets_manager>
```

The Redis password is stored in Secrets Manager. The application receives it at startup via the secrets client. It is never in a config file.

### 3.2 Network Binding

```
# redis.conf
bind 127.0.0.1                # local only in Phase 1 (single-machine)
protected-mode yes             # extra guard
```

In multi-machine Phase 2+: bind to a private network interface only. Never expose Redis port publicly. TLS required for any network-boundary Redis traffic (`tls-port`, `tls-cert-file`, `tls-key-file`).

### 3.3 Dangerous Commands

```
# redis.conf
rename-command FLUSHALL ""     # disable
rename-command FLUSHDB  ""     # disable
rename-command CONFIG   ""     # disable (use redis-cli CONFIG only from localhost)
rename-command DEBUG    ""     # disable
rename-command EVAL     "EVAL_RESTRICTED_<random_suffix>"  # rename, not fully disable
```

### 3.4 Key Naming — Information Exposure Reduction

Signal dedup keys must not expose weight configuration details:

```
# Old (leaks weight config hash):
signal:dedup:{symbol}:{direction}:{weight_config_hash}

# New (uses signal fingerprint UUID — opaque):
signal:dedup:{symbol}:{direction}:{dedup_period_epoch_bucket}
```

The `weight_config_hash` is stored inside the signal record in the DB — it does not need to appear in Redis key names.

---

## 4. JWT Authentication

### 4.1 Signing Algorithm and Secret

- Algorithm: **RS256** (asymmetric RSA) for production. Not HS256 (shared secret is a single point of failure).
- RSA key pair: 4096-bit. Private key stored in Secrets Manager. Public key distributed to services that only need to verify tokens.
- Key rotation: 90 days. Old public key retained for 24 hours post-rotation to allow in-flight token verification.

### 4.2 Token Lifecycle

| Token Type | Expiry | Storage | Revocation |
|-----------|--------|---------|------------|
| Access token | 15 minutes | HTTP-only cookie or Authorization header | JWT `jti` claim in Redis blocklist |
| Refresh token | 7 days | HTTP-only cookie only | DB record; revoked on logout |
| Admin session | 8 hours (market hours max) | HTTP-only cookie | DB record |

**Token revocation:** On logout, the JWT `jti` (JWT ID) is added to a Redis SET `auth:revoked:{jti}` with TTL = remaining token lifetime. The authentication middleware checks this set on every request. This adds ~1ms to every authenticated request — acceptable.

### 4.3 Brute-Force Protection

```
Rate limiting on /api/v1/auth/login:
  5 failed attempts per IP in 10 minutes → lockout for 30 minutes
  Lockout state stored in Redis: auth:lockout:{ip_hash}
  Alert triggered on 10+ failed attempts from same IP
```

### 4.4 Admin Endpoints — Additional Controls

Kill switch and risk limit modification endpoints require:
1. Valid admin JWT (role=ADMIN).
2. Source IP in the configured allowlist (`config/security.yaml: allowed_admin_ips`).
3. 2FA code (Phase 2 enhancement — TOTPAuth).

The IP allowlist is stored in `config/security.yaml` (not in the database) — it must be managed via deployment config, not via an API that could be compromised.

---

## 5. Database Permission Model

The application connects as the `trading_app` database user. This user's permissions:

| Table / Domain | SELECT | INSERT | UPDATE | DELETE |
|---------------|--------|--------|--------|--------|
| `users` | ✓ | ✓ | ✓ (own row only) | ✗ |
| `instruments` | ✓ | ✗ | ✗ | ✗ |
| `market_data` (hypertable) | ✓ | ✓ | ✗ | ✗ |
| `option_chain` (hypertable) | ✓ | ✓ | ✗ | ✗ |
| `market_features` | ✓ | ✓ | ✗ | ✗ |
| `signals` | ✓ | ✓ | ✓ (state only) | ✗ |
| `orders` | ✓ | ✓ | ✓ (state, fill fields) | ✗ |
| `positions` | ✓ | ✓ | ✓ (mtm, state) | ✗ |
| `risk_decisions` | ✓ | ✓ | ✗ | ✗ |
| `kill_switch_events` | ✓ | ✓ | ✗ | ✗ |
| `signal_events` (hypertable) | ✓ | ✓ | ✗ | ✗ |
| `order_events` (hypertable) | ✓ | ✓ | ✗ | ✗ |
| `signal_performance_stats` | ✓ | ✓ | ✗ | ✗ |
| `ai_usage_log` | ✓ | ✓ | ✗ | ✗ |
| `instrument_refresh_log` | ✓ | ✓ | ✗ | ✗ |

A separate `migration_user` with full DDL rights is used only for Alembic migrations. It is never used by the running application.

TimescaleDB retention policies (which delete old chunks) run as the `timescaledb_admin` user — not as `trading_app`. This ensures the application layer cannot inadvertently delete data.

---

## 6. TLS / HTTPS

### External API

All REST API endpoints are served over HTTPS only. HTTP requests receive a `301 Redirect` to HTTPS.

```
TLS version: TLS 1.2 minimum, TLS 1.3 preferred
Cipher suites: ECDHE-RSA-AES256-GCM-SHA384 and equivalents (no RC4, no 3DES, no CBC-mode weak suites)
Certificate: Let's Encrypt (auto-renew) or internal PKI
HSTS header: Strict-Transport-Security: max-age=31536000; includeSubDomains
```

### Internal Service Communication (Phase 2+)

When services run on separate machines, all inter-service traffic (app ↔ Redis, app ↔ PostgreSQL, app ↔ PgBouncer) uses TLS mutual authentication (mTLS). In Phase 1 (single machine), loopback communication is acceptable.

---

## 7. Secrets Scrubbing in Logs

structlog must never log secrets. A scrubbing processor is added to the structlog pipeline:

```
Patterns to scrub (replace with "[REDACTED]"):
  - Any field named: password, token, api_key, secret, access_key, private_key, credential
  - Values matching: sk-[a-zA-Z0-9]{48} (OpenAI keys)
  - Values matching: Bearer [a-zA-Z0-9._-]+ (auth tokens in headers)
  - Values matching: [0-9a-f]{64} in fields named: hash, signature (potential key material)
```

The scrubber runs as a structlog processor before any log handler (file, stdout, or remote).

---

## 8. Dependency Security

### Python Dependencies

```
# Required in CI pipeline:
pip-audit --requirement requirements.txt   # checks against OSV/NVD
safety check                               # secondary check

# Dependency pinning:
All production dependencies are pinned to exact versions in requirements.txt.
requirements.in contains unpinned declarations.
pip-compile generates requirements.txt deterministically.
```

No dependency with a known HIGH or CRITICAL CVE may be deployed to production.

### Docker Image (if containerized)

- Base image: `python:3.12-slim-bookworm` (minimal attack surface).
- No root user in container: `USER nonroot:nonroot`.
- No secrets in Dockerfile or image layers.
- Image scanned by `trivy` in CI pipeline.

---

## 9. Audit and Compliance

### Sensitive Actions — Full Audit Trail

Every action in this list writes an immutable record to the `audit_log` table:

- Admin login / logout
- Kill switch activation / deactivation
- Risk limit change
- Broker session authentication
- Signal execution (order placed)
- Manual order cancellation
- Password change
- IP allowlist modification
- Weight configuration change (weight_config_hash change)

### `audit_log` Table

```
audit_log
─────────────────────────────────────────────────────────
id               BIGSERIAL        PRIMARY KEY
actor_user_id    INTEGER                      FK → users (NULL for system actions)
actor_type       VARCHAR(20)      NOT NULL    (USER, SYSTEM, RISK_ENGINE, DEAD_MANS_SWITCH)
action           VARCHAR(50)      NOT NULL
resource_type    VARCHAR(30)                  (KILL_SWITCH, ORDER, RISK_LIMIT, etc.)
resource_id      VARCHAR(50)
ip_address       INET
user_agent       TEXT
request_id       VARCHAR(50)                  (correlation_id)
metadata         JSONB                        (before/after state for config changes)
created_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW()
```

Application DB user has INSERT permission only. No UPDATE. No DELETE.  
SEBI requires 2-year minimum retention for trading records. `audit_log` retention: 5 years.

---

## 10. Security Checklist — Pre-Production Gate

No deployment to production is permitted with any item unchecked:

- [ ] No hardcoded credentials in any source file (`git grep -r "password\s*=\s*['\"]" src/`)
- [ ] All secrets sourced from Secrets Manager (not `.env`)
- [ ] Redis `requirepass` enabled and tested
- [ ] Redis dangerous commands disabled (FLUSHALL, CONFIG, DEBUG)
- [ ] Database `trading_app` user has no DDL rights (verify with `\dp` in psql)
- [ ] JWT uses RS256 with keys from Secrets Manager
- [ ] All admin endpoints return 403 from non-allowlisted IPs
- [ ] `pip-audit` passes with zero HIGH/CRITICAL findings
- [ ] TLS enforced on all external endpoints
- [ ] First-run generates random admin password (not `admin/admin`)
- [ ] structlog secrets scrubber active and tested
- [ ] `audit_log` table created and INSERT-only permission verified
- [ ] Broker token encryption tested (encrypt → store → restart → decrypt → use)
- [ ] Key rotation procedure documented and rehearsed

---

*Cross-references: Doc 09 (Execution Rules — forbidden practices) · Doc 14 (Kill Switch — IP allowlist, admin auth) · Doc 15 (AI Provider — cost controls and key management) · Doc 18 (Database — permission model)*  
*This document must be reviewed and re-signed-off by the lead engineer after any credential rotation event.*
