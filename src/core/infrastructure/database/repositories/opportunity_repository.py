"""SQLAlchemy repository for market_opportunities and backtest tables."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.market_opportunity import MarketOpportunity
from core.domain.entities.backtest_result import BacktestRun, BacktestTrade, BacktestMetrics


class SqlAlchemyOpportunityRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def save(self, opp: MarketOpportunity) -> None:
        async with self._sf() as db:
            await db.execute(text("""
                INSERT INTO market_opportunities
                    (symbol, opportunity_type, technical_score, volume_score,
                     sentiment_score, oi_score, regime_score, total_score,
                     confidence, direction, regime, meta, expires_at)
                VALUES
                    (:symbol, :opp_type, :tech, :vol, :sent, :oi, :reg,
                     :total, :conf, :dir, :regime, :meta::jsonb, :expires_at)
            """), {
                "symbol": opp.symbol, "opp_type": opp.opportunity_type,
                "tech": float(opp.technical_score or 0),
                "vol": float(opp.volume_score or 0),
                "sent": float(opp.sentiment_score or 0),
                "oi": float(opp.oi_score or 0),
                "reg": float(opp.regime_score or 0),
                "total": float(opp.total_score),
                "conf": float(opp.confidence),
                "dir": opp.direction, "regime": opp.regime,
                "meta": json.dumps(opp.meta),
                "expires_at": opp.expires_at,
            })
            await db.commit()

    async def get_top(self, limit: int = 20, min_score: float = 0) -> list[MarketOpportunity]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT id, symbol, opportunity_type, technical_score, volume_score,
                       sentiment_score, oi_score, regime_score, total_score,
                       confidence, direction, regime, meta, created_at, expires_at
                FROM market_opportunities
                WHERE total_score >= :min_score
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY total_score DESC, created_at DESC
                LIMIT :lim
            """), {"min_score": min_score, "lim": limit})
            return [_row_to_opp(r) for r in result.mappings().fetchall()]


def _row_to_opp(r) -> MarketOpportunity:
    def _d(v): return Decimal(str(v)) if v is not None else None
    meta = r["meta"] or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return MarketOpportunity(
        id=r["id"], symbol=r["symbol"],
        opportunity_type=r["opportunity_type"],
        total_score=_d(r["total_score"]),
        confidence=_d(r["confidence"]),
        direction=r["direction"],
        technical_score=_d(r["technical_score"]),
        volume_score=_d(r["volume_score"]),
        sentiment_score=_d(r["sentiment_score"]),
        oi_score=_d(r["oi_score"]),
        regime_score=_d(r["regime_score"]),
        regime=r["regime"], meta=meta,
        created_at=r["created_at"], expires_at=r["expires_at"],
    )


class SqlAlchemyBacktestRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def save_run(self, run: BacktestRun) -> None:
        async with self._sf() as db:
            await db.execute(text("""
                INSERT INTO backtest_runs
                    (run_id, strategy_name, params, symbols, timeframe,
                     start_date, end_date, status, error_message, completed_at)
                VALUES
                    (:run_id, :strategy, :params::jsonb, :symbols::jsonb,
                     :timeframe, :start_date, :end_date, :status, :error, :completed_at)
                ON CONFLICT (run_id) DO UPDATE SET
                    status=EXCLUDED.status, error_message=EXCLUDED.error_message,
                    completed_at=EXCLUDED.completed_at
            """), {
                "run_id": run.run_id, "strategy": run.strategy_name,
                "params": json.dumps(run.params),
                "symbols": json.dumps(run.symbols),
                "timeframe": run.timeframe,
                "start_date": run.start_date, "end_date": run.end_date,
                "status": run.status, "error": run.error_message,
                "completed_at": run.completed_at,
            })
            await db.commit()

    async def save_trades(self, trades: list[BacktestTrade]) -> None:
        if not trades:
            return
        async with self._sf() as db:
            for t in trades:
                await db.execute(text("""
                    INSERT INTO backtest_trades
                        (run_id, symbol, direction, entry_at, entry_price,
                         stop_loss, target, exit_at, exit_price, quantity,
                         pnl, pnl_pct, exit_reason, strategy_name)
                    VALUES
                        (:run_id, :symbol, :direction, :entry_at, :entry_price,
                         :stop_loss, :target, :exit_at, :exit_price, :qty,
                         :pnl, :pnl_pct, :exit_reason, :strategy)
                """), {
                    "run_id": t.run_id, "symbol": t.symbol,
                    "direction": t.direction,
                    "entry_at": t.entry_at,
                    "entry_price": float(t.entry_price),
                    "stop_loss": float(t.stop_loss) if t.stop_loss else None,
                    "target": float(t.target) if t.target else None,
                    "exit_at": t.exit_at,
                    "exit_price": float(t.exit_price) if t.exit_price else None,
                    "qty": t.quantity,
                    "pnl": float(t.pnl) if t.pnl else None,
                    "pnl_pct": float(t.pnl_pct) if t.pnl_pct else None,
                    "exit_reason": t.exit_reason,
                    "strategy": t.strategy_name,
                })
            await db.commit()

    async def save_metrics(self, metrics: BacktestMetrics) -> None:
        async with self._sf() as db:
            await db.execute(text("""
                INSERT INTO backtest_metrics
                    (run_id, total_trades, winning_trades, losing_trades,
                     win_rate, total_pnl, avg_profit, avg_loss, profit_factor,
                     expectancy, max_drawdown_pct, sharpe_ratio, sortino_ratio,
                     cagr, avg_trade_duration_mins)
                VALUES
                    (:run_id, :total, :wins, :losses, :win_rate, :total_pnl,
                     :avg_profit, :avg_loss, :pf, :exp, :mdd, :sharpe,
                     :sortino, :cagr, :avg_dur)
                ON CONFLICT (run_id) DO UPDATE SET
                    total_trades=EXCLUDED.total_trades,
                    winning_trades=EXCLUDED.winning_trades,
                    win_rate=EXCLUDED.win_rate,
                    total_pnl=EXCLUDED.total_pnl,
                    sharpe_ratio=EXCLUDED.sharpe_ratio,
                    max_drawdown_pct=EXCLUDED.max_drawdown_pct
            """), {
                "run_id": metrics.run_id,
                "total": metrics.total_trades,
                "wins": metrics.winning_trades,
                "losses": metrics.losing_trades,
                "win_rate": float(metrics.win_rate or 0),
                "total_pnl": float(metrics.total_pnl or 0),
                "avg_profit": float(metrics.avg_profit or 0),
                "avg_loss": float(metrics.avg_loss or 0),
                "pf": float(metrics.profit_factor or 0),
                "exp": float(metrics.expectancy or 0),
                "mdd": float(metrics.max_drawdown_pct or 0),
                "sharpe": float(metrics.sharpe_ratio or 0),
                "sortino": float(metrics.sortino_ratio or 0),
                "cagr": float(metrics.cagr or 0),
                "avg_dur": float(metrics.avg_trade_duration_mins or 0),
            })
            await db.commit()

    async def list_runs(self, limit: int = 20) -> list[dict]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT r.run_id, r.strategy_name, r.timeframe,
                       r.start_date, r.end_date, r.status, r.created_at,
                       m.total_trades, m.win_rate, m.total_pnl,
                       m.sharpe_ratio, m.max_drawdown_pct
                FROM backtest_runs r
                LEFT JOIN backtest_metrics m ON m.run_id = r.run_id
                ORDER BY r.created_at DESC
                LIMIT :lim
            """), {"lim": limit})
            return [dict(r) for r in result.mappings().fetchall()]

    async def get_run(self, run_id: str) -> dict | None:
        async with self._sf() as db:
            result = await db.execute(
                text("SELECT * FROM backtest_runs WHERE run_id=:id"),
                {"id": run_id},
            )
            row = result.mappings().fetchone()
            return dict(row) if row else None
