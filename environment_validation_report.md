# Environment Validation Report
**Project:** StockSignalAnalyzer  
**Date:** 2026-06-16  
**Environment:** development  
**Source:** D:\StockSignalAnalyzer\.env

---

## Executive Summary

The `.env` file contains 37 configuration variables spanning application settings, security, AI provider, database, Redis, WebSocket, rate limiting, and broker credentials. All critical operational variables are present with two notable exceptions: `NEWSAPI_AI_KEY` is absent (the news subsystem uses free public RSS feeds instead, so this is not a blocker), and `DATABASE_READ_URL` is intentionally left blank (read/write split is not enabled in development). The Azure OpenAI integration is fully configured. Kite broker credentials are present but trading is running in PAPER mode. No secrets are stored in plaintext beyond the `.env` file itself, with the exception of the broker token encryption key which should be moved to a secrets manager before production deployment.

---

## Variable Audit Table

### Application Settings

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| APP_NAME | PRESENT | StockSignalAna*** | Application display name |
| APP_VERSION | PRESENT | 0.1.0 | Semantic version |
| ENVIRONMENT | PRESENT | developme*** | Set to `development`; must be `production` before go-live |
| DEBUG | PRESENT | true | Must be set to `false` in production |
| API_HOST | PRESENT | 0.0.0.0 | Binds to all interfaces; acceptable for local dev |
| API_PORT | PRESENT | 8000 | Standard FastAPI port |

### Logging

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| LOG_LEVEL | PRESENT | DEBUG | Set to `INFO` or `WARNING` in production |
| LOG_FORMAT | PRESENT | console | Switch to `json` for structured logging in production |

### Security / Auth

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| SECRET_KEY | PRESENT | 3b76b7*** | 64-hex-char key; strong entropy; rotate before production |
| ALLOWED_ADMIN_IPS | PRESENT | 127.0.0*** | Localhost-only admin; acceptable for dev |
| CORS_ALLOWED_ORIGINS | PRESENT | http://lo*** | Locked to localhost:3000 |
| ACCESS_TOKEN_TTL_SECONDS | PRESENT | 900 | 15-minute JWT access token; appropriate |
| REFRESH_TOKEN_TTL_SECONDS | PRESENT | 604800 | 7-day refresh token; acceptable |
| MAX_LOGIN_ATTEMPTS | PRESENT | 5 | Brute-force lockout threshold |
| LOCKOUT_DURATION_SECONDS | PRESENT | 900 | 15-minute lockout; appropriate |

### AI Provider — Azure OpenAI

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| AI_PROVIDER | PRESENT | azure_op*** | Set to `azure_openai`; validated by `AIConfig.provider_must_be_valid` |
| AI_MODEL | PRESENT | gpt-4.1-*** | Model alias; maps to deployment in Azure |
| AI_DAILY_BUDGET_USD | PRESENT | 5.00 | $5/day guard; enforced at application level |
| AI_MAX_TOKENS_PER_CALL | PRESENT | 1000 | Per-call cap; matches AIConfig default |
| AI_TIMEOUT_SECONDS | PRESENT | 10 | 10-second HTTP timeout on AI calls |
| AZURE_OPENAI_API_KEY | PRESENT | 1IiACOI*** | Full key present; used by `AIClient._azure_openai()` |
| AZURE_OPENAI_ENDPOINT | PRESENT | https://b*** | `bharmalburhan26-9275-resource.services.ai.azure.com` |
| AZURE_OPENAI_DEPLOYMENT | PRESENT | gpt-4.1-*** | Deployment name: `gpt-4.1-mini` |
| AZURE_OPENAI_API_VERSION | PRESENT | 2025-01-*** | API version `2025-01-01-preview` |
| ANTHROPIC_API_KEY | EMPTY | (empty) | Not used; `AI_PROVIDER` is `azure_openai`; harmless |

### Database

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| DATABASE_WRITE_URL | PRESENT | postgresql*** | `postgresql+asyncpg://trading:trading@localhost:5432/trading` |
| DATABASE_READ_URL | EMPTY | (empty) | Read replica not configured; all reads go to write node |
| DATABASE_POOL_SIZE | PRESENT | 5 | Minimum pool size |
| DATABASE_MAX_OVERFLOW | PRESENT | 10 | Max burst connections |
| DATABASE_POOL_TIMEOUT | PRESENT | 30 | Connection timeout in seconds |

> **Note:** `DATABASE_READ_URL` being empty is acceptable in development. For production, configure a read replica to separate OLAP/reporting queries from the write path.

### Redis

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| REDIS_URL | PRESENT | redis://l*** | `redis://localhost:6379/0`; no auth (dev-safe) |
| REDIS_MAX_CONNECTIONS | PRESENT | 20 | Connection pool cap |
| REDIS_DECODE_RESPONSES | PRESENT | true | Strings decoded automatically; required for Pub/Sub channel matching |

### WebSocket Manager

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| WEBSOCKET_MAX_RECONNECT_ATTEMPTS | PRESENT | 5 | Frontend reconnect cap |
| WEBSOCKET_PING_INTERVAL_SECONDS | PRESENT | 3 | Frontend ping check interval |
| WEBSOCKET_PING_TIMEOUT_SECONDS | PRESENT | 2 | Frontend ping timeout |
| WEBSOCKET_TICK_STALE_THRESHOLD_SECONDS | PRESENT | 30 | Tick staleness alert threshold |
| WEBSOCKET_TICK_WARN_THRESHOLD_SECONDS | PRESENT | 10 | Tick staleness warning threshold |
| WEBSOCKET_SUBSCRIPTION_BATCH_DEBOUNCE_MS | PRESENT | 100 | Subscription batch debounce |
| WEBSOCKET_MAX_SUBSCRIPTIONS_PER_CONNECTION | PRESENT | 3000 | Per-connection subscription cap |

### Rate Limiting

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| RATE_LIMIT_REQUESTS_PER_MINUTE | PRESENT | 120 | 120 req/min per client |
| RATE_LIMIT_ENABLED | PRESENT | true | Rate limiter active |

### Broker

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| TRADING_MODE | PRESENT | paper | Set to `paper`; change to `live` to route real orders |
| KITE_API_KEY | PRESENT | wonpxy8*** | Kite Connect API key present |
| KITE_API_SECRET | PRESENT | lxsxdrg*** | Kite API secret present |
| KITE_SESSION_EXPIRY_HOUR_IST | PRESENT | 6 | Session expiry at 06:00 IST |
| BROKER_TOKEN_ENCRYPTION_KEY | PRESENT | a8f371c*** | 64-hex-char AES-256 key; used by `TokenEncryptor` |

### News Integration

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| NEWSAPI_AI_KEY | **MISSING** | N/A | `NEWSAPI_AI_KEY` is not present in `.env`. The news subsystem (`NewsAggregationService`) uses public RSS feeds only (Economic Times, Moneycontrol, Business Standard, NSE, Livemint). No paid NewsAPI.ai integration is active. The `POST /api/v1/news/refresh` endpoint will function normally. |

### Frontend Variables

| Variable | Status | Value (masked) | Notes |
|---|---|---|---|
| NEXT_PUBLIC_API_URL | NOT IN .env | N/A | Frontend reads from `frontend/.env.local` or defaults to `http://localhost:8000`; not in root `.env` by design |
| NEXT_PUBLIC_WS_URL | NOT IN .env | N/A | Same as above — `ws://localhost:8000` expected |

---

## Summary

| Category | Variables | Present | Missing / Empty |
|---|---|---|---|
| Application | 6 | 6 | 0 |
| Logging | 2 | 2 | 0 |
| Security / Auth | 7 | 7 | 0 |
| Azure OpenAI | 9 | 8 | 1 (ANTHROPIC_API_KEY — intentionally empty) |
| Database | 5 | 4 | 1 (DATABASE_READ_URL — intentionally empty) |
| Redis | 3 | 3 | 0 |
| WebSocket | 7 | 7 | 0 |
| Rate Limiting | 2 | 2 | 0 |
| Broker | 5 | 5 | 0 |
| News | 1 | 0 | **1 (NEWSAPI_AI_KEY — absent; RSS fallback active)** |
| Frontend | 2 | 0 | 2 (managed in frontend/.env.local) |

### Critical Findings

1. **NEWSAPI_AI_KEY is absent.** This is not a runtime blocker because the news aggregation service uses only public RSS feeds. If a paid NewsAPI.ai feed is added in a future phase, this key must be provisioned.

2. **DEBUG=true and ENVIRONMENT=development** must be updated before any production deployment.

3. **BROKER_TOKEN_ENCRYPTION_KEY is stored in `.env`**. While this is acceptable for local development, in production this 32-byte AES key must be stored in a secrets manager (Azure Key Vault, AWS Secrets Manager, or HashiCorp Vault) and fetched at runtime via `ISecretsClient`.

4. **DATABASE_READ_URL is empty.** All queries use the write database. This is an accepted configuration for development and single-node deployments.

5. **REDIS_URL has no authentication.** Acceptable on localhost; must add `redis://:password@host:port/db` format for any networked deployment.
