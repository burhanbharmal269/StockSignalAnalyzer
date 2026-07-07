"""FeatureImportanceService — ranks scoring components by predictive power.

Uses point-biserial correlation (component score vs WIN/LOSS outcome)
to compute an importance score for each of the 7 components. Updates
the in-memory FeatureRegistry with the computed scores.
"""

from __future__ import annotations

import logging
import math
from typing import Any, TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from core.application.services.feature_registry import FeatureRegistry

_log = logging.getLogger(__name__)

_COMPONENT_MAP = {
    "oi_buildup": "oi_score",
    "trend": "trend_score",
    "option_chain": "option_chain_score",
    "volume": "volume_score",
    "vwap": "vwap_score",
    "sentiment": "sentiment_score",
    "iv_analysis": "iv_score",
}


def _point_biserial(continuous: list[float], binary: list[float]) -> float | None:
    """Compute |r_pb| — correlation of continuous score with binary outcome."""
    n = len(continuous)
    if n < 5:
        return None
    n1 = sum(binary)
    n0 = n - n1
    if n1 == 0 or n0 == 0:
        return None
    m1 = sum(c for c, b in zip(continuous, binary) if b == 1) / n1
    m0 = sum(c for c, b in zip(continuous, binary) if b == 0) / n0
    mean_all = sum(continuous) / n
    var_all = sum((c - mean_all) ** 2 for c in continuous) / n
    std_all = math.sqrt(var_all)
    if std_all == 0:
        return None
    r = (m1 - m0) / std_all * math.sqrt(n1 * n0 / n ** 2)
    return round(abs(r), 4)


class FeatureImportanceService:
    """Computes and persists feature importance scores."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        feature_registry: "FeatureRegistry | None" = None,
    ) -> None:
        self._sf = session_factory
        self._registry = feature_registry

    async def compute_importance(self, lookback_days: int = 90) -> list[dict]:
        try:
            rows = await self._fetch(lookback_days)
            if not rows:
                return []

            results: list[dict] = []
            for comp, col in _COMPONENT_MAP.items():
                col_idx = list(_COMPONENT_MAP.values()).index(col)
                scores = [float(row[col_idx] or 0.0) for row in rows]
                outcomes = [1.0 if row[7] == "WIN" else 0.0 for row in rows]
                importance = _point_biserial(scores, outcomes)
                results.append({"component": comp, "importance_score": importance})

            # Rank by importance
            results.sort(key=lambda x: x["importance_score"] or 0.0, reverse=True)
            for rank, item in enumerate(results, start=1):
                item["rank"] = rank

            await self._persist(lookback_days, results)

            # Update in-memory registry
            if self._registry:
                for item in results:
                    try:
                        self._registry.update_predictive_power(
                            item["component"], item["importance_score"] or 0.0
                        )
                    except Exception:
                        pass

            return results
        except Exception as exc:
            _log.warning("feature_importance_service.compute_failed: %s", exc)
            return []

    async def get_importance(self) -> list[dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT DISTINCT ON (component) component, importance_score, rank, lookback_days, computed_at
                        FROM research_feature_importance
                        ORDER BY component, computed_at DESC
                    """)
                )
                return sorted(
                    [dict(row) for row in r.mappings().fetchall()],
                    key=lambda x: x.get("rank") or 99,
                )
        except Exception as exc:
            _log.warning("feature_importance_service.get_failed: %s", exc)
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

    async def _persist(self, lookback_days: int, results: list[dict]) -> None:
        async with self._sf() as db:
            for item in results:
                await db.execute(
                    text("""
                        INSERT INTO research_feature_importance
                            (lookback_days, component, importance_score, rank, computed_at)
                        VALUES (:days, :comp, :score, :rank, NOW())
                    """),
                    {
                        "days": lookback_days,
                        "comp": item["component"],
                        "score": item.get("importance_score"),
                        "rank": item.get("rank"),
                    },
                )
            await db.commit()
