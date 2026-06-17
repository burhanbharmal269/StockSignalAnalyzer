"""BacktestRun and BacktestMetrics — results from the backtesting engine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass
class BacktestTrade:
    trade_id: int | None
    run_id: str
    symbol: str
    direction: str      # LONG | SHORT
    entry_at: datetime
    entry_price: Decimal
    exit_at: datetime | None = None
    exit_price: Decimal | None = None
    stop_loss: Decimal | None = None
    target: Decimal | None = None
    quantity: int = 1
    pnl: Decimal | None = None
    pnl_pct: Decimal | None = None
    exit_reason: str | None = None
    strategy_name: str | None = None


@dataclass
class BacktestMetrics:
    run_id: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal | None = None
    total_pnl: Decimal | None = None
    avg_profit: Decimal | None = None
    avg_loss: Decimal | None = None
    profit_factor: Decimal | None = None
    expectancy: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    sharpe_ratio: Decimal | None = None
    sortino_ratio: Decimal | None = None
    cagr: Decimal | None = None
    avg_trade_duration_mins: Decimal | None = None


@dataclass
class BacktestRun:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    strategy_name: str = ""
    params: dict = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    timeframe: str = "15m"
    start_date: date | None = None
    end_date: date | None = None
    status: str = "PENDING"        # PENDING | RUNNING | COMPLETED | FAILED
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    trades: list[BacktestTrade] = field(default_factory=list)
    metrics: BacktestMetrics | None = None
