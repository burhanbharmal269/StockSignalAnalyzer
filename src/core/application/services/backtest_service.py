"""BacktestService — event-driven historical strategy backtesting.

Walk-forward simulation: feeds candles one by one to the strategy,
tracks simulated trades, and computes performance metrics.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from core.domain.strategies.base_strategy import IStrategy, StrategySignal
    from core.infrastructure.database.repositories.historical_candle_repository import (
        SqlAlchemyHistoricalCandleRepository,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

_log = logging.getLogger(__name__)

_COMMISSION_PCT = Decimal("0.0003")   # 0.03% per side


class BacktestService:
    def __init__(
        self,
        candle_repo: SqlAlchemyHistoricalCandleRepository,
        session_factory,
    ) -> None:
        self._candles = candle_repo
        self._sf = session_factory

    async def run(
        self,
        strategy: IStrategy,
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
        initial_capital: Decimal = Decimal("100000"),
        risk_per_trade_pct: Decimal = Decimal("1"),    # 1% of capital per trade
        params: dict | None = None,
    ) -> dict:
        """Run walk-forward backtest. Returns run summary."""
        run_id = str(uuid.uuid4())
        _log.info("backtest.start run_id=%s strategy=%s symbol=%s", run_id, strategy.name, symbol)

        all_candles = await self._candles.get(symbol, timeframe, from_dt, to_dt)
        if len(all_candles) < strategy.min_candles_required + 10:
            return {"error": "insufficient_candles", "count": len(all_candles)}

        trades: list[dict] = []
        capital = initial_capital
        peak_capital = initial_capital
        max_drawdown = Decimal("0")
        open_trade: dict | None = None

        for i in range(strategy.min_candles_required, len(all_candles)):
            window = all_candles[:i + 1]
            current = all_candles[i]

            # Check if open trade has hit target or stop
            if open_trade:
                result = self._check_exit(open_trade, current)
                if result:
                    pnl = result["pnl"]
                    capital += pnl
                    open_trade["exit_price"] = result["exit_price"]
                    open_trade["exit_ts"] = current.ts
                    open_trade["pnl"] = float(pnl)
                    open_trade["exit_reason"] = result["reason"]
                    trades.append(open_trade)
                    open_trade = None

                    # Drawdown tracking
                    if capital > peak_capital:
                        peak_capital = capital
                    dd = (peak_capital - capital) / peak_capital * 100
                    if dd > max_drawdown:
                        max_drawdown = dd
                continue

            # Generate new signal
            try:
                signal = await strategy.generate_signal(symbol, window, params)
            except Exception as exc:
                _log.debug("strategy.error i=%d err=%s", i, exc)
                continue

            if signal is None:
                continue

            # Position sizing: risk 1% of capital
            risk_amount = capital * risk_per_trade_pct / 100
            price = signal.entry_price
            stop = signal.stop_loss
            risk_per_unit = abs(price - stop)
            if risk_per_unit == 0:
                continue

            qty = int(risk_amount / risk_per_unit)
            if qty == 0:
                continue

            commission = price * qty * _COMMISSION_PCT
            open_trade = {
                "run_id": run_id,
                "symbol": symbol,
                "direction": signal.direction,
                "entry_price": float(price),
                "entry_ts": current.ts,
                "stop_loss": float(signal.stop_loss),
                "target": float(signal.target),
                "qty": qty,
                "commission": float(commission),
                "strategy_name": strategy.name,
                "timeframe": timeframe,
                "confidence": float(signal.confidence),
                "pnl": 0,
                "exit_price": None,
                "exit_ts": None,
                "exit_reason": None,
            }

        # Close any remaining open trade at last price
        if open_trade:
            last = all_candles[-1]
            last_price = last.close
            pnl = self._calc_pnl(open_trade, last_price)
            open_trade["exit_price"] = float(last_price)
            open_trade["exit_ts"] = last.ts
            open_trade["pnl"] = float(pnl)
            open_trade["exit_reason"] = "EXPIRY"
            trades.append(open_trade)

        metrics = self._calculate_metrics(trades, initial_capital, capital, max_drawdown)
        await self._persist(run_id, strategy.name, symbol, timeframe, from_dt, to_dt,
                            initial_capital, capital, trades, metrics)

        return {
            "run_id": run_id,
            "strategy": strategy.name,
            "symbol": symbol,
            "timeframe": timeframe,
            "from_dt": from_dt.isoformat(),
            "to_dt": to_dt.isoformat(),
            "initial_capital": float(initial_capital),
            "final_capital": float(capital),
            "metrics": metrics,
            "trade_count": len(trades),
        }

    def _check_exit(self, trade: dict, candle) -> dict | None:
        direction = trade["direction"]
        target = Decimal(str(trade["target"]))
        stop = Decimal(str(trade["stop_loss"]))
        qty = trade["qty"]
        entry = Decimal(str(trade["entry_price"]))
        commission = Decimal(str(trade["commission"]))

        if direction == "LONG":
            if candle.high >= target:
                pnl = (target - entry) * qty - commission * 2
                return {"exit_price": target, "pnl": pnl, "reason": "TARGET"}
            if candle.low <= stop:
                pnl = (stop - entry) * qty - commission * 2
                return {"exit_price": stop, "pnl": pnl, "reason": "STOP"}
        else:
            if candle.low <= target:
                pnl = (entry - target) * qty - commission * 2
                return {"exit_price": target, "pnl": pnl, "reason": "TARGET"}
            if candle.high >= stop:
                pnl = (entry - stop) * qty - commission * 2
                return {"exit_price": stop, "pnl": pnl, "reason": "STOP"}

        return None

    def _calc_pnl(self, trade: dict, exit_price: Decimal) -> Decimal:
        entry = Decimal(str(trade["entry_price"]))
        qty = trade["qty"]
        commission = Decimal(str(trade["commission"]))
        if trade["direction"] == "LONG":
            return (exit_price - entry) * qty - commission * 2
        return (entry - exit_price) * qty - commission * 2

    def _calculate_metrics(
        self, trades: list[dict], initial: Decimal, final: Decimal, max_dd: Decimal
    ) -> dict:
        if not trades:
            return {"total_trades": 0, "win_rate": 0, "pnl": 0, "max_drawdown_pct": 0}

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in trades)
        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 1
        profit_factor = (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))
                         if losses and sum(t["pnl"] for t in losses) != 0 else 0)
        return_pct = float((final - initial) / initial * 100)

        return {
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 2),
            "total_pnl": round(total_pnl, 2),
            "return_pct": round(return_pct, 2),
            "max_drawdown_pct": round(float(max_dd), 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(avg_win * (len(wins) / len(trades)) - avg_loss * (len(losses) / len(trades)), 2),
        }

    async def _persist(
        self, run_id: str, strategy_name: str, symbol: str, timeframe: str,
        from_dt: datetime, to_dt: datetime, initial: Decimal, final: Decimal,
        trades: list[dict], metrics: dict,
    ) -> None:
        import json
        async with self._sf() as db:
            await db.execute(text("""
                INSERT INTO backtest_runs
                    (run_id, strategy_name, symbol, timeframe, from_dt, to_dt,
                     initial_capital, final_capital, status, params)
                VALUES
                    (:run_id, :strategy, :symbol, :tf, :from_dt, :to_dt,
                     :init, :final, 'COMPLETED', '{}'::jsonb)
                ON CONFLICT (run_id) DO NOTHING
            """), {
                "run_id": run_id, "strategy": strategy_name, "symbol": symbol,
                "tf": timeframe, "from_dt": from_dt, "to_dt": to_dt,
                "init": float(initial), "final": float(final),
            })

            for t in trades:
                try:
                    await db.execute(text("""
                        INSERT INTO backtest_trades
                            (run_id, symbol, direction, entry_price, entry_ts, exit_price,
                             exit_ts, qty, pnl, exit_reason, strategy_name, timeframe)
                        VALUES
                            (:run_id, :sym, :dir, :entry, :entry_ts, :exit, :exit_ts,
                             :qty, :pnl, :reason, :strategy, :tf)
                    """), {
                        "run_id": run_id, "sym": t["symbol"], "dir": t["direction"],
                        "entry": t["entry_price"], "entry_ts": t["entry_ts"],
                        "exit": t["exit_price"], "exit_ts": t["exit_ts"],
                        "qty": t["qty"], "pnl": t["pnl"], "reason": t["exit_reason"],
                        "strategy": t["strategy_name"], "tf": t["timeframe"],
                    })
                except Exception as exc:
                    _log.debug("backtest.trade.save err=%s", exc)

            await db.execute(text("""
                INSERT INTO backtest_metrics
                    (run_id, total_trades, winning_trades, losing_trades, win_rate,
                     total_pnl, return_pct, max_drawdown_pct, profit_factor,
                     avg_win, avg_loss, expectancy)
                VALUES
                    (:run_id, :total, :wins, :losses, :win_rate, :pnl, :ret,
                     :dd, :pf, :avg_win, :avg_loss, :exp)
                ON CONFLICT (run_id) DO UPDATE SET
                    total_trades=EXCLUDED.total_trades, win_rate=EXCLUDED.win_rate
            """), {
                "run_id": run_id,
                "total": metrics["total_trades"],
                "wins": metrics["winning_trades"],
                "losses": metrics["losing_trades"],
                "win_rate": metrics["win_rate"],
                "pnl": metrics["total_pnl"],
                "ret": metrics["return_pct"],
                "dd": metrics["max_drawdown_pct"],
                "pf": metrics["profit_factor"],
                "avg_win": metrics["avg_win"],
                "avg_loss": metrics["avg_loss"],
                "exp": metrics["expectancy"],
            })
            await db.commit()

    async def list_runs(self, limit: int = 20) -> list[dict]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT r.run_id, r.strategy_name, r.symbol, r.timeframe,
                       r.from_dt, r.to_dt, r.initial_capital, r.final_capital, r.status,
                       m.win_rate, m.total_pnl, m.return_pct, m.max_drawdown_pct,
                       m.profit_factor, m.total_trades
                FROM backtest_runs r
                LEFT JOIN backtest_metrics m ON r.run_id = m.run_id
                ORDER BY r.started_at DESC
                LIMIT :lim
            """), {"lim": limit})
            return [dict(r) for r in result.mappings().fetchall()]

    async def get_trades(self, run_id: str) -> list[dict]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT * FROM backtest_trades WHERE run_id = :rid ORDER BY entry_ts
            """), {"rid": run_id})
            return [dict(r) for r in result.mappings().fetchall()]
