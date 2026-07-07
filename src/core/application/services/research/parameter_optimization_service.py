"""ParameterOptimizationService — grid search over strategy weights/thresholds.

Iterates combinations of scoring component weights and signal thresholds,
re-scores historical signal_analytics rows offline, and evaluates each
combination using a chosen metric (Sharpe by default).

All computation is read-only on signal_analytics — production scoring
is never modified.
"""

from __future__ import annotations

import itertools
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.research.performance_metrics_service import (
    compute_metrics,
    _reweight,
)

_log = logging.getLogger(__name__)

_MAX_COMBOS = 500


class ParameterOptimizationService:
    """Grid search over strategy parameters using historical signal_analytics."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def start_grid_search(
        self,
        version_id: str,
        param_grid: dict,
        metric: str = "sharpe",
        lookback_days: int = 252,
    ) -> str:
        run_id = str(uuid.uuid4())
        opt_id = str(uuid.uuid4())

        combos = list(_build_combos(param_grid))[:_MAX_COMBOS]

        async with self._sf() as db:
            await db.execute(
                text("""
                    INSERT INTO research_runs
                        (id, version_id, run_type, status, params, started_at, created_at)
                    VALUES
                        (:id, :vid, 'GRID_SEARCH', 'RUNNING', CAST(:params AS jsonb), NOW(), NOW())
                """),
                {"id": run_id, "vid": version_id, "params": json.dumps({"metric": metric, "lookback_days": lookback_days})},
            )
            await db.execute(
                text("""
                    INSERT INTO research_optimization_runs
                        (id, run_id, param_grid, metric, lookback_days, combos_total, created_at)
                    VALUES
                        (:id, :run_id, CAST(:grid AS jsonb), :metric, :days, :total, NOW())
                """),
                {
                    "id": opt_id, "run_id": run_id,
                    "grid": json.dumps(param_grid),
                    "metric": metric, "days": lookback_days, "total": len(combos),
                },
            )
            await db.commit()

        # Run evaluation
        await self._run_combos(run_id, opt_id, combos, metric, lookback_days)
        return run_id

    async def get_run_status(self, run_id: str) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("SELECT * FROM research_runs WHERE id = :id"),
                    {"id": run_id},
                )
                row = r.mappings().fetchone()
                return dict(row) if row else {}
        except Exception as exc:
            _log.warning("parameter_optimization_service.get_status_failed: %s", exc)
            return {}

    async def get_results(
        self, run_id: str, limit: int = 100, sort_by: str = "sharpe"
    ) -> list[dict]:
        safe_sort = sort_by if sort_by in {"sharpe", "sortino", "calmar", "win_rate"} else "sharpe"
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text(f"""
                        SELECT * FROM research_optimization_results
                        WHERE run_id = :rid
                        ORDER BY {safe_sort} DESC NULLS LAST
                        LIMIT :lim
                    """),
                    {"rid": run_id, "lim": limit},
                )
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.warning("parameter_optimization_service.get_results_failed: %s", exc)
            return []

    async def get_best_params(self, run_id: str) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT best_params FROM research_optimization_runs
                        WHERE run_id = :rid
                    """),
                    {"rid": run_id},
                )
                row = r.fetchone()
                return row[0] if row and row[0] else {}
        except Exception as exc:
            _log.warning("parameter_optimization_service.get_best_failed: %s", exc)
            return {}

    # ── Private ───────────────────────────────────────────────────────────────

    async def _run_combos(
        self,
        run_id: str,
        opt_id: str,
        combos: list[dict],
        metric: str,
        lookback_days: int,
    ) -> None:
        try:
            rows = await self._fetch_signal_rows(lookback_days)
            best_value = float("-inf")
            best_params: dict = {}

            for i, params in enumerate(combos):
                new_weights = {k: v for k, v in params.items() if k in {
                    "oi_buildup", "trend", "option_chain", "volume", "vwap", "sentiment", "iv_analysis"
                }}
                min_score = params.get("min_score", 60)

                trade_returns = []
                for row in rows:
                    score = _reweight(row, new_weights) if new_weights else float(row[3] or 0)
                    if score >= min_score:
                        pnl = float(row[0] or 0.0) if row[2] == "WIN" else -abs(float(row[1] or 0.0))
                        trade_returns.append(pnl)

                m = compute_metrics(trade_returns)
                metric_val = m.get(metric)

                async with self._sf() as db:
                    await db.execute(
                        text("""
                            INSERT INTO research_optimization_results
                                (run_id, params, sharpe, sortino, calmar,
                                 max_drawdown_pct, win_rate, profit_factor,
                                 trade_count, avg_trade_pnl, created_at)
                            VALUES
                                (:rid, CAST(:params AS jsonb), :sh, :so, :ca,
                                 :mdd, :wr, :pf, :cnt, :avg, NOW())
                        """),
                        {
                            "rid": run_id, "params": json.dumps(params),
                            "sh": m.get("sharpe"), "so": m.get("sortino"),
                            "ca": m.get("calmar"), "mdd": m.get("max_drawdown_pct"),
                            "wr": m.get("win_rate"), "pf": m.get("profit_factor"),
                            "cnt": m.get("trade_count"), "avg": m.get("avg_trade_pnl"),
                        },
                    )
                    await db.execute(
                        text("""
                            UPDATE research_optimization_runs
                            SET combos_completed = :done
                            WHERE run_id = :rid
                        """),
                        {"done": i + 1, "rid": run_id},
                    )
                    await db.commit()

                if metric_val is not None and metric_val > best_value:
                    best_value = metric_val
                    best_params = params

            # Finalise
            async with self._sf() as db:
                await db.execute(
                    text("""
                        UPDATE research_optimization_runs
                        SET best_params = CAST(:bp AS jsonb), best_metric_value = :bv
                        WHERE run_id = :rid
                    """),
                    {"bp": json.dumps(best_params), "bv": best_value if best_params else None, "rid": run_id},
                )
                await db.execute(
                    text("""
                        UPDATE research_runs
                        SET status = 'COMPLETED', completed_at = NOW()
                        WHERE id = :id
                    """),
                    {"id": run_id},
                )
                await db.commit()

        except Exception as exc:
            _log.warning("parameter_optimization_service.run_combos_failed: %s", exc)
            async with self._sf() as db:
                await db.execute(
                    text("UPDATE research_runs SET status='FAILED', error_message=:err WHERE id=:id"),
                    {"err": str(exc), "id": run_id},
                )
                await db.commit()

    async def _fetch_signal_rows(self, lookback_days: int) -> list[Any]:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT mfe_pct, mae_pct, outcome,
                           raw_score,
                           oi_score, trend_score, option_chain_score,
                           volume_score, vwap_score, sentiment_score, iv_score
                    FROM signal_analytics
                    WHERE created_at > NOW() - :days * INTERVAL '1 day'
                      AND outcome IN ('WIN', 'LOSS')
                """),
                {"days": lookback_days},
            )
            return r.fetchall()


def _build_combos(param_grid: dict) -> list[dict]:
    """Generate all parameter combinations from a grid dict."""
    keys = list(param_grid.keys())
    values = [param_grid[k] if isinstance(param_grid[k], list) else [param_grid[k]] for k in keys]
    for combo in itertools.product(*values):
        yield dict(zip(keys, combo))
