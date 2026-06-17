# 15 — AI Provider Abstraction

## Purpose

Define the interface, data contracts, prompt management, caching, fallback, and cost control architecture for all AI-assisted features. AI is an optional enrichment layer that improves signal quality but must never be a single point of failure. The platform must function correctly — generating signals, managing orders, and enforcing risk — when the AI provider is unavailable.

---

## Architectural Position

```
NewsPoller ──► SentimentService ──► [IAIProvider] ──► OpenAI / Anthropic / Gemini / Ollama
                      │
                      ▼
             Redis Cache (keyed by content hash)
                      │
                      ▼
         ScoringEngine reads cached SentimentResult
         (neutral fallback if cache empty)
```

AI calls are always asynchronous and always decoupled from the synchronous signal pipeline. The scoring engine never waits for an AI call. It reads from cache. If the cache is empty for a symbol, the sentiment component returns a neutral score (0) and a `confidence_degraded = true` flag.

---

## IAIProvider Interface

```
IAIProvider:
    provider_name:    str     (read-only property)
    model_version:    str     (read-only property, e.g., 'gpt-4o-mini')
    is_available() -> bool

    analyze_sentiment(request: SentimentRequest) -> SentimentResult
    classify_news(request: NewsClassificationRequest) -> NewsClassification
    summarize_news(request: NewsSummaryRequest) -> NewsSummary
    generate_market_commentary(request: MarketCommentaryRequest) -> MarketCommentary
    explain_trade(request: TradeExplanationRequest) -> TradeExplanation
    generate_eod_report(request: EODReportRequest) -> EODReport
```

All methods are async. All inputs and outputs are Pydantic models. No raw strings are passed to or returned from the interface.

---

## Output Data Models

### SentimentResult

```
SentimentResult:
    sentiment:       SentimentLabel        (BULLISH, BEARISH, NEUTRAL, MIXED)
    score:           float                 (-1.0 to +1.0; +1.0 = strongly bullish)
    confidence:      float                 (0.0 to 1.0)
    entities:        list[EntitySentiment]
    key_factors:     list[str]             (max 3 factors driving the sentiment)
    prompt_version:  str
    model:           str
    tokens_used:     int
    latency_ms:      int
    is_fallback:     bool                  (True if returned from NeutralSentimentProvider)
```

### EntitySentiment

```
EntitySentiment:
    entity:          str           (e.g., 'NIFTY', 'RELIANCE', 'RBI')
    entity_type:     EntityType    (INDEX, STOCK, SECTOR, MACRO)
    sentiment:       SentimentLabel
    score:           float
    confidence:      float
```

### NewsClassification

```
NewsClassification:
    category:           NewsCategory     (EARNINGS, MACRO, REGULATORY, GEOPOLITICAL,
                                          TECHNICAL, CORPORATE_ACTION, FII_DII, OTHER)
    relevance_score:    float            (0.0 to 1.0; how relevant to Indian markets)
    urgency:            NewsUrgency      (BREAKING, HIGH, MEDIUM, LOW)
    affected_symbols:   list[str]
    affected_sectors:   list[str]
    prompt_version:     str
    model:              str
    tokens_used:        int
```

### NewsSummary

```
NewsSummary:
    headline:            str    (one sentence, max 120 chars)
    summary:             str    (max 3 sentences)
    market_implication:  str    (one sentence)
    prompt_version:      str
    model:               str
    tokens_used:         int
```

### TradeExplanation

```
TradeExplanation:
    signal_id:           UUID
    explanation:         str                  (plain English, max 200 words)
    score_rationale:     dict[str, str]        (component → reason)
    risk_summary:        str
    prompt_version:      str
    model:               str
    tokens_used:         int
```

---

## Prompt Registry

All prompts are stored in configuration files, not in code. Prompts are versioned using semantic versioning. The version is recorded alongside every AI response for historical comparability.

### Prompt File Structure

```
config/
  prompts/
    sentiment_analysis/
      v1.0.0.yaml
      v1.1.0.yaml       ← current
    news_classification/
      v1.0.0.yaml
    news_summary/
      v1.0.0.yaml
    market_commentary/
      v1.0.0.yaml
    trade_explanation/
      v1.0.0.yaml
    eod_report/
      v1.0.0.yaml
```

### Prompt YAML Schema

```yaml
name: sentiment_analysis
version: "1.1.0"
model_family: gpt
max_tokens: 512
temperature: 0.1
system_prompt: |
  You are a financial analyst specializing in Indian stock markets (NSE/BSE).
  You analyze news articles for their directional impact on Indian equities and derivatives.
  You always return structured JSON. You never hallucinate financial facts.
user_prompt_template: |
  Analyze the sentiment of the following news article for its impact on Indian equity markets.
  Return a JSON object matching the specified schema exactly.
  
  Article: {article_text}
  Published: {published_at}
  Source: {source}
output_schema:
  type: json_object
  required_fields: [sentiment, score, confidence, entities, key_factors]
changelog:
  - version: "1.1.0"
    date: "2026-01-15"
    change: "Added entity-level sentiment extraction"
  - version: "1.0.0"
    date: "2025-11-01"
    change: "Initial version"
```

### Prompt Loading Rules

- Prompts are loaded at startup. Missing prompt files are a fatal startup error.
- The active version for each prompt type is set in `config/settings.yaml` under `ai.prompts`.
- Prompt version can be changed without a code deployment (config-only change).
- Previous versions are retained for fallback and historical comparison.

---

## Provider Implementations

### OpenAIProvider

- Default model: `gpt-4o-mini` (speed and cost optimized)
- Premium model: `gpt-4o` (for end-of-day reports and complex explanations)
- Uses `response_format: { type: "json_object" }` for structured output
- Implements rate limiting via token bucket (configurable RPM and TPM limits)
- Implements retry with exponential backoff on 429 and 503 responses

### AnthropicProvider (Future)

- Default model: `claude-haiku-4-5` (low cost, high speed for sentiment)
- Uses tool use / JSON mode for structured output
- Same interface as OpenAIProvider

### GeminiProvider (Future)

- Default model: `gemini-2.0-flash`
- Uses response schema enforcement via Gemini's structured output API

### OllamaProvider (Local / Testing)

- For offline testing and CI environments
- No API cost; no network dependency
- Confidence scores are automatically capped at 0.6 when using this provider
- Not for production use

### NeutralSentimentProvider (Fallback)

This is not a real AI provider. It is a zero-dependency fallback that returns deterministic neutral values when all real providers are unavailable.

```
Returns SentimentResult:
    sentiment:   NEUTRAL
    score:       0.0
    confidence:  0.0
    is_fallback: True
    entities:    []
```

The scoring engine treats a fallback sentiment as "no information" and reduces the signal's confidence score by the weight of the sentiment component.

---

## Caching Architecture

### Cache Key Design

```
Redis Key:  ai:sentiment:{sha256(provider_name + prompt_version + normalized_text)}
TTL:        3600 seconds (1 hour)

Redis Key:  ai:classification:{sha256(provider_name + prompt_version + normalized_text)}
TTL:        3600 seconds

Redis Key:  ai:summary:{sha256(provider_name + prompt_version + normalized_text)}
TTL:        86400 seconds (24 hours)
```

**Text normalization before hashing:** lowercase, strip extra whitespace, remove HTML tags. The same article from two sources with minor whitespace differences hits the same cache key.

### Cache Miss Behaviour

```
1. Check Redis cache (< 1ms)
2. If hit: return cached result immediately
3. If miss:
   a. Return NeutralSentimentProvider result immediately to caller
   b. Enqueue async task to call AI provider
   c. When async task completes: write result to Redis, publish news.sentiment.computed
   d. ScoringEngine picks up the real sentiment on next scoring cycle
```

### Cache Warm-Up

During the pre-market routine (07:30 IST), the last 4 hours of news items with no cached sentiment are queued for batch processing before market open.

---

## Rate Limiting

Each provider maintains its own rate limiter using a token bucket algorithm. Limits are configurable.

### OpenAI Defaults

```yaml
ai:
  openai:
    requests_per_minute: 60
    tokens_per_minute:   150000
    tokens_per_day:      2000000
```

**When rate limit is at 80%:**
- Log WARNING
- Downgrade model from `gpt-4o` to `gpt-4o-mini` if premium was active
- Emit `system.health_check.failed` with severity WARNING

**When rate limit is hit (100%):**
- Return `NeutralSentimentProvider` result immediately
- Log ERROR + emit alert

---

## Cost Tracking

Every AI call records cost metadata to structured logs and to the `ai_usage_log` table.

### `ai_usage_log` Table

```
ai_usage_log
─────────────────────────────────────────────────────────
id               BIGSERIAL        PRIMARY KEY
provider         VARCHAR(30)      NOT NULL
model            VARCHAR(50)      NOT NULL
operation        VARCHAR(50)      NOT NULL    (sentiment, classification, etc.)
prompt_version   VARCHAR(20)      NOT NULL
input_tokens     INTEGER          NOT NULL
output_tokens    INTEGER          NOT NULL
total_tokens     INTEGER          NOT NULL
cost_usd         NUMERIC(10,6)    NOT NULL
latency_ms       INTEGER          NOT NULL
cache_hit        BOOLEAN          NOT NULL
created_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW()
correlation_id   VARCHAR(50)
```

### Budget Controls

```yaml
ai:
  daily_budget_usd:    5.00
  monthly_budget_usd:  100.00
  alert_threshold_pct: 80
```

When daily spend reaches 80%: emit alert + downgrade to cheapest models.
When daily spend reaches 100%: all AI calls return `NeutralSentimentProvider`; log CRITICAL on each call.

---

## AI Response Validation

All AI responses are validated before being stored or used. A response failing validation triggers a retry.

### Validation Rules

- `score` must be in [-1.0, +1.0]. Out-of-range: reject.
- `confidence` must be in [0.0, 1.0]. Out-of-range: reject.
- `sentiment` must be a defined enum value. Unknown value: reject.
- `entities` list must not exceed 20 items.
- All required fields must be present (enforced by Pydantic).
- Response must be valid JSON. Parse failure: reject and retry.
- 3 consecutive validation failures for the same input: return `NeutralSentimentProvider` and log the raw response for investigation.

---

## Forbidden Usage (Architecturally Enforced)

The following services must not have `IAIProvider` registered in their dependency injection container:

| Service | Reason |
|---|---|
| OMS | AI must never initiate or influence order placement |
| RiskEngine | Risk calculations are deterministic; AI introduces non-determinism |
| PositionSizer | Position sizing must be formula-based |
| ScoringEngine (direct) | AI feeds into scoring only through cached SentimentResult |
| KillSwitchService | Emergency stop must have no external dependencies |

These constraints are enforced by the DI container configuration, not by convention.

---

## Observability

| Metric | Type | Labels | Description |
|---|---|---|---|
| `ai_requests_total` | Counter | `provider`, `operation`, `cache_hit` | Total AI requests |
| `ai_request_errors_total` | Counter | `provider`, `operation`, `error_type` | Failed requests |
| `ai_latency_seconds` | Histogram | `provider`, `operation` | End-to-end latency |
| `ai_tokens_used_total` | Counter | `provider`, `model`, `operation` | Cumulative tokens |
| `ai_cost_usd_total` | Counter | `provider`, `model` | Cumulative cost |
| `ai_daily_budget_utilization` | Gauge | `provider` | % of daily budget consumed |
| `ai_cache_hit_ratio` | Gauge | `operation` | Cache effectiveness |
| `ai_fallback_total` | Counter | `reason` | Times NeutralProvider was used |
