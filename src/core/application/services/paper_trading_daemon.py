"""PaperTradingDaemon — continuous paper trading loop.

Runs strategies against live market data every N minutes during market hours.
Generates signals → applies risk rules → executes via paper broker.
Journals all activity to the paper_trade_journal table.

Market hours: Mon-Fri 09:15-15:30 IST.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from core.application.services.historical_data_service import HistoricalDataService
    from core.application.services.market_universe_service import MarketUniverseService
    from core.domain.strategies.base_strategy import IStrategy
    from sqlalchemy.ext.asyncio import async_sessionmaker

_log = logging.getLogger(__name__)

# IST = UTC+5:30
_MARKET_OPEN = time(9, 15)
_MARKET_CLOSE = time(15, 30)
_SCAN_INTERVAL_SECONDS = 300       # scan every 5 minutes
_MAX_OPEN_POSITIONS = 10
_RISK_PER_TRADE_PCT = Decimal("1")  # 1% capital per trade
_INITIAL_PAPER_CAPITAL = Decimal("500000")


class PaperTradingDaemon:
    def __init__(
        self,
        universe_service: MarketUniverseService,
        historical_service: HistoricalDataService,
        strategies: list[IStrategy],
        session_factory,
    ) -> None:
        self._universe = universe_service
        self._historical = historical_service
        self._strategies = strategies
        self._sf = session_factory

        self._running = False
        self._capital = _INITIAL_PAPER_CAPITAL
        self._positions: dict[str, dict] = {}   # symbol → position
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            _log.info("paper_daemon.already_running")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="paper_daemon")
        _log.info("paper_daemon.started strategies=%s", [s.name for s in self._strategies])

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _log.info("paper_daemon.stopped")

    def status(self) -> dict:
        return {
            "running": self._running,
            "open_positions": len(self._positions),
            "capital": float(self._capital),
            "positions": list(self._positions.keys()),
            "strategies": [s.name for s in self._strategies],
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            try:
                if self._is_market_hours():
                    await self._tick()
                else:
                    _log.debug("paper_daemon.market_closed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.error("paper_daemon.tick_error err=%s", exc, exc_info=True)

            await asyncio.sleep(_SCAN_INTERVAL_SECONDS)

    def _is_market_hours(self) -> bool:
        # Convert UTC to IST (UTC+5:30)
        now_utc = datetime.now(UTC)
        ist_hour = (now_utc.hour * 60 + now_utc.minute + 330) // 60 % 24
        ist_minute = (now_utc.minute + 330) % 60
        now_ist = time(ist_hour, ist_minute)
        weekday = now_utc.weekday()   # 0=Mon, 5=Sat, 6=Sun
        return weekday < 5 and _MARKET_OPEN <= now_ist <= _MARKET_CLOSE

    # ------------------------------------------------------------------
    # Per-tick logic
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        _log.debug("paper_daemon.tick positions=%d capital=%.0f",
                   len(self._positions), float(self._capital))

        await self._check_exits()

        if len(self._positions) >= _MAX_OPEN_POSITIONS:
            return

        symbols = await self._universe.get_fo_symbols()
        for symbol in symbols[:50]:   # scan top 50 for performance
            if symbol in self._positions:
                continue

            for strategy in self._strategies:
                try:
                    candles = await self._historical.get_latest(
                        symbol, strategy.preferred_timeframes[0],
                        strategy.min_candles_required + 5
                    )
                    if len(candles) < strategy.min_candles_required:
                        continue

                    signal = await strategy.generate_signal(symbol, candles)
                    if signal and signal.confidence >= Decimal("0.65"):
                        await self._open_position(signal)
                        break  # one strategy per symbol per tick
                except Exception as exc:
                    _log.debug("paper_daemon.signal_error sym=%s err=%s", symbol, exc)

    async def _check_exits(self) -> None:
        for symbol, pos in list(self._positions.items()):
            try:
                candles = await self._historical.get_latest(symbol, pos["timeframe"], 3)
                if not candles:
                    continue
                current = candles[-1]
                exit_reason = None

                if pos["direction"] == "LONG":
                    if current.high >= Decimal(str(pos["target"])):
                        exit_reason = "TARGET"
                        exit_price = Decimal(str(pos["target"]))
                    elif current.low <= Decimal(str(pos["stop_loss"])):
                        exit_reason = "STOP"
                        exit_price = Decimal(str(pos["stop_loss"]))
                else:
                    if current.low <= Decimal(str(pos["target"])):
                        exit_reason = "TARGET"
                        exit_price = Decimal(str(pos["target"]))
                    elif current.high >= Decimal(str(pos["stop_loss"])):
                        exit_reason = "STOP"
                        exit_price = Decimal(str(pos["stop_loss"]))

                if exit_reason:
                    await self._close_position(symbol, pos, exit_price, exit_reason)
            except Exception as exc:
                _log.debug("paper_daemon.exit_check_error sym=%s err=%s", symbol, exc)

    async def _open_position(self, signal) -> None:
        price = signal.entry_price
        risk_amount = self._capital * _RISK_PER_TRADE_PCT / 100
        risk_per_unit = abs(price - signal.stop_loss)
        if risk_per_unit == 0:
            return

        qty = max(1, int(risk_amount / risk_per_unit))
        cost = price * qty

        if cost > self._capital * Decimal("0.2"):  # max 20% per position
            qty = max(1, int(self._capital * Decimal("0.2") / price))

        self._positions[signal.symbol] = {
            "symbol": signal.symbol,
            "direction": signal.direction,
            "entry_price": float(price),
            "stop_loss": float(signal.stop_loss),
            "target": float(signal.target),
            "qty": qty,
            "strategy": signal.strategy_name,
            "timeframe": signal.timeframe,
            "entry_ts": datetime.now(UTC),
            "confidence": float(signal.confidence),
        }

        _log.info("paper_daemon.open sym=%s dir=%s price=%.2f qty=%d strategy=%s",
                  signal.symbol, signal.direction, price, qty, signal.strategy_name)
        await self._journal("OPEN", signal.symbol, self._positions[signal.symbol], None, None)

    async def _close_position(
        self, symbol: str, pos: dict, exit_price: Decimal, reason: str
    ) -> None:
        qty = pos["qty"]
        entry = Decimal(str(pos["entry_price"]))

        if pos["direction"] == "LONG":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        self._capital += pnl
        del self._positions[symbol]

        _log.info("paper_daemon.close sym=%s reason=%s pnl=%.2f capital=%.0f",
                  symbol, reason, float(pnl), float(self._capital))
        await self._journal("CLOSE", symbol, pos, float(exit_price), float(pnl))

    async def _journal(
        self, action: str, symbol: str, pos: dict, exit_price: float | None, pnl: float | None
    ) -> None:
        async with self._sf() as db:
            try:
                await db.execute(text("""
                    INSERT INTO paper_trade_journal
                        (symbol, action, direction, price, qty, strategy_name,
                         stop_loss, target, pnl, capital_after, notes)
                    VALUES
                        (:sym, :action, :dir, :price, :qty, :strategy,
                         :stop, :target, :pnl, :capital, :notes)
                """), {
                    "sym": symbol,
                    "action": action,
                    "dir": pos["direction"],
                    "price": exit_price if exit_price else pos["entry_price"],
                    "qty": pos["qty"],
                    "strategy": pos["strategy"],
                    "stop": pos["stop_loss"],
                    "target": pos["target"],
                    "pnl": pnl,
                    "capital": float(self._capital),
                    "notes": f"confidence={pos.get('confidence', 0):.2f}",
                })
                await db.commit()
            except Exception as exc:
                _log.debug("paper_daemon.journal_error err=%s", exc)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    async def get_journal(self, limit: int = 50) -> list[dict]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT * FROM paper_trade_journal
                ORDER BY signal_at DESC LIMIT :lim
            """), {"lim": limit})
            return [dict(r) for r in result.mappings().fetchall()]

    async def get_performance(self) -> dict:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE status='CLOSED') as total_trades,
                    SUM(pnl) FILTER (WHERE status='CLOSED') as total_pnl,
                    COUNT(*) FILTER (WHERE status='CLOSED' AND pnl > 0) as wins,
                    COUNT(*) FILTER (WHERE status='CLOSED' AND pnl <= 0) as losses
                FROM paper_trade_journal
            """))
            row = result.fetchone()
            total = int(row[0] or 0)
            total_pnl = float(row[1] or 0)
            wins = int(row[2] or 0)
            losses = int(row[3] or 0)
            return {
                "total_trades": total,
                "total_pnl": total_pnl,
                "win_rate": round(wins / total * 100, 2) if total else 0,
                "wins": wins,
                "losses": losses,
                "current_capital": float(self._capital),
                "initial_capital": float(_INITIAL_PAPER_CAPITAL),
                "return_pct": round(
                    float((self._capital - _INITIAL_PAPER_CAPITAL) / _INITIAL_PAPER_CAPITAL * 100), 2
                ),
            }
