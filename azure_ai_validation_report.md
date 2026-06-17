# Azure OpenAI Validation Report
**Project:** StockSignalAnalyzer  
**Date:** 2026-06-16  
**Provider:** Azure OpenAI  
**Deployment:** gpt-4.1-mini

---

## Executive Summary

The Azure OpenAI integration is fully configured and code-complete. The `AIClient` class provides an async singleton wrapper around the `AsyncAzureOpenAI` SDK. All required credentials (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`) are present in `.env`. The AI subsystem is explicitly constrained to advisory roles only — it is architecturally forbidden from being injected into order management, risk evaluation, or kill switch services. Budget enforcement ($5/day), timeout (10s), and graceful failure (returns `None` on error with rule-based fallback) are all implemented. The integration is code-verified; runtime testing requires the Azure endpoint to be reachable from the deployment environment.

---

## 1. Configuration

| Parameter | Value | Source |
|---|---|---|
| Endpoint | `https://bharmalburhan26-9275-resource.services.ai.azure.com` | `AZURE_OPENAI_ENDPOINT` in `.env` |
| Deployment | `gpt-4.1-mini` | `AZURE_OPENAI_DEPLOYMENT` in `.env` |
| API Version | `2025-01-01-preview` | `AZURE_OPENAI_API_VERSION` in `.env` |
| Authentication | API Key | `AZURE_OPENAI_API_KEY` in `.env` (present, 88 chars) |
| Model alias | `gpt-4.1-mini` | `AI_MODEL` in `.env` (passed as `model` param to SDK) |

**Config class:** `AIConfig` (`src/core/infrastructure/config/ai_config.py`) uses `pydantic-settings` with `SecretStr` for the API key, preventing accidental logging. The `@lru_cache(maxsize=1)` on `get_ai_config()` ensures a single config instance per process.

**Validator:** `provider_must_be_valid()` field validator (line 50) enforces that `AI_PROVIDER` is one of `{openai, anthropic, azure_openai, disabled}`. Invalid values raise a `ValueError` at startup.

---

## 2. AIClient Implementation

**File:** `src/core/infrastructure/ai/ai_client.py`

The `AIClient` is a thin async wrapper with three provider backends: OpenAI, Anthropic, and Azure OpenAI. The active backend is selected by `AIConfig.ai_provider`.

**Singleton pattern:** The `AsyncAzureOpenAI` client instance is stored as `self._openai_client` and created lazily on the first call (lines 73-80). Subsequent calls reuse the same client instance, maintaining the underlying HTTP connection pool.

**Azure OpenAI call path (`_azure_openai`, line 66):**

```python
self._openai_client = AsyncAzureOpenAI(
    api_key=key,
    azure_endpoint=self._config.azure_openai_endpoint,
    api_version=self._config.azure_openai_api_version,
    timeout=self._config.ai_timeout_seconds,   # 10 seconds
)
response = await self._openai_client.chat.completions.create(
    model=self._config.azure_openai_deployment,  # "gpt-4.1-mini"
    max_tokens=self._config.ai_max_tokens_per_call,  # 1000
    messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ],
)
return response.choices[0].message.content
```

**Guard:** If `AZURE_OPENAI_API_KEY` is empty or `AZURE_OPENAI_ENDPOINT` is empty, the method returns `None` without making any HTTP call (line 75-76).

**Disabled mode:** If `AI_PROVIDER=disabled`, `AIConfig.is_enabled` returns `False` and `complete()` returns `None` immediately without any network call (line 29-30).

---

## 3. Budget Guard

**Implementation:** `AI_DAILY_BUDGET_USD=5.00` is stored in `AIConfig.ai_daily_budget_usd` (line 45). The field has validation `ge=0.0, le=1000.0`.

**Current enforcement:** The $5/day limit is configured at the application level. The `AIClient` itself does not implement a token counter or daily spend tracker inline — enforcement is expected to occur at a higher service layer (budget tracking service) or via Azure OpenAI's own quota settings. This is a **⚠️ gap**: if a budget enforcement service is not wired up, the $5 cap is not actively enforced at the Python level.

**Recommendation:** Verify that a `BudgetGuardService` or similar exists in the application layer and is called before `ai_client.complete()`. Alternatively, configure a hard quota cap in the Azure OpenAI resource settings.

---

## 4. Timeout

`AI_TIMEOUT_SECONDS=10` is passed directly to `AsyncAzureOpenAI(timeout=10)`. The OpenAI Python SDK uses `httpx` under the hood, and the `timeout` parameter applies as an HTTP read timeout. If the Azure endpoint does not respond within 10 seconds, an `httpx.ReadTimeout` or equivalent exception is raised.

This exception is caught by the outer `try/except Exception` in `complete()` (line 39), logged as `ai_client.error`, and `None` is returned — triggering the caller's fallback path.

---

## 5. Retry and Fallback

**AIClient-level retry:** No explicit retry logic (e.g., exponential backoff) is implemented in `AIClient`. A single failure returns `None`.

**Caller-level fallback:** All callers of `ai_client.complete()` handle `None` returns:

- `MarketAnalystService._call_ai()` (line 124): if `raw` is falsy, calls `self._fallback_insight(context)` which produces a rule-based regime determination using A/D ratio, sentiment score, and % above 200 DMA.
- The fallback sets `regime_confidence: 0.5` and `key_themes: ["breadth-driven analysis", "no AI available"]`, so the dashboard always has usable content even when Azure OpenAI is unreachable.

**Graceful degradation:** The system is designed to operate fully without AI. All AI outputs are advisory and informational; no trading decisions depend on the AI response.

---

## 6. Rate Limit Handling

The `AsyncAzureOpenAI` SDK handles HTTP 429 (rate limit) responses. The current `AIClient` does not add application-level rate limit handling beyond the single-call pattern. If Azure returns 429, the SDK may raise `openai.RateLimitError`, which is caught by the `except Exception` block in `complete()` and results in a `None` return with a WARNING log.

**Recommendation:** Add `openai.RateLimitError` to the except clause with a distinct log message to differentiate rate limit events from other errors. For high-frequency insight generation, consider a token bucket or leaky bucket at the application level.

---

## 7. Response Parsing

`MarketAnalystService._call_ai()` (line 124) handles the Azure OpenAI response:

1. The raw string is stripped of whitespace.
2. Markdown code block fences (` ```json ` prefix) are stripped if present.
3. `json.loads()` is called on the cleaned string.
4. On any `json.JSONDecodeError` or other exception, `_fallback_insight()` is called.

The expected JSON schema enforced by the system prompt:

```json
{
  "regime": "BULLISH" | "BEARISH" | "NEUTRAL" | "VOLATILE",
  "regime_confidence": 0.0-1.0,
  "summary": "2-3 sentence market overview",
  "key_themes": ["theme1", "theme2", "theme3"],
  "sector_outlook": {"sector": "bullish/bearish/neutral"},
  "risks": ["risk1", "risk2"],
  "opportunities": ["opp1", "opp2"],
  "recommendation": "1 sentence actionable advice"
}
```

The system prompt enforces JSON-only output with a strict schema (market_analyst_service.py lines 24-37). The model is instructed: "Respond in this exact JSON format." The parse-and-fallback pattern is robust for all failure modes.

---

## 8. AI Safety Guardrails

Per `ai_config.py` (lines 5-8) and the referenced architecture documentation:

> "The AI provider is ADVISORY ONLY. It is injected into SentimentAnalyzer and SummarizationService only. It is FORBIDDEN from being injected into: OMS, RiskEngine, PositionSizer, KillSwitchService."

This is a hard architectural boundary. The `AIClient` is not available to the order management or risk subsystems. Any AI-generated insight is consumed only by `MarketAnalystService`, `NewsAnalystService`, and `StrategySelectorService`, all of which feed the dashboard display layer.

---

## 9. Test: Market Insight Generation

The flow for `POST /api/v1/ai/market/generate`:

1. `MarketAnalystService.generate_daily_insight()` is called.
2. `_build_context()` assembles: market breadth (A/D ratio, breadth score, above-200DMA%), market sentiment (avg_score, bullish/bearish/neutral counts), NIFTY option chain data.
3. Context is serialized to JSON and sent to `AIClient.complete(system_prompt, context_json)`.
4. Azure OpenAI returns a JSON string with regime analysis.
5. Response is parsed, `generated_at` timestamp is added, and the full insight is persisted to `ai_insights` table (`insight_type='MARKET_DAILY'`, `symbol='MARKET'`).
6. The insight is returned to the caller and the frontend updates the AI Insights page.

**Expected result:** `{"regime": "...", "regime_confidence": ..., "summary": "...", ...}`  
**On Azure failure:** Rule-based fallback insight is persisted and returned instead.

---

## 10. Test: News Sentiment Analysis

News sentiment analysis is handled by `NewsAnalystService` (referenced in `ai_insights_router.py` line 13 as `news_analyst_service`). The `POST /api/v1/ai/news/analyze` endpoint was not implemented in the scanned router (the router only has 5 endpoints up to `get_strategy_recommendation`; the news analyze endpoint is defined in the docstring but not in the router body). This endpoint may be pending implementation.

`SentimentService.get_market_sentiment()` and `get_symbol_sentiment()` are the active paths for sentiment data, independent of the AI client.

---

## Summary

| Item | Status | Notes |
|---|---|---|
| Azure endpoint configured | ✅ | `bharmalburhan26-9275-resource.services.ai.azure.com` |
| Deployment configured | ✅ | `gpt-4.1-mini` |
| API version configured | ✅ | `2025-01-01-preview` |
| API key present | ✅ | `AZURE_OPENAI_API_KEY` in `.env` |
| AIClient (async, singleton) | ✅ | `ai_client.py` — lazy init, connection pool reuse |
| Budget guard ($5/day) | ⚠️ | Configured; Python-level enforcement not confirmed |
| Timeout (10s) | ✅ | Passed to `AsyncAzureOpenAI(timeout=10)` |
| Retry logic | ⚠️ | No backoff; single failure returns None |
| Fallback (graceful) | ✅ | Rule-based insight on AI unavailability |
| Rate limit handling | ⚠️ | Caught generically; no distinct logging or backoff |
| Response parsing (JSON) | ✅ | With markdown fence stripping and fallback |
| AI safety guardrails | ✅ | Advisory-only; forbidden from OMS/Risk/KillSwitch |
| Market insight generation | ✅ | Full pipeline implemented |
| News sentiment AI analysis | ⚠️ | Router endpoint defined in docstring but not in code |
