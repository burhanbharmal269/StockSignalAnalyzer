"""WalkForwardAnalyzerService — rolling walk-forward analysis on signal_analytics.

Uses a 60/20/20 in-sample / validation / OOS split on historical signals.
For each window: finds weights that maximise validation Sharpe (from a
fixed search space), then evaluates on the OOS holdout. All computation
is read-only on signal_analytics.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.research.performance_metrics_service import (
    compute_metrics,
    _reweight,
)

_log = logging.getLogger(__name__)

# Fixed weight search space for in-sample optimisation (lightweight)
_WEIGHT_CANDIDATES = [
    {"oi_buildup": 25, "trend": 20, "option_chain": 20, "volume": 15, "vwap": 10, "sentiment": 5, "iv_analysis": 5},
    {"oi_buildup": 30, "trend": 20, "option_chain": 15, "volume": 15, "vwap": 10, "sentiment": 5, "iv_analysis": 5},
    {"oi_buildup": 20, "trend": 25, "option_chain": 20, "volume": 15, "vwap": 10, "sentiment": 5, "iv_analysis": 5},
    {"oi_buildup": 25, "trend": 20, "option_chain": 20, "volume": 20, "vwap": 5, "sentiment": 5, "iv_analysis": 5},
    {"oi_buildup": 25, "trend": 15, "option_chain": 25, "volume": 15, "vwap": 10, "sentiment": 5, "iv_analysis": 5},
]


class WalkForwardAnalyzerService:
    """Walk-forward analysis using stored signal_analytics rows."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def start_run(
        self,
        version_id: str,
        from_dt: datetime,
        to_dt: datetime,
        n_windows: int = 5,
    ) -> str:
        run_id = str(uuid.uuid4())
        async with self._sf() as db:
            await db.execute(
                text("""
                    INSERT INTO research_runs
                        (id, version_id, run_type, status, params, started_at, created_at)
                    VALUES
                        (:id, :vid, 'WALK_FORWARD', 'RUNNING',
                         CAST(:params AS jsonb), NOW(), NOW())
                """),
                {
                    "id": run_id, "vid": version_id,
                    "params": json.dumps({
                        "from": from_dt.isoformat(),
                        "to": to_dt.isoformat(),
                        "n_windows": n_windows,
                    }),
                },
            )
            await db.commit()

        await self._run_windows(run_id, from_dt, to_dt, n_windows)
        return run_id

    async def get_windows(self, run_id: str) -> list[dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT * FROM research_walk_forward_windows
                        WHERE run_id = :rid ORDER BY window_idx
                    """),
                    {"rid": run_id},
                )
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.warning("walk_forward_analyzer_service.get_windows_failed: %s", exc)
            return []

    async def get_aggregate_oos_stats(self, run_id: str) -> dict:
        windows = await self.get_windows(run_id)
        oos_sharpes = [w["oos_sharpe"] for w in windows if w.get("oos_sharpe") is not None]
        oos_win_rates = [w["oos_win_rate"] for w in windows if w.get("oos_win_rate") is not None]
        oos_trades = [w["oos_trade_count"] for w in windows if w.get("oos_trade_count") is not None]

        if not oos_sharpes:
            return {"window_count": len(windows), "oos_sharpe_mean": None, "t_stat": None, "p_value": None}

        n = len(oos_sharpes)
        mean = sum(oos_sharpes) / n
        variance = sum((s - mean) ** 2 for s in oos_sharpes) / n if n > 1 else 0.0
        std = math.sqrt(variance)
        t_stat = (mean / (std / math.sqrt(n))) if std > 0 and n > 1 else None
        # Simple one-sample t-test p-value approximation
        p_value = None
        if t_stat is not None:
            # Very rough approximation: p ≈ 2*(1-Φ(|t|)) for large n
            try:
                from math import erf
                p_value = round(1 - erf(abs(t_stat) / math.sqrt(2)), 4)
            except Exception:
                pass

        return {
            "window_count": n,
            "oos_sharpe_mean": round(mean, 4),
            "oos_sharpe_std": round(std, 4),
            "oos_win_rate_mean": round(sum(oos_win_rates) / len(oos_win_rates), 2) if oos_win_rates else None,
            "total_oos_trades": sum(oos_trades) if oos_trades else None,
            "t_stat": round(t_stat, 4) if t_stat else None,
            "p_value": p_value,
        }

    # ── Private ───────────────────────────────────────────────────────────────

    async def _run_windows(
        self,
        run_id: str,
        from_dt: datetime,
        to_dt: datetime,
        n_windows: int,
    ) -> None:
        try:
            total_days = (to_dt.date() - from_dt.date()).days
            # Step size: advance test window each iteration
            step_days = max(10, total_days // (n_windows + 2))
            train_pct = 0.60
            val_pct = 0.20

            all_rows = await self._fetch_rows(from_dt, to_dt)

            for i in range(n_windows):
                window_start = from_dt.date() + timedelta(days=i * step_days)
                window_end_days = min(total_days, (i + 1) * step_days + int(total_days * 0.4))
                window_end = from_dt.date() + timedelta(days=window_end_days)

                span_days = (window_end - window_start).days
                train_days = int(span_days * train_pct)
                val_days = int(span_days * val_pct)

                train_from = window_start
                train_to = window_start + timedelta(days=train_days)
                val_from = train_to
                val_to = val_from + timedelta(days=val_days)
                test_from = val_to
                test_to = window_end

                def in_window(row: Any, start: date, end: date) -> bool:
                    try:
                        d = row[-1]  # created_at is last column
                        if hasattr(d, "date"):
                            d = d.date()
                        return start <= d < end
                    except Exception:
                        return False

                train_rows = [r for r in all_rows if in_window(r, train_from, train_to)]
                val_rows = [r for r in all_rows if in_window(r, val_from, val_to)]
                test_rows = [r for r in all_rows if in_window(r, test_from, test_to)]

                # Find best weights on training set (measured on validation)
                best_val_sharpe = float("-inf")
                best_params: dict = _WEIGHT_CANDIDATES[0]
                for wc in _WEIGHT_CANDIDATES:
                    val_returns = _rows_to_returns(val_rows, wc)
                    m = compute_metrics(val_returns)
                    sh = m.get("sharpe") or float("-inf")
                    if sh > best_val_sharpe:
                        best_val_sharpe = sh
                        best_params = wc

                # Evaluate on OOS
                oos_returns = _rows_to_returns(test_rows, best_params)
                is_returns = _rows_to_returns(train_rows, best_params)
                oos_m = compute_metrics(oos_returns)
                is_m = compute_metrics(is_returns)

                async with self._sf() as db:
                    await db.execute(
                        text("""
                            INSERT INTO research_walk_forward_windows
                                (run_id, window_idx,
                                 train_from, train_to, validate_from, validate_to,
                                 test_from, test_to,
                                 is_sharpe, oos_sharpe, oos_win_rate, oos_trade_count,
                                 oos_pnl, best_params, created_at)
                            VALUES
                                (:rid, :idx,
                                 :tf, :tt, :vf, :vt, :sf2, :st,
                                 :is_sh, :oos_sh, :oos_wr, :oos_cnt,
                                 :oos_pnl, CAST(:bp AS jsonb), NOW())
                        """),
                        {
                            "rid": run_id, "idx": i,
                            "tf": train_from, "tt": train_to,
                            "vf": val_from, "vt": val_to,
                            "sf2": test_from, "st": test_to,
                            "is_sh": is_m.get("sharpe"),
                            "oos_sh": oos_m.get("sharpe"),
                            "oos_wr": oos_m.get("win_rate"),
                            "oos_cnt": oos_m.get("trade_count"),
                            "oos_pnl": sum(oos_returns) if oos_returns else None,
                            "bp": json.dumps(best_params),
                        },
                    )
                    await db.commit()

            async with self._sf() as db:
                await db.execute(
                    text("UPDATE research_runs SET status='COMPLETED', completed_at=NOW() WHERE id=:id"),
                    {"id": run_id},
                )
                await db.commit()

        except Exception as exc:
            _log.warning("walk_forward_analyzer_service.run_failed: %s", exc)
            async with self._sf() as db:
                await db.execute(
                    text("UPDATE research_runs SET status='FAILED', error_message=:err WHERE id=:id"),
                    {"err": str(exc), "id": run_id},
                )
                await db.commit()

    async def _fetch_rows(self, from_dt: datetime, to_dt: datetime) -> list[Any]:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT mfe_pct, mae_pct, outcome,
                           oi_score, trend_score, option_chain_score,
                           volume_score, vwap_score, sentiment_score, iv_score,
                           created_at
                    FROM signal_analytics
                    WHERE created_at BETWEEN :from_dt AND :to_dt
                      AND outcome IN ('WIN', 'LOSS')
                    ORDER BY created_at
                """),
                {"from_dt": from_dt, "to_dt": to_dt},
            )
            return r.fetchall()


def _rows_to_returns(rows: list[Any], weights: dict) -> list[float]:
    returns = []
    for row in rows:
        score = _reweight(row, weights)
        if score >= 60:
            pnl = float(row[0] or 0.0) if row[2] == "WIN" else -abs(float(row[1] or 0.0))
            returns.append(pnl)
    return returns
