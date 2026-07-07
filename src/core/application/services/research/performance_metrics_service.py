"""PerformanceMetricsService — computes Sharpe, Sortino, Calmar, etc.

Reads signal_analytics outcomes to compute performance metrics for a
strategy version. Supports offline re-weighting: component scores are
already stored per signal and can be re-weighted without re-running
the live engine.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Component columns in signal_analytics mapped to their max_score (V1 weights)
_COMPONENT_COLS = {
    "oi_buildup": ("oi_score", 25),
    "trend": ("trend_score", 20),
    "option_chain": ("option_chain_score", 20),
    "volume": ("volume_score", 15),
    "vwap": ("vwap_score", 10),
    "sentiment": ("sentiment_score", 5),
    "iv_analysis": ("iv_score", 5),
}

_ANNUAL_FACTOR = 252.0  # trading days


def _sharpe(returns: list[float], risk_free: float = 0.0) -> float | None:
    if len(returns) < 2:
        return None
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return round((mean - risk_free) / std * math.sqrt(_ANNUAL_FACTOR), 4)


def _sortino(returns: list[float], risk_free: float = 0.0) -> float | None:
    if len(returns) < 2:
        return None
    n = len(returns)
    mean = sum(returns) / n
    neg = [r for r in returns if r < 0]
    if not neg:
        return None
    downside_var = sum(r ** 2 for r in neg) / n
    downside_std = math.sqrt(downside_var)
    if downside_std == 0:
        return None
    return round((mean - risk_free) / downside_std * math.sqrt(_ANNUAL_FACTOR), 4)


def _max_drawdown(cumulative: list[float]) -> float | None:
    if not cumulative:
        return None
    peak = cumulative[0]
    max_dd = 0.0
    for v in cumulative:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return round(max_dd * 100, 4)


def _calmar(annual_return: float, max_dd_pct: float) -> float | None:
    if max_dd_pct == 0:
        return None
    return round(annual_return / (max_dd_pct / 100), 4)


def _profit_factor(returns: list[float]) -> float | None:
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r < 0))
    if gross_loss == 0:
        return None
    return round(gross_profit / gross_loss, 4)


def compute_metrics(returns: list[float]) -> dict[str, Any]:
    """Compute all performance metrics from a list of per-trade returns (%)."""
    if not returns:
        return {
            "sharpe": None, "sortino": None, "calmar": None,
            "max_drawdown_pct": None, "win_rate": None,
            "profit_factor": None, "avg_trade_pnl": None, "trade_count": 0,
        }
    n = len(returns)
    wins = sum(1 for r in returns if r > 0)
    win_rate = round(wins / n * 100, 2)
    avg_pnl = round(sum(returns) / n, 4)

    cumulative = []
    running = 1.0
    for r in returns:
        running *= (1 + r / 100)
        cumulative.append(running)

    max_dd = _max_drawdown(cumulative)
    total_return = (cumulative[-1] - 1) * 100 if cumulative else 0.0
    ann_return = total_return  # simplified: treat as annualised

    sh = _sharpe(returns)
    so = _sortino(returns)
    ca = _calmar(ann_return, max_dd or 0.0) if max_dd is not None else None
    pf = _profit_factor(returns)

    return {
        "sharpe": sh,
        "sortino": so,
        "calmar": ca,
        "max_drawdown_pct": max_dd,
        "win_rate": win_rate,
        "profit_factor": pf,
        "avg_trade_pnl": avg_pnl,
        "trade_count": n,
    }


class PerformanceMetricsService:
    """Compute and persist performance metrics for a research strategy version."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute_for_version(
        self,
        version_id: str,
        lookback_days: int = 252,
        new_weights: dict | None = None,
    ) -> dict:
        """Compute metrics using historical signal_analytics outcomes.

        If new_weights is provided, signals are re-scored offline using the
        stored component scores multiplied by the new weights.
        """
        try:
            rows = await self._fetch_outcomes(lookback_days, new_weights)
            metrics = compute_metrics(rows)
            await self._persist(version_id, lookback_days, metrics)
            return metrics
        except Exception as exc:
            _log.warning("performance_metrics_service.compute_failed: %s", exc)
            return {}

    async def compare_versions(
        self, version_ids: list[str], lookback_days: int = 252
    ) -> list[dict]:
        results = []
        for vid in version_ids:
            m = await self.compute_for_version(vid, lookback_days)
            results.append({"version_id": vid, **m})
        return results

    async def get_latest(self, version_id: str) -> dict | None:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT * FROM research_performance_snapshots
                        WHERE version_id = :vid
                        ORDER BY computed_at DESC LIMIT 1
                    """),
                    {"vid": version_id},
                )
                row = r.mappings().fetchone()
                return dict(row) if row else None
        except Exception as exc:
            _log.warning("performance_metrics_service.get_latest_failed: %s", exc)
            return None

    # ── Private ───────────────────────────────────────────────────────────────

    async def _fetch_outcomes(
        self, lookback_days: int, new_weights: dict | None
    ) -> list[float]:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT mfe_pct, mae_pct, outcome,
                           oi_score, trend_score, option_chain_score,
                           volume_score, vwap_score, sentiment_score, iv_score
                    FROM signal_analytics
                    WHERE created_at > NOW() - :days * INTERVAL '1 day'
                      AND outcome IN ('WIN', 'LOSS')
                    ORDER BY created_at
                """),
                {"days": lookback_days},
            )
            rows = r.fetchall()

        returns = []
        for row in rows:
            if new_weights:
                score = _reweight(row, new_weights)
                # Use MFE as proxy return for wins, MAE for losses under reweighted filter
                pnl = float(row[0] or 0.0) if row[2] == "WIN" else -abs(float(row[1] or 0.0))
                # Only include signal if reweighted score passes the threshold
                if score >= 60:
                    returns.append(pnl)
            else:
                pnl = float(row[0] or 0.0) if row[2] == "WIN" else -abs(float(row[1] or 0.0))
                returns.append(pnl)
        return returns

    async def _persist(self, version_id: str, lookback_days: int, m: dict) -> None:
        try:
            async with self._sf() as db:
                await db.execute(
                    text("""
                        INSERT INTO research_performance_snapshots
                            (version_id, lookback_days, sharpe, sortino, calmar,
                             max_drawdown_pct, win_rate, profit_factor,
                             avg_trade_pnl, trade_count, computed_at)
                        VALUES
                            (:vid, :days, :sharpe, :sortino, :calmar,
                             :mdd, :wr, :pf, :avg, :cnt, NOW())
                    """),
                    {
                        "vid": version_id, "days": lookback_days,
                        "sharpe": m.get("sharpe"), "sortino": m.get("sortino"),
                        "calmar": m.get("calmar"), "mdd": m.get("max_drawdown_pct"),
                        "wr": m.get("win_rate"), "pf": m.get("profit_factor"),
                        "avg": m.get("avg_trade_pnl"), "cnt": m.get("trade_count"),
                    },
                )
                await db.commit()
        except Exception as exc:
            _log.warning("performance_metrics_service.persist_failed: %s", exc)


def _reweight(row: Any, new_weights: dict) -> float:
    """Re-score a signal_analytics row using new component weights."""
    mapping = {
        "oi_buildup": 3, "trend": 4, "option_chain": 5,
        "volume": 6, "vwap": 7, "sentiment": 8, "iv_analysis": 9,
    }
    total = 0.0
    for comp, col_idx in mapping.items():
        raw_score = float(row[col_idx] or 0.0)
        orig_max = _COMPONENT_COLS[comp][1]
        new_max = new_weights.get(comp, {}).get("max_score", orig_max) if isinstance(
            new_weights.get(comp), dict
        ) else float(new_weights.get(comp, orig_max))
        # Normalise: raw_score was already out of orig_max, re-scale to new_max
        if orig_max > 0:
            total += (raw_score / orig_max) * new_max
    return total
