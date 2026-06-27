"""ResearchCubeService — Phase 23 §4.

Multi-dimensional research cube.  Accepts up to 3 dimensions and optional
dimension-level filters, returns aggregate performance statistics per cell.

Example query:
    cube.query(["score_bucket", "regime", "instrument_type"])

    → [
        {"score_bucket": "75-79", "regime": "TRENDING_BULLISH",
         "instrument_type": "NIFTY", "trade_count": 34, "win_rate": 62.5, ...},
        ...
      ]
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.cohort_engine_service import _BASE_WHERE, _DIM_SQL, _STATS_SQL

_log = logging.getLogger(__name__)

_MAX_DIMENSIONS = 3


class ResearchCubeService:
    """Parameterized multi-dimensional GROUP BY over signal_analytics."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def query(
        self,
        dimensions: list[str],
        filters: dict[str, list[str]] | None = None,
        min_trades: int = 5,
        days_back: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run a multi-dimensional research cube query.

        Args:
            dimensions: 1–3 dimension names from cohort_engine_service._DIM_SQL
            filters:    optional {dimension: [allowed_values]} to restrict cells
            min_trades: minimum completed trades to include a cell
            days_back:  limit to last N calendar days

        Returns:
            List of dicts, one per cube cell, ordered by profit_factor DESC.
        """
        if not dimensions:
            raise ValueError("At least one dimension required")
        if len(dimensions) > _MAX_DIMENSIONS:
            raise ValueError(f"Maximum {_MAX_DIMENSIONS} dimensions per query")

        unknown = [d for d in dimensions if d not in _DIM_SQL]
        if unknown:
            raise ValueError(f"Unknown dimensions: {unknown}")

        # Build SELECT aliases for each dimension
        select_parts: list[str] = []
        group_parts:  list[str] = []
        for i, dim in enumerate(dimensions):
            alias = f"dim_{i}"
            expr  = _DIM_SQL[dim].strip()
            select_parts.append(f"({expr}) AS {alias}")
            group_parts.append(str(i + 1))   # GROUP BY ordinal

        select_clause = ",\n".join(select_parts)
        group_clause  = ", ".join(group_parts)

        extra_where = ""
        params: dict[str, Any] = {"min_trades": min_trades}

        if days_back:
            extra_where += f" AND created_at >= NOW() - INTERVAL '{int(days_back)} days'"

        # Dimension-level value filters (applied via HAVING-equivalent post-grouping
        # or via sub-WHERE on raw column — simpler to do in application layer)

        sql = f"""
            SELECT
                {select_clause},
                {_STATS_SQL}
            FROM signal_analytics
            {_BASE_WHERE}
            {extra_where}
            GROUP BY {group_clause}
            HAVING COUNT(*) >= :min_trades
            ORDER BY profit_factor DESC NULLS LAST
            LIMIT 500
        """

        try:
            async with self._sf() as db:
                r = await db.execute(text(sql), params)
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("research_cube.query failed dims=%s: %s", dimensions, exc, exc_info=True)
            return []

        results: list[dict[str, Any]] = []
        for row in rows:
            cell: dict[str, Any] = {}
            for i, dim in enumerate(dimensions):
                cell[dim] = getattr(row, f"dim_{i}", None)
            cell.update({
                "trade_count":    int(row.trade_count or 0),
                "win_rate":       float(row.win_rate or 0),
                "profit_factor":  float(row.profit_factor) if row.profit_factor is not None else None,
                "expectancy":     float(row.expectancy)    if row.expectancy     is not None else None,
                "sharpe":         float(row.sharpe)        if row.sharpe         is not None else None,
                "sortino":        float(row.sortino)       if row.sortino        is not None else None,
                "avg_mfe":        float(row.avg_mfe)       if row.avg_mfe        is not None else None,
                "avg_mae":        float(row.avg_mae)       if row.avg_mae        is not None else None,
                "avg_score":      float(row.avg_score or 0),
                "avg_confidence": float(row.avg_confidence or 0),
            })
            results.append(cell)

        # Apply optional value filters in-process
        if filters:
            results = [
                row for row in results
                if all(
                    row.get(dim) in allowed
                    for dim, allowed in filters.items()
                    if allowed
                )
            ]

        return results

    async def get_available_dimensions(self) -> list[str]:
        """Return all supported dimension names."""
        return list(_DIM_SQL.keys())
