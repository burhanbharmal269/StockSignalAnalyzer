# AI Pipeline Validation Report
**Project:** StockSignalAnalyzer  
**Date:** 2026-06-16  
**Pipeline:** News → Sentiment → Market Context → AI Analysis → Dashboard

---

## Executive Summary

The AI intelligence pipeline is a sequential data enrichment chain that transforms raw financial news and market breadth data into human-readable market insights displayed on the dashboard. The pipeline has five distinct stages: news ingestion (RSS), sentiment scoring, market context assembly, Azure OpenAI analysis, and frontend presentation. Each stage has graceful degradation — failures in any upstream stage produce neutral/empty context rather than blocking downstream steps. The pipeline is code-complete and the AI analysis step produces structured JSON that the frontend renders directly. The entire pipeline is advisory only and does not interact with order execution.

---

## Pipeline Overview

```
[RSS Feeds x6]
      ↓
[NewsAggregationService]   — fetch_all() → news_events table
      ↓
[SentimentService]         — score articles → avg_score, direction
      ↓
[MarketBreadthService]     — A/D ratio, above_200dma_pct, 52w highs/lows
[OptionChainService]       — NIFTY OI, put/call ratio
      ↓
[MarketAnalystService]     — _build_context() → JSON context
      ↓
[AIClient (Azure OpenAI)]  — gpt-4.1-mini → structured JSON insight
      ↓
[ai_insights table]        — persisted as JSONB
      ↓
[GET /api/v1/ai/market]    — serves latest insight
      ↓
[AIInsightsView (frontend)]— rendered on /ai-insights page
```

---

## Stage 1: News Ingestion

**What happens:** `NewsAggregationService.fetch_all()` polls six public RSS feeds. For each feed, articles are parsed from XML, content-hashed for deduplication, and persisted to the `news_events` table with source tags, categories, and extracted NSE symbols.

**Trigger:** `POST /api/v1/news/refresh` (manual) or a background scheduler task.

**Stored in:** `news_events` table. Fields: `source`, `title`, `content`, `url`, `content_hash`, `published_at`, `symbols[]`, `categories[]`.

**What the frontend shows:** The `GET /api/v1/news` endpoint returns up to 200 recent news events. No dedicated news list page was found in the frontend; news data flows primarily into sentiment scoring.

**Failure behavior:** Per-feed exception isolation. A failed feed emits a WARNING log and processing continues. Returns `{"fetched": 0}` if all feeds fail.

---

## Stage 2: Sentiment Scoring

**What happens:** `SentimentService` reads articles from `news_events` and computes sentiment scores. The service produces:

- `avg_score`: float, typically -1.0 to 1.0
- `direction`: `BULLISH` / `BEARISH` / `NEUTRAL`
- `total_articles`: count of scored articles
- `bullish`, `bearish`, `neutral`: article counts by sentiment category

**Trigger:** Scores are pre-computed and queried on-demand via:
- `GET /api/v1/news/sentiment/market` — overall market sentiment
- `GET /api/v1/news/sentiment/{symbol}?hours=24` — per-symbol sentiment window (1-168 hours)

**Stored in:** Sentiment scores are stored as computed fields or in an associated sentiment table; the exact schema is managed by `SentimentService`.

**What the frontend shows:** Market Overview page (`market-overview-view.tsx`) displays:
- Overall direction badge (BULLISH/BEARISH/NEUTRAL)
- Average score (3 decimal places)
- Total articles analyzed
- Bullish / Bearish / Neutral article counts

If no sentiment data is available, the page shows: "No sentiment data yet. Run 'News Refresh' from the News section to populate."

---

## Stage 3: Market Context Assembly

**What happens:** `MarketAnalystService._build_context()` assembles a structured dict containing all available market intelligence data for the AI prompt. Each data source is fetched independently with per-source exception isolation:

```python
context = {
    "breadth": {
        "advances": int,
        "declines": int,
        "ad_ratio": float,
        "breadth_score": float,
        "above_200dma_pct": float,
        "new_highs_52w": int,
        "new_lows_52w": int,
    },
    "sentiment": {
        "avg_score": float,
        "direction": str,
        "total_articles": int,
        "bullish": int,
        "bearish": int,
        "neutral": int,
    },
    "nifty_options": { ... }   # Put/call ratios, OI data
}
```

**Data sources:**
- `MarketBreadthService.get_latest()` — breadth data from market hours collection
- `SentimentService.get_market_sentiment()` — current sentiment aggregation
- `OptionChainService.get_latest("NIFTY")` — NIFTY option chain data

**Failure isolation:** Each data source is wrapped in `try/except Exception`; on failure, that key is simply absent from the context dict. The AI prompt is built with whatever data is available. An empty context produces a neutral fallback insight.

**Stored in:** Context is not independently persisted. It is embedded in the `ai_insights.content` JSONB field under the `"context"` key.

---

## Stage 4: AI Analysis (Azure OpenAI)

**What happens:** `MarketAnalystService._call_ai(context)` sends the assembled context to Azure OpenAI:

**System prompt** (market_analyst_service.py lines 24-37):

> "You are a senior NSE/BSE equity and derivatives market analyst. You receive aggregated market intelligence (NOT individual prices) and produce a concise market briefing. Be specific, actionable, and data-driven. Respond in this exact JSON format: {...}"

**User prompt:**
```
Market Intelligence Data:
{JSON serialization of context dict, pretty-printed with indent=2}
```

**Model:** `gpt-4.1-mini` via `AZURE_OPENAI_DEPLOYMENT`  
**Max tokens:** 1,000 (enforced by `AI_MAX_TOKENS_PER_CALL`)  
**Timeout:** 10 seconds (`AI_TIMEOUT_SECONDS`)

**Response schema enforced by prompt:**

| Field | Type | Description |
|---|---|---|
| regime | enum | BULLISH / BEARISH / NEUTRAL / VOLATILE |
| regime_confidence | float 0-1 | Confidence level in regime classification |
| summary | string | 2-3 sentence market overview |
| key_themes | string[] | Up to 3 key market themes |
| sector_outlook | object | Per-sector bullish/bearish/neutral assessment |
| risks | string[] | Active market risks |
| opportunities | string[] | Trading opportunities |
| recommendation | string | Single actionable advice sentence |

**Response parsing:**

1. Strip whitespace from raw response.
2. Strip markdown code fences (` ```json ` block) if present.
3. `json.loads()` to parse.
4. On any exception: call `_fallback_insight(context)`.

**Fallback logic** (rule-based, no AI):

```
if ad_ratio > 1.5 AND sent_score > 0.1 AND above_200 > 60%:  regime = BULLISH
elif ad_ratio < 0.7 AND sent_score < -0.1 AND above_200 < 40%: regime = BEARISH
elif above_200 < 30%:                                           regime = VOLATILE
else:                                                           regime = NEUTRAL
regime_confidence = 0.5 (always for fallback)
```

**Stored in:** `ai_insights` table via raw SQL INSERT:

```sql
INSERT INTO ai_insights (insight_type, symbol, content, model_used, token_count)
VALUES ('MARKET_DAILY', 'MARKET', :content::jsonb, :model, 0)
```

- `insight_type` = `'MARKET_DAILY'`
- `symbol` = `'MARKET'`
- `content` = full insight JSON including `context` and `generated_at`
- `model_used` = `gpt-4.1-mini` (or `rule_based` on fallback)

---

## Stage 5: Frontend Presentation

**What the frontend shows** (`frontend/src/features/ai/ai-insights-view.tsx`):

| Component | Data |
|---|---|
| Regime badge | Color-coded pill: green=BULLISH, red=BEARISH, orange=VOLATILE, yellow=NEUTRAL |
| Confidence | Percentage display next to regime badge |
| Summary card | 2-3 sentence market overview in a bordered card |
| Recommendation card | Purple-accented card with actionable advice |
| Key Themes | Bulleted list in a bordered card |
| Opportunities | Bulleted list with green dot indicators |
| Risks | Bulleted list with red dot indicators |
| Generated timestamp | `new Date(generated_at).toLocaleString()` |

**Loading state:** "Loading AI insights..." text displayed during initial fetch.

**Empty state:** "No AI insights generated yet. Click 'Generate New' to create one." — shown when API returns `{"message": "no_insight_yet"}`.

**Generate button:** Calls `POST /api/v1/ai/market/generate` and immediately updates the displayed insight with the response. A spinning `RefreshCw` icon is shown during generation.

**Data retrieval:** `GET /api/v1/ai/market` returns the latest `ai_insights` row ordered by `generated_at DESC`.

**History:** `GET /api/v1/ai/market/history?limit=7` returns the 7 most recent insights (not yet surfaced on the frontend history tab).

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/v1/ai/market` | GET | Latest market insight |
| `GET /api/v1/ai/market/history` | GET | Last N insights (default 7, max 30) |
| `POST /api/v1/ai/market/generate` | POST | Generate fresh insight; persists to DB |
| `GET /api/v1/ai/strategy/{symbol}` | GET | Strategy recommendation per symbol |

---

## Graceful Degradation Summary

| Stage Failure | Downstream Impact |
|---|---|
| RSS feed unreachable | No new news; sentiment uses existing DB articles |
| Sentiment service error | `context["sentiment"]` absent; AI uses breadth only |
| Breadth service error | `context["breadth"]` absent; AI uses sentiment only |
| Option chain error | `context["nifty_options"]` absent; AI uses breadth + sentiment |
| Azure OpenAI timeout/error | Fallback rule-based insight persisted and served |
| DB persist failure | Insight returned to caller but not saved; next generate call repeats |

---

## Recommendations

1. **Surface insight history on the frontend.** The backend provides `GET /api/v1/ai/market/history` with up to 30 historical insights. A tabbed history view or timeline would allow users to compare regime assessments over time.

2. **Add sector_outlook visualization.** The AI prompt returns a `sector_outlook` object (e.g., `{"IT": "bullish", "Banking": "neutral"}`). This data is not currently rendered on the frontend.

3. **Schedule daily generation.** `POST /api/v1/ai/market/generate` is currently manual-only. A background scheduler (e.g., APScheduler) should trigger this once per day at market open.

4. **Track token usage.** The `token_count` field in `ai_insights` is currently hardcoded to `0`. Wire in `response.usage.total_tokens` from the Azure OpenAI response to enable budget tracking.

5. **Add `POST /api/v1/ai/news/analyze` implementation.** The endpoint is listed in the router docstring but not implemented in the router body. If news-level AI analysis is needed, implement the endpoint calling `NewsAnalystService.analyze()`.
