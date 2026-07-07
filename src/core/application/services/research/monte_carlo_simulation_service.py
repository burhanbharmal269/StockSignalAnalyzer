"""MonteCarloSimulationService — bootstrap resampling of historical trade outcomes.

Resamples signal_analytics WIN/LOSS outcomes with replacement to build a
distribution of portfolio-level statistics (terminal PnL, max drawdown,
Sharpe). 1000+ simulations per run. All computation is read-only.
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.research.performance_metrics_service import (
    compute_metrics,
    _max_drawdown,
)

_log = logging.getLogger(__name__)
_BATCH_SIZE = 100


class MonteCarloSimulationService:
    """Bootstrap Monte Carlo simulation over historical signal outcomes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def start_simulation(
        self,
        version_id: str,
        n_sims: int = 1000,
        lookback_days: int = 252,
        seed: int | None = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        mc_id = str(uuid.uuid4())

        async with self._sf() as db:
            await db.execute(
                text("""
                    INSERT INTO research_runs
                        (id, version_id, run_type, status, params, started_at, created_at)
                    VALUES
                        (:id, :vid, 'MONTE_CARLO', 'RUNNING', :params::jsonb, NOW(), NOW())
                """),
                {
                    "id": run_id, "vid": version_id,
                    "params": json.dumps({"n_sims": n_sims, "lookback_days": lookback_days, "seed": seed}),
                },
            )
            await db.commit()

        await self._run_simulations(run_id, mc_id, n_sims, lookback_days, seed)
        return run_id

    async def get_results(self, run_id: str) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("SELECT * FROM research_monte_carlo_runs WHERE run_id = :rid"),
                    {"rid": run_id},
                )
                mc_row = r.mappings().fetchone()

                r2 = await db.execute(
                    text("""
                        SELECT terminal_pnl, max_drawdown_pct, sharpe
                        FROM research_monte_carlo_results
                        WHERE run_id = :rid
                        ORDER BY sim_idx
                    """),
                    {"rid": run_id},
                )
                detail = [dict(row) for row in r2.mappings().fetchall()]

            summary = dict(mc_row) if mc_row else {}
            return {"summary": summary, "simulations": detail}
        except Exception as exc:
            _log.warning("monte_carlo_simulation_service.get_results_failed: %s", exc)
            return {"summary": {}, "simulations": []}

    # ── Private ───────────────────────────────────────────────────────────────

    async def _run_simulations(
        self,
        run_id: str,
        mc_id: str,
        n_sims: int,
        lookback_days: int,
        seed: int | None,
    ) -> None:
        try:
            base_returns = await self._fetch_returns(lookback_days)
            if not base_returns:
                raise ValueError("No historical outcomes found — cannot simulate")

            rng = random.Random(seed)
            terminal_pnls: list[float] = []
            all_rows: list[dict] = []

            for sim_idx in range(n_sims):
                # Bootstrap: sample with replacement
                sampled = rng.choices(base_returns, k=len(base_returns))
                m = compute_metrics(sampled)

                cumulative: list[float] = []
                running = 1.0
                for r in sampled:
                    running *= (1 + r / 100)
                    cumulative.append(running)

                terminal_pnl = (cumulative[-1] - 1.0) * 100 if cumulative else 0.0
                terminal_pnls.append(terminal_pnl)
                all_rows.append({
                    "run_id": run_id,
                    "sim_idx": sim_idx,
                    "terminal_pnl": terminal_pnl,
                    "max_drawdown_pct": m.get("max_drawdown_pct"),
                    "sharpe": m.get("sharpe"),
                    "win_rate": m.get("win_rate"),
                })

                # Flush in batches
                if len(all_rows) >= _BATCH_SIZE:
                    await self._persist_results(all_rows)
                    all_rows = []

            if all_rows:
                await self._persist_results(all_rows)

            # Compute percentile summary
            sorted_pnls = sorted(terminal_pnls)
            n = len(sorted_pnls)

            def pctile(p: float) -> float:
                idx = max(0, min(n - 1, int(p / 100 * n)))
                return sorted_pnls[idx]

            prob_positive = sum(1 for p in terminal_pnls if p > 0) / n if n else 0.0

            async with self._sf() as db:
                await db.execute(
                    text("""
                        INSERT INTO research_monte_carlo_runs
                            (id, run_id, n_sims, seed, lookback_days,
                             percentile_5, percentile_25, percentile_50,
                             percentile_75, percentile_95, prob_positive, created_at)
                        VALUES
                            (:id, :rid, :n, :seed, :days,
                             :p5, :p25, :p50, :p75, :p95, :prob, NOW())
                    """),
                    {
                        "id": mc_id, "rid": run_id, "n": n_sims,
                        "seed": seed, "days": lookback_days,
                        "p5": pctile(5), "p25": pctile(25),
                        "p50": pctile(50), "p75": pctile(75),
                        "p95": pctile(95), "prob": round(prob_positive, 4),
                    },
                )
                await db.execute(
                    text("UPDATE research_runs SET status='COMPLETED', completed_at=NOW() WHERE id=:id"),
                    {"id": run_id},
                )
                await db.commit()

        except Exception as exc:
            _log.warning("monte_carlo_simulation_service.run_failed: %s", exc)
            async with self._sf() as db:
                await db.execute(
                    text("UPDATE research_runs SET status='FAILED', error_message=:err WHERE id=:id"),
                    {"err": str(exc), "id": run_id},
                )
                await db.commit()

    async def _persist_results(self, rows: list[dict]) -> None:
        async with self._sf() as db:
            for row in rows:
                await db.execute(
                    text("""
                        INSERT INTO research_monte_carlo_results
                            (run_id, sim_idx, terminal_pnl, max_drawdown_pct, sharpe, win_rate)
                        VALUES
                            (:rid, :idx, :pnl, :mdd, :sh, :wr)
                    """),
                    {
                        "rid": row["run_id"], "idx": row["sim_idx"],
                        "pnl": row.get("terminal_pnl"), "mdd": row.get("max_drawdown_pct"),
                        "sh": row.get("sharpe"), "wr": row.get("win_rate"),
                    },
                )
            await db.commit()

    async def _fetch_returns(self, lookback_days: int) -> list[float]:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT mfe_pct, mae_pct, outcome
                    FROM signal_analytics
                    WHERE created_at > NOW() - :days * INTERVAL '1 day'
                      AND outcome IN ('WIN', 'LOSS')
                """),
                {"days": lookback_days},
            )
            rows = r.fetchall()

        return [
            float(row[0] or 0.0) if row[2] == "WIN" else -abs(float(row[1] or 0.0))
            for row in rows
        ]
