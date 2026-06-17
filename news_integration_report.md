# News Integration Report
**Project:** StockSignalAnalyzer  
**Date:** 2026-06-16  
**Service:** NewsAggregationService (RSS-based)  
**File:** `src/core/application/services/news_aggregation_service.py`

---

## Executive Summary

The news integration does **not** use the NewsAPI.ai paid service. Instead, `NewsAggregationService` ingests financial news from six public RSS feeds: Economic Times Markets, Economic Times Stocks, Moneycontrol, Business Standard, Livemint, and NSE Announcements. `NEWSAPI_AI_KEY` is absent from `.env` and is not referenced in the codebase — this is intentional. The `POST /api/v1/news/refresh` endpoint is fully functional using RSS only. Deduplication is implemented via SHA-256 content hashes. Symbol extraction is keyword-based against a Nifty 50 symbol list. Sentiment scoring is handled separately by `SentimentService`. The overall news pipeline is operational with no missing dependencies.

---

## 1. API Key Status

| Variable | Status | Impact |
|---|---|---|
| NEWSAPI_AI_KEY | **MISSING from .env** | **None** — the codebase does not import or call NewsAPI.ai. All news ingestion uses free public RSS feeds. |

The absence of `NEWSAPI_AI_KEY` does **not** cause a 503 error on `POST /api/v1/news/refresh`. The service will return `{"fetched": N}` where N is the number of new items ingested from RSS. If all feeds fail due to network unavailability, it returns `{"fetched": 0}`.

---

## 2. RSS Feed Sources

Six feeds are configured in `_RSS_FEEDS` (lines 24-55):

| Feed Name | URL | Categories |
|---|---|---|
| economic_times_markets | `https://economictimes.indiatimes.com/markets/rss.cms` | markets |
| economic_times_stocks | `https://economictimes.indiatimes.com/markets/stocks/rss.cms` | stocks |
| moneycontrol_news | `https://www.moneycontrol.com/rss/latestnews.xml` | general |
| business_standard | `https://www.business-standard.com/rss/markets-106.rss` | markets |
| livemint_markets | `https://www.livemint.com/rss/markets` | markets |
| nse_announcements | `https://www.nseindia.com/feed/announcements.xml` | corporate_action, regulatory |

All feeds use a browser-like `User-Agent` header (`Mozilla/5.0 (compatible; StockSignalAnalyzer/1.0)`) and a 15-second HTTP timeout with redirect following via `httpx.AsyncClient`.

---

## 3. News Ingestion Flow

The flow triggered by `POST /api/v1/news/refresh` → `news_svc.fetch_all()`:

```
fetch_all()
  for each feed in _RSS_FEEDS:
    _fetch_feed(feed)
      httpx.AsyncClient.get(feed["url"])  → raw XML
      _parse_rss(xml_text)                → list of {title, link, description, pub_date}
      for each item:
        _extract_symbols(title + description)  → list of NSE symbols
        construct NewsEvent(
          source, title[:500], content[:2000], url,
          content_hash, published_at, symbols, categories
        )
        repo.save(event)   → INSERT or skip if hash exists
  return total count ingested
```

**Field truncation:**
- `title` is capped at 500 characters.
- `content` (description) is capped at 2,000 characters.
- `symbols` list is capped at 10 symbols per article.

---

## 4. Deduplication (content_hash)

Deduplication is implemented using a SHA-256 hash computed over the article's title concatenated with its URL (line 116-119):

```python
content_hash = hashlib.sha256(
    (item["title"] + item.get("link", "")).encode()
).hexdigest()
```

The repository's `save()` method performs an upsert or duplicate-check against the `news_events` table's `content_hash` column. If an article with the same hash already exists, `save()` returns `None` (or a falsy value) and the item is not counted. This prevents duplicate ingestion when the same RSS feed is polled multiple times.

**Trade-off:** The hash is based on title + URL only (not body content). An article with the same URL that has its body updated post-publication will not be re-ingested.

---

## 5. Retry and Failure Handling

The service uses a per-feed exception catch strategy:

- **Feed-level failure:** If `_fetch_feed()` raises any exception (network error, DNS failure, HTTP error), the exception is caught at `fetch_all()` (line 88-91), a `WARNING` log is emitted (`news.fetch_feed failed {name}: {exc}`), and processing continues with the next feed. A single feed failure does not abort the entire refresh.
- **HTTP errors:** `r.raise_for_status()` is called (line 100); non-2xx responses are caught by the outer exception handler.
- **XML parse errors:** `ET.ParseError` is caught in `_parse_rss()` (line 162); the feed returns an empty list without aborting.
- **Individual item errors:** Not explicitly caught; a malformed item that raises an exception during symbol extraction or `NewsEvent` construction would propagate up to the feed-level handler.
- **No retry backoff:** The current implementation does not retry failed feeds within a single `fetch_all()` call. Retry behavior relies on the caller scheduling periodic `fetch_all()` invocations (e.g., via a background scheduler).

---

## 6. Sentiment Scoring

Sentiment is handled by a separate `SentimentService` (not part of `NewsAggregationService`). It is accessible via:

- `GET /api/v1/news/sentiment/market` → `SentimentService.get_market_sentiment()`
- `GET /api/v1/news/sentiment/{symbol}` → `SentimentService.get_symbol_sentiment(symbol, hours=24)`

Sentiment scores are pre-computed and stored alongside news events. The `MarketOverviewView` frontend page displays overall market sentiment (avg_score, direction, bullish/bearish/neutral article counts).

---

## 7. Category Mapping

Categories are assigned per feed source (not per article). The mapping is:

| Source | Category Tags |
|---|---|
| economic_times_markets | markets |
| economic_times_stocks | stocks |
| moneycontrol_news | general |
| business_standard | markets |
| livemint_markets | markets |
| nse_announcements | corporate_action, regulatory |

Articles from NSE Announcements are automatically tagged `corporate_action` and `regulatory`, making them filterable for event-driven strategies.

---

## 8. Storage in news_events Table

Each ingested `NewsEvent` entity contains:

| Field | Source |
|---|---|
| id | Auto-generated (None at creation, set by DB) |
| source | Feed name (e.g., `economic_times_markets`) |
| title | Article title, max 500 chars |
| content | Article description/body, max 2000 chars |
| url | Article link |
| content_hash | SHA-256(title + url) |
| published_at | Parsed from RSS `pubDate` (RFC 2822); falls back to UTC now on parse failure |
| symbols | List of matched NSE symbols, max 10 |
| categories | List of category tags from feed config |

The `GET /api/v1/news` endpoint retrieves recent events via `news_svc.get_recent(limit, symbol)`. The `limit` parameter accepts 1–200 (default 50). Filtering by `symbol` passes the symbol to the repository for a column or JSON-array query on `symbols`.

---

## 9. Symbol Mapping

Symbol extraction is implemented in `_extract_symbols()` (line 165). It uses a static set `_NIFTY50_SYMS` of 20 common NSE symbols (line 63-67):

```
RELIANCE, TCS, HDFC, INFY, INFOSYS, ICICI, WIPRO, HCL, BAJAJ, MARUTI,
TATA, SBI, BHARTI, KOTAK, AXIS, ASIAN, ITC, LT, ONGC, NTPC
```

The algorithm uppercases the combined title + description text and checks for each symbol as a substring. All matches are returned, up to 10.

**Limitations:**
- The symbol set contains only 20 entries versus a full Nifty 50 or broader universe. Many midcap and smallcap stocks will not be matched.
- Substring matching can produce false positives (e.g., "ITC" matching within "NOTICE").
- Partial company name matching (e.g., "TATA" matching Tata Motors, Tata Steel, Tata Consultancy) is ambiguous.

**Recommendation:** Expand `_NIFTY50_SYMS` to the full trading universe and use word-boundary matching to reduce false positives.

---

## 10. API Endpoints Summary

| Endpoint | Method | Handler | Notes |
|---|---|---|---|
| `/api/v1/news` | GET | `get_news()` | Returns recent news; filter by symbol; limit 1-200 |
| `/api/v1/news/sentiment/market` | GET | `get_market_sentiment()` | Overall market sentiment object |
| `/api/v1/news/sentiment/{symbol}` | GET | `get_symbol_sentiment()` | Per-symbol sentiment; hours param 1-168 |
| `/api/v1/news/refresh` | POST | `refresh_news()` | Triggers `fetch_all()`; returns `{"fetched": N}` |

---

## Recommendations

1. **Expand symbol list:** The 20-symbol `_NIFTY50_SYMS` set covers roughly 40% of a typical Nifty 50 screen. Expand it to the full configured trading universe and use word-boundary or regex matching.

2. **Add per-item retry:** Consider wrapping the `repo.save()` call in a try/except to prevent a single DB error from silently dropping an entire feed's worth of articles.

3. **Schedule periodic refresh:** The `POST /api/v1/news/refresh` endpoint is manual. A background scheduler should call `fetch_all()` every 15–30 minutes during market hours.

4. **Document NEWSAPI_AI_KEY intent:** If NewsAPI.ai integration is planned for a future phase, add a commented-out `# NEWSAPI_AI_KEY=` placeholder in `.env` with a note explaining when it will be used.
