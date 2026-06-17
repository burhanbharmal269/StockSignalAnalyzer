"""NewsAggregationService — ingests financial news from RSS feeds.

Sources: Economic Times, Moneycontrol, Business Standard, NSE, livemint.
All sources are public RSS feeds — no paid API required.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import httpx

from core.domain.entities.news_event import NewsEvent

if TYPE_CHECKING:
    from core.infrastructure.database.repositories.news_repository import SqlAlchemyNewsRepository

_log = logging.getLogger(__name__)

_RSS_FEEDS: list[dict] = [
    {
        "name": "economic_times_markets",
        "url": "https://economictimes.indiatimes.com/markets/rss.cms",
        "categories": ["markets"],
    },
    {
        "name": "economic_times_stocks",
        "url": "https://economictimes.indiatimes.com/markets/stocks/rss.cms",
        "categories": ["stocks"],
    },
    {
        "name": "moneycontrol_news",
        "url": "https://www.moneycontrol.com/rss/latestnews.xml",
        "categories": ["general"],
    },
    {
        "name": "business_standard",
        "url": "https://www.business-standard.com/rss/markets-106.rss",
        "categories": ["markets"],
    },
    {
        "name": "livemint_markets",
        "url": "https://www.livemint.com/rss/markets",
        "categories": ["markets"],
    },
    {
        "name": "nse_announcements",
        "url": "https://www.nseindia.com/feed/announcements.xml",
        "categories": ["corporate_action", "regulatory"],
    },
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StockSignalAnalyzer/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}

# Common NSE symbols to extract from news titles
_NIFTY50_SYMS = {
    "RELIANCE", "TCS", "HDFC", "INFY", "INFOSYS", "ICICI",
    "WIPRO", "HCL", "BAJAJ", "MARUTI", "TATA", "SBI", "BHARTI",
    "KOTAK", "AXIS", "ASIAN", "ITC", "LT", "ONGC", "NTPC",
}


class NewsAggregationService:
    def __init__(self, repository: SqlAlchemyNewsRepository) -> None:
        self._repo = repository
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=_HEADERS, timeout=15.0, follow_redirects=True
            )
        return self._client

    async def fetch_all(self) -> int:
        """Fetch all RSS feeds and persist new items. Returns count ingested."""
        total = 0
        for feed in _RSS_FEEDS:
            try:
                count = await self._fetch_feed(feed)
                total += count
            except Exception as exc:
                _log.warning("news.fetch_feed failed %s: %s", feed["name"], exc)
        return total

    async def get_recent(self, limit: int = 50, symbol: str | None = None) -> list[NewsEvent]:
        return await self._repo.get_recent(limit=limit, symbol=symbol)

    async def _fetch_feed(self, feed: dict) -> int:
        client = self._get_client()
        try:
            r = await client.get(feed["url"])
            r.raise_for_status()
            content = r.text
        except Exception as exc:
            _log.debug("rss.fetch failed %s: %s", feed["url"], exc)
            return 0

        items = self._parse_rss(content)
        count = 0
        for item in items:
            symbols = self._extract_symbols(item["title"] + " " + item.get("description", ""))
            event = NewsEvent(
                id=None,
                source=feed["name"],
                title=item["title"][:500],
                content=item.get("description", "")[:2000],
                url=item.get("link", ""),
                content_hash=hashlib.sha256(
                    (item["title"] + item.get("link", "")).encode()
                ).hexdigest(),
                published_at=item.get("pub_date"),
                symbols=symbols,
                categories=feed.get("categories", []),
            )
            result = await self._repo.save(event)
            if result:
                count += 1

        _log.debug("news.feed=%s ingested=%d", feed["name"], count)
        return count

    def _parse_rss(self, xml_text: str) -> list[dict]:
        """Simple XML parser — no lxml dependency required."""
        import xml.etree.ElementTree as ET
        items = []
        try:
            root = ET.fromstring(xml_text)
            ns = {}
            channel = root.find("channel") or root
            for item in channel.findall("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                pubdate_el = item.find("pubDate")

                title = (title_el.text or "").strip() if title_el is not None else ""
                if not title:
                    continue

                pub_date: datetime | None = None
                if pubdate_el is not None and pubdate_el.text:
                    try:
                        pub_date = parsedate_to_datetime(pubdate_el.text)
                    except Exception:
                        pub_date = datetime.now(UTC)

                items.append({
                    "title": title,
                    "link": (link_el.text or "").strip() if link_el is not None else "",
                    "description": (desc_el.text or "").strip() if desc_el is not None else "",
                    "pub_date": pub_date,
                })
        except ET.ParseError as exc:
            _log.debug("rss.parse_error: %s", exc)
        return items

    def _extract_symbols(self, text: str) -> list[str]:
        """Extract potential NSE symbols from news text (best-effort)."""
        found = []
        text_upper = text.upper()
        for sym in _NIFTY50_SYMS:
            if sym in text_upper:
                found.append(sym)
        return found[:10]

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
