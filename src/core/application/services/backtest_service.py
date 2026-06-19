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
_SLIPPAGE_PCT   = Decimal("0.0005")   # 0.05% per side (NSE options typical mid-spread)


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
        slippage_pct: Decimal = _SLIPPAGE_PCT,
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

            commission = price * qty * (_COMMISSION_PCT + slippage_pct)
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

    async def run_walk_forward(
        self,
        strategy: "IStrategy",
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
        train_days: int = 60,
        test_days: int = 20,
        initial_capital: Decimal = Decimal("100000"),
        risk_per_trade_pct: Decimal = Decimal("1"),
        slippage_pct: Decimal = _SLIPPAGE_PCT,
        params: dict | None = None,
    ) -> dict:
        """Rolling walk-forward test.

        Splits the date range into overlapping train/test windows:
          Window 1: train=[from_dt, from_dt+train_days), test=[from_dt+train_days, +test_days)
          Window 2: train=[from_dt+test_days, ...), test=[..., +test_days)  (rolling by test_days)

        The strategy is evaluated on the TEST portion only using all candles up to
        the test window start as context (no lookahead). Metrics are aggregated across
        windows to produce out-of-sample statistics.

        Returns summary dict with per-window results and aggregate OOS metrics.
        """
        from datetime import timedelta

        all_candles = await self._candles.get(symbol, timeframe, from_dt, to_dt)
        if len(all_candles) < strategy.min_candles_required + 10:
            return {"error": "insufficient_candles", "count": len(all_candles)}

        # Build a timestamp index so we can slice by date
        candle_dates = []
        for c in all_candles:
            ts = getattr(c, "ts", None) or getattr(c, "date", None) or getattr(c, "timestamp", None)
            candle_dates.append(ts)

        windows: list[dict] = []
        cursor = from_dt + timedelta(days=train_days)

        while cursor + timedelta(days=test_days) <= to_dt:
            test_end = cursor + timedelta(days=test_days)

            # All candles up to test window end (context + test candles)
            context_end_idx = next(
                (i for i, ts in enumerate(candle_dates) if ts is not None and ts >= cursor),
                len(all_candles),
            )
            full_window = all_candles[:next(
                (i for i, ts in enumerate(candle_dates) if ts is not None and ts >= test_end),
                len(all_candles),
            )]

            # Run strategy only on the test portion (candles from context_end_idx onward)
            trades: list[dict] = []
            capital    = initial_capital
            peak_cap   = initial_capital
            max_dd     = Decimal("0")
            open_trade = None

            for i in range(context_end_idx, len(full_window)):
                window_slice = full_window[:i + 1]
                current = full_window[i]

                if open_trade:
                    result = self._check_exit(open_trade, current)
                    if result:
                        pnl = result["pnl"]
                        capital += pnl
                        open_trade["exit_price"] = result["exit_price"]
                        open_trade["exit_ts"]    = current.ts if hasattr(current, "ts") else None
                        open_trade["pnl"]        = float(pnl)
                        open_trade["exit_reason"] = result["reason"]
                        trades.append(open_trade)
                        open_trade = None
                        if capital > peak_cap:
                            peak_cap = capital
                        dd = (peak_cap - capital) / peak_cap * 100
                        if dd > max_dd:
                            max_dd = dd
                    continue

                try:
                    signal = await strategy.generate_signal(symbol, window_slice, params)
                except Exception:
                    continue

                if signal is None:
                    continue

                risk_amount  = capital * risk_per_trade_pct / 100
                price        = signal.entry_price
                stop         = signal.stop_loss
                risk_per_unit = abs(price - stop)
                if risk_per_unit == 0:
                    continue

                qty = int(risk_amount / risk_per_unit)
                if qty == 0:
                    continue

                commission = price * qty * (_COMMISSION_PCT + slippage_pct)
                open_trade = {
                    "symbol": symbol, "direction": signal.direction,
                    "entry_price": float(price), "entry_ts": current.ts if hasattr(current, "ts") else None,
                    "stop_loss": float(signal.stop_loss), "target": float(signal.target),
                    "qty": qty, "commission": float(commission),
                    "pnl": 0, "exit_price": None, "exit_ts": None, "exit_reason": None,
                }

            if open_trade:
                last = full_window[-1]
                pnl  = self._calc_pnl(open_trade, last.close)
                open_trade["pnl"]        = float(pnl)
                open_trade["exit_price"] = float(last.close)
                open_trade["exit_ts"]    = last.ts if hasattr(last, "ts") else None
                open_trade["exit_reason"] = "EXPIRY"
                trades.append(open_trade)

            metrics = self._calculate_metrics(trades, initial_capital, capital, max_dd)
            windows.append({
                "train_start": (cursor - timedelta(days=train_days)).isoformat(),
                "train_end":   cursor.isoformat(),
                "test_start":  cursor.isoformat(),
                "test_end":    test_end.isoformat(),
                "trades":      len(trades),
                "win_rate":    metrics.get("win_rate", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
                "profit_factor": metrics.get("profit_factor", 0),
                "return_pct":  metrics.get("return_pct", 0),
            })

            cursor += timedelta(days=test_days)

        if not windows:
            return {"error": "no_windows_generated", "reason": "date_range_too_short"}

        # Aggregate OOS statistics across all windows
        n = len(windows)
        oos_win_rates    = [w["win_rate"]    for w in windows if w["trades"] > 0]
        oos_sharpes      = [w["sharpe_ratio"] for w in windows if w["trades"] > 0]
        oos_drawdowns    = [w["max_drawdown_pct"] for w in windows]
        oos_pfs          = [w["profit_factor"] for w in windows if w["trades"] > 0]

        def _mean(vals: list) -> float:
            return round(sum(vals) / len(vals), 3) if vals else 0.0

        def _stdev(vals: list) -> float:
            import math
            if len(vals) < 2:
                return 0.0
            m = sum(vals) / len(vals)
            return round(math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)), 3)

        return {
            "symbol":       symbol,
            "timeframe":    timeframe,
            "strategy":     strategy.name,
            "windows_count": n,
            "train_days":   train_days,
            "test_days":    test_days,
            "oos_win_rate_mean":   _mean(oos_win_rates),
            "oos_win_rate_stdev":  _stdev(oos_win_rates),
            "oos_sharpe_mean":     _mean(oos_sharpes),
            "oos_max_drawdown_mean": _mean(oos_drawdowns),
            "oos_profit_factor_mean": _mean(oos_pfs),
            "oos_consistent":  all(w > 50 for w in oos_win_rates),
            "windows": windows,
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
        import math
        if not trades:
            return {"total_trades": 0, "win_rate": 0, "pnl": 0, "max_drawdown_pct": 0}

        wins   = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in trades)
        avg_win   = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0
        avg_loss  = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 1
        gross_win  = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_win / gross_loss if gross_loss > 0 else 0.0
        return_pct    = float((final - initial) / initial * 100)
        win_rate      = len(wins) / len(trades)

        # Per-trade returns as % of notional entry for Sharpe/Sortino
        returns = [t["pnl"] / (t["entry_price"] * t["qty"]) * 100
                   if t["entry_price"] and t["qty"] else 0.0 for t in trades]

        # Sharpe ratio (annualised, assuming 252 trading days, ~4 trades/day max)
        if len(returns) >= 2:
            mean_r = sum(returns) / len(returns)
            var_r  = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
            std_r  = math.sqrt(var_r) if var_r > 0 else 0.0
            # Annualise: sqrt of (252 * bars_per_day / avg_hold_bars)
            sharpe = (mean_r / std_r * math.sqrt(len(returns))) if std_r > 0 else 0.0
        else:
            sharpe = 0.0

        # Sortino ratio — only downside deviation
        neg_returns = [r for r in returns if r < 0]
        if len(neg_returns) >= 2:
            mean_r    = sum(returns) / len(returns)
            down_var  = sum(r ** 2 for r in neg_returns) / len(neg_returns)
            down_std  = math.sqrt(down_var) if down_var > 0 else 0.0
            sortino   = (mean_r / down_std * math.sqrt(len(returns))) if down_std > 0 else 0.0
        else:
            sortino = 0.0

        # Consecutive win/loss streaks
        max_consec_wins = max_consec_losses = cur_wins = cur_losses = 0
        for t in trades:
            if t["pnl"] > 0:
                cur_wins   += 1; cur_losses = 0
            else:
                cur_losses += 1; cur_wins  = 0
            max_consec_wins   = max(max_consec_wins,   cur_wins)
            max_consec_losses = max(max_consec_losses, cur_losses)

        # Average hold duration (minutes from entry_ts to exit_ts)
        hold_mins = []
        for t in trades:
            if t.get("entry_ts") and t.get("exit_ts"):
                try:
                    delta = (t["exit_ts"] - t["entry_ts"]).total_seconds() / 60
                    if delta >= 0:
                        hold_mins.append(delta)
                except Exception:
                    pass
        avg_hold_minutes = round(sum(hold_mins) / len(hold_mins), 1) if hold_mins else None

        return {
            "total_trades":        len(trades),
            "winning_trades":      len(wins),
            "losing_trades":       len(losses),
            "win_rate":            round(win_rate * 100, 2),
            "total_pnl":           round(total_pnl, 2),
            "return_pct":          round(return_pct, 2),
            "max_drawdown_pct":    round(float(max_dd), 2),
            "profit_factor":       round(profit_factor, 2),
            "avg_win":             round(avg_win, 2),
            "avg_loss":            round(avg_loss, 2),
            "expectancy":          round(avg_win * win_rate - avg_loss * (1 - win_rate), 2),
            "sharpe_ratio":        round(sharpe, 3),
            "sortino_ratio":       round(sortino, 3),
            "max_consec_wins":     max_consec_wins,
            "max_consec_losses":   max_consec_losses,
            "avg_hold_minutes":    avg_hold_minutes,
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
                     avg_win, avg_loss, expectancy,
                     sharpe_ratio, sortino_ratio, max_consec_wins, max_consec_losses)
                VALUES
                    (:run_id, :total, :wins, :losses, :win_rate, :pnl, :ret,
                     :dd, :pf, :avg_win, :avg_loss, :exp,
                     :sharpe, :sortino, :mcw, :mcl)
                ON CONFLICT (run_id) DO UPDATE SET
                    total_trades=EXCLUDED.total_trades, win_rate=EXCLUDED.win_rate,
                    sharpe_ratio=EXCLUDED.sharpe_ratio, sortino_ratio=EXCLUDED.sortino_ratio
            """), {
                "run_id":  run_id,
                "total":   metrics["total_trades"],
                "wins":    metrics["winning_trades"],
                "losses":  metrics["losing_trades"],
                "win_rate": metrics["win_rate"],
                "pnl":     metrics["total_pnl"],
                "ret":     metrics["return_pct"],
                "dd":      metrics["max_drawdown_pct"],
                "pf":      metrics["profit_factor"],
                "avg_win": metrics["avg_win"],
                "avg_loss": metrics["avg_loss"],
                "exp":     metrics["expectancy"],
                "sharpe":  metrics.get("sharpe_ratio", 0),
                "sortino": metrics.get("sortino_ratio", 0),
                "mcw":     metrics.get("max_consec_wins", 0),
                "mcl":     metrics.get("max_consec_losses", 0),
            })
            await db.commit()

    async def list_runs(self, limit: int = 20) -> list[dict]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT r.run_id, r.strategy_name, r.symbols, r.timeframe,
                       r.start_date, r.end_date, r.status, r.created_at, r.completed_at,
                       m.win_rate, m.total_pnl, m.max_drawdown_pct,
                       m.profit_factor, m.total_trades
                FROM backtest_runs r
                LEFT JOIN backtest_metrics m ON r.run_id = m.run_id
                ORDER BY r.created_at DESC
                LIMIT :lim
            """), {"lim": limit})
            return [dict(r) for r in result.mappings().fetchall()]

    async def get_trades(self, run_id: str) -> list[dict]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT * FROM backtest_trades WHERE run_id = :rid ORDER BY entry_ts
            """), {"rid": run_id})
            return [dict(r) for r in result.mappings().fetchall()]
