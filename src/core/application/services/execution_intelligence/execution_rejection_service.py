"""ExecutionRejectionService — Phase 23 §7.

Categorizes and records order rejections. Categories:
  INSUFFICIENT_FUNDS, MARKET_CLOSED, PRICE_FREEZE, MARGIN_ISSUE,
  BROKER_ERROR, EXCHANGE_ERROR, VALIDATION_ERROR, API_FAILURE,
  NETWORK_FAILURE, UNKNOWN
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Rejection category classification rules (most-specific first)
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("INSUFFICIENT_FUNDS", ["insufficient funds", "not enough", "insufficient balance"]),
    ("MARGIN_ISSUE",       ["margin", "exposure limit", "span"]),
    ("MARKET_CLOSED",      ["market closed", "market is closed", "after hours", "pre-open"]),
    ("PRICE_FREEZE",       ["price freeze", "circuit", "frozen", "no price"]),
    ("VALIDATION_ERROR",   ["invalid", "validation", "order type", "quantity", "lot size", "wrong"]),
    ("API_FAILURE",        ["api error", "api failure", "http", "timeout", "503", "502", "401"]),
    ("NETWORK_FAILURE",    ["network", "connection", "unreachable", "socket", "connection refused"]),
    ("BROKER_ERROR",       ["broker", "kite", "order management"]),
    ("EXCHANGE_ERROR",     ["exchange", "nse", "bse"]),
]


def categorize(raw_reason: str | None) -> str:
    """Classify a raw rejection reason into a category."""
    if not raw_reason:
        return "UNKNOWN"
    lower = raw_reason.lower()
    for category, keywords in _CATEGORY_RULES:
        if any(kw in lower for kw in keywords):
            return category
    return "UNKNOWN"


class ExecutionRejectionService:
    """Records and categorizes order rejections. Fail-open."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record_rejection(
        self,
        *,
        signal_id: str | None = None,
        order_id: str | None = None,
        symbol: str | None = None,
        broker: str = "kite",
        rejected_by: str | None = None,
        raw_reason: str | None = None,
        regime: str | None = None,
    ) -> str:
        """Record a rejection and return the assigned category."""
        category = categorize(raw_reason)
        try:
            now = datetime.now(UTC)
            async with self._sf() as db:
                await db.execute(text("""
                    INSERT INTO execution_rejections
                        (signal_id, order_id, symbol, broker,
                         rejected_by, category, raw_reason,
                         regime, time_of_day, recorded_at)
                    VALUES
                        (:sid, :oid, :sym, :broker,
                         :rejected_by, :category, :raw_reason,
                         :regime, :time_of_day, NOW())
                """), {
                    "sid": signal_id, "oid": order_id, "sym": symbol, "broker": broker,
                    "rejected_by": rejected_by, "category": category,
                    "raw_reason": raw_reason, "regime": regime,
                    "time_of_day": now.time(),
                })
                await db.commit()
            _log.info(
                "execution_rejection category=%s signal=%s symbol=%s reason=%s",
                category, signal_id or "?", symbol or "?", raw_reason or "?",
            )
        except Exception as exc:
            _log.warning("execution_rejection.record_failed: %s", exc)
        return category

    async def get_stats(self, hours: int = 24) -> dict[str, Any]:
        """Breakdown of rejections by category."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT category, rejected_by, COUNT(*) AS cnt
                    FROM execution_rejections
                    WHERE recorded_at > NOW() - :hrs * INTERVAL '1 hour'
                    GROUP BY category, rejected_by
                    ORDER BY cnt DESC
                """), {"hrs": hours})
                rows = [dict(row) for row in r.mappings().fetchall()]

                r2 = await db.execute(text("""
                    SELECT COUNT(*) AS total
                    FROM execution_rejections
                    WHERE recorded_at > NOW() - :hrs * INTERVAL '1 hour'
                """), {"hrs": hours})
                total = (r2.scalar() or 0)

            return {"hours": hours, "total": total, "breakdown": rows}
        except Exception as exc:
            _log.debug("execution_rejection.get_stats_failed: %s", exc)
            return {"error": str(exc)}

    async def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Most recent rejections with category + raw reason."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT signal_id, order_id, symbol, category, rejected_by,
                           raw_reason, recorded_at
                    FROM execution_rejections
                    ORDER BY recorded_at DESC
                    LIMIT :lim
                """), {"lim": limit})
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.debug("execution_rejection.get_recent_failed: %s", exc)
            return []
