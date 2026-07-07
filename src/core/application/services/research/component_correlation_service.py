"""ComponentCorrelationService — pairwise Pearson r between component scores.

Computes correlations between all 7 scoring components and each component
vs binary outcome (1=WIN, 0=LOSS). Read-only on signal_analytics.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_COMPONENTS = ["oi_score", "trend_score", "option_chain_score", "volume_score",
               "vwap_score", "sentiment_score", "iv_score"]

_COMP_LABELS = {
    "oi_score": "oi_buildup",
    "trend_score": "trend",
    "option_chain_score": "option_chain",
    "volume_score": "volume",
    "vwap_score": "vwap",
    "sentiment_score": "sentiment",
    "iv_score": "iv_analysis",
}


def _pearson(x: list[float], y: list[float]) -> tuple[float | None, float | None]:
    n = len(x)
    if n < 3:
        return None, None
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx == 0 or dy == 0:
        return None, None
    r = num / (dx * dy)
    r = max(-1.0, min(1.0, r))
    # Approximate p-value via t-statistic
    if abs(r) >= 1.0:
        p = 0.0
    else:
        t = r * math.sqrt(n - 2) / math.sqrt(1 - r ** 2)
        # Rough approximation
        p = round(1 - math.erf(abs(t) / math.sqrt(2)), 6)
    return round(r, 4), p


class ComponentCorrelationService:
    """Computes and persists pairwise component correlations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute_correlations(self, lookback_days: int = 90) -> dict:
        try:
            rows = await self._fetch(lookback_days)
            if not rows:
                return {"correlations": [], "computed": 0}

            # Build vectors
            vectors: dict[str, list[float]] = {c: [] for c in _COMPONENTS}
            outcomes: list[float] = []
            for row in rows:
                for i, col in enumerate(_COMPONENTS):
                    vectors[col].append(float(row[i] or 0.0))
                outcomes.append(1.0 if row[7] == "WIN" else 0.0)

            pairs: list[dict] = []
            # Component vs component
            cols = list(_COMPONENTS)
            for i in range(len(cols)):
                for j in range(i + 1, len(cols)):
                    r, p = _pearson(vectors[cols[i]], vectors[cols[j]])
                    pairs.append({
                        "component_a": _COMP_LABELS[cols[i]],
                        "component_b": _COMP_LABELS[cols[j]],
                        "pearson_r": r, "p_value": p,
                    })
                # Component vs outcome
                r, p = _pearson(vectors[cols[i]], outcomes)
                pairs.append({
                    "component_a": _COMP_LABELS[cols[i]],
                    "component_b": "outcome",
                    "pearson_r": r, "p_value": p,
                })

            await self._persist(lookback_days, pairs)
            return {"correlations": pairs, "computed": len(pairs)}
        except Exception as exc:
            _log.warning("component_correlation_service.compute_failed: %s", exc)
            return {"correlations": [], "computed": 0, "error": str(exc)}

    async def get_correlations(self, lookback_days: int = 90) -> list[dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT component_a, component_b, pearson_r, p_value, computed_at
                        FROM research_component_correlations
                        WHERE lookback_days = :days
                        ORDER BY computed_at DESC, ABS(pearson_r) DESC NULLS LAST
                        LIMIT 200
                    """),
                    {"days": lookback_days},
                )
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.warning("component_correlation_service.get_failed: %s", exc)
            return []

    async def _fetch(self, lookback_days: int) -> list[Any]:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT oi_score, trend_score, option_chain_score,
                           volume_score, vwap_score, sentiment_score, iv_score,
                           outcome
                    FROM signal_analytics
                    WHERE created_at > NOW() - :days * INTERVAL '1 day'
                      AND outcome IN ('WIN', 'LOSS')
                """),
                {"days": lookback_days},
            )
            return r.fetchall()

    async def _persist(self, lookback_days: int, pairs: list[dict]) -> None:
        async with self._sf() as db:
            for p in pairs:
                await db.execute(
                    text("""
                        INSERT INTO research_component_correlations
                            (lookback_days, component_a, component_b, pearson_r, p_value, computed_at)
                        VALUES (:days, :ca, :cb, :r, :p, NOW())
                    """),
                    {
                        "days": lookback_days,
                        "ca": p["component_a"], "cb": p["component_b"],
                        "r": p["pearson_r"], "p": p["p_value"],
                    },
                )
            await db.commit()
