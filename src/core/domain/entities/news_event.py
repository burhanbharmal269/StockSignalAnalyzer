"""NewsEvent — a financial news article ingested from any source."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsEvent:
    id: int | None
    source: str
    title: str
    content: str
    url: str
    content_hash: str
    published_at: datetime | None
    symbols: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    ingested_at: datetime | None = None
