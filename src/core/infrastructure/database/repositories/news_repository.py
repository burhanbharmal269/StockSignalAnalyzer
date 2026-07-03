"""SQLAlchemy repository for news_events and sentiment_scores."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.news_event import NewsEvent


class SqlAlchemyNewsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def save(self, event: NewsEvent) -> int | None:
        """Insert news event, skip if content_hash already exists. Returns new id or None."""
        async with self._sf() as db:
            try:
                result = await db.execute(text("""
                    INSERT INTO news_events
                        (source, title, content, url, content_hash, published_at, symbols, categories)
                    VALUES
                        (:source, :title, :content, :url, :content_hash, :published_at,
                         CAST(:symbols AS jsonb), CAST(:categories AS jsonb))
                    ON CONFLICT (content_hash) DO NOTHING
                    RETURNING id
                """), {
                    "source": event.source,
                    "title": event.title,
                    "content": event.content,
                    "url": event.url,
                    "content_hash": event.content_hash,
                    "published_at": event.published_at,
                    "symbols": json.dumps(event.symbols),
                    "categories": json.dumps(event.categories),
                })
                await db.commit()
                row = result.fetchone()
                return row[0] if row else None
            except Exception:
                return None

    async def get_recent(
        self,
        limit: int = 50,
        symbol: str | None = None,
    ) -> list[NewsEvent]:
        if symbol:
            stmt = text("""
                SELECT id, source, title, content, url, content_hash,
                       published_at, symbols, categories, ingested_at
                FROM news_events
                WHERE symbols::text ILIKE :sym_pattern
                ORDER BY published_at DESC NULLS LAST
                LIMIT :lim
            """)
            params = {"sym_pattern": f"%{symbol}%", "lim": limit}
        else:
            stmt = text("""
                SELECT id, source, title, content, url, content_hash,
                       published_at, symbols, categories, ingested_at
                FROM news_events
                ORDER BY published_at DESC NULLS LAST
                LIMIT :lim
            """)
            params = {"lim": limit}

        async with self._sf() as db:
            result = await db.execute(stmt, params)
            return [_row_to_news(r) for r in result.mappings().fetchall()]


def _row_to_news(r) -> NewsEvent:
    def _parse(v):
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return []

    return NewsEvent(
        id=r["id"],
        source=r["source"],
        title=r["title"],
        content=r["content"] or "",
        url=r["url"] or "",
        content_hash=r["content_hash"],
        published_at=r["published_at"],
        symbols=_parse(r["symbols"]),
        categories=_parse(r["categories"]),
        ingested_at=r["ingested_at"],
    )
