"""ExecutionSlippageService — Phase 23 §3, §4, §8.

Records entry/exit slippage, liquidity context at execution time,
and computes fill quality scores.

Slippage = actual_price - expected_price (positive = worse for buyer).
Fill quality score (0-100) combines:
  - Fill completeness (fill_pct)
  - Slippage magnitude
  - Spread at execution
  - Number of partial fills
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Slippage alert thresholds (§12)
_SLIPPAGE_WARN_PCT  = 0.5   # 0.5% entry slippage — warn
_SLIPPAGE_CRIT_PCT  = 2.0   # 2.0% entry slippage — critical


class ExecutionSlippageService:
    """Records slippage and fill quality. Fail-open."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record_entry(
        self,
        signal_id: str,
        order_id: str | None = None,
        *,
        symbol: str | None = None,
        broker: str = "kite",
        direction: str | None = None,
        expected_entry: float | None = None,
        actual_entry: float | None = None,
        lot_size: int | None = None,
        lots: int | None = None,
        bid: float | None = None,
        ask: float | None = None,
        available_qty: int | None = None,
    ) -> None:
        """Record entry slippage + liquidity snapshot."""
        try:
            entry_slip_pts = entry_slip_pct = entry_slip_inr = None
            spread = spread_pct = liquidity_score = None

            if expected_entry and actual_entry:
                entry_slip_pts = round(actual_entry - expected_entry, 4)
                entry_slip_pct = round((entry_slip_pts / expected_entry) * 100, 6)
                lots_ = lots or 1
                lot_size_ = lot_size or 1
                entry_slip_inr = round(entry_slip_pts * lots_ * lot_size_, 4)

                if abs(entry_slip_pct) > _SLIPPAGE_CRIT_PCT:
                    _log.warning(
                        "execution_slippage.CRITICAL signal=%s symbol=%s entry_slippage_pct=%.2f%%",
                        signal_id, symbol or "?", entry_slip_pct,
                    )
                elif abs(entry_slip_pct) > _SLIPPAGE_WARN_PCT:
                    _log.warning(
                        "execution_slippage.WARNING signal=%s symbol=%s entry_slippage_pct=%.2f%%",
                        signal_id, symbol or "?", entry_slip_pct,
                    )

            if bid is not None and ask is not None:
                spread = round(ask - bid, 4)
                mid = (bid + ask) / 2
                spread_pct = round((spread / mid) * 100, 4) if mid else None
                liquidity_score = _liquidity_score(spread_pct, available_qty)

            async with self._sf() as db:
                await db.execute(text("""
                    INSERT INTO execution_slippage
                        (signal_id, order_id, symbol, broker, direction,
                         expected_entry, actual_entry,
                         entry_slippage_points, entry_slippage_pct, entry_slippage_rupees,
                         lot_size, lots, bid, ask, spread, spread_pct,
                         available_qty, liquidity_score, recorded_at)
                    VALUES
                        (:sid, :oid, :sym, :broker, :dir,
                         :exp_e, :act_e,
                         :slip_pts, :slip_pct, :slip_inr,
                         :lot_size, :lots, :bid, :ask, :spread, :spread_pct,
                         :avail_qty, :liq_score, NOW())
                """), {
                    "sid": signal_id, "oid": order_id, "sym": symbol,
                    "broker": broker, "dir": direction,
                    "exp_e": expected_entry, "act_e": actual_entry,
                    "slip_pts": entry_slip_pts, "slip_pct": entry_slip_pct, "slip_inr": entry_slip_inr,
                    "lot_size": lot_size, "lots": lots,
                    "bid": bid, "ask": ask, "spread": spread, "spread_pct": spread_pct,
                    "avail_qty": available_qty, "liq_score": liquidity_score,
                })
                await db.commit()
        except Exception as exc:
            _log.debug("execution_slippage.record_entry_failed signal=%s: %s", signal_id, exc)

    async def record_exit(
        self,
        signal_id: str,
        *,
        expected_exit: float | None = None,
        actual_exit: float | None = None,
        lot_size: int | None = None,
        lots: int | None = None,
    ) -> None:
        """Update exit slippage on the existing slippage row for signal_id."""
        try:
            exit_pts = exit_pct = exit_inr = total_pts = total_pct = total_inr = None

            if expected_exit and actual_exit:
                # For exits (sell), lower actual is worse — invert sign convention
                exit_pts = round(expected_exit - actual_exit, 4)
                exit_pct = round((exit_pts / expected_exit) * 100, 6)
                lots_ = lots or 1
                lot_size_ = lot_size or 1
                exit_inr = round(exit_pts * lots_ * lot_size_, 4)

            async with self._sf() as db:
                if exit_pts is not None:
                    await db.execute(text("""
                        UPDATE execution_slippage SET
                            expected_exit = :exp_e,
                            actual_exit   = :act_e,
                            exit_slippage_points  = :ep,
                            exit_slippage_pct     = :epct,
                            exit_slippage_rupees  = :einr,
                            total_slippage_points = COALESCE(entry_slippage_points, 0) + :ep,
                            total_slippage_pct    = COALESCE(entry_slippage_pct, 0)    + :epct,
                            total_slippage_rupees = COALESCE(entry_slippage_rupees, 0) + :einr
                        WHERE signal_id = :sid
                          AND id = (SELECT MAX(id) FROM execution_slippage WHERE signal_id = :sid)
                    """), {
                        "sid": signal_id,
                        "exp_e": expected_exit, "act_e": actual_exit,
                        "ep": exit_pts, "epct": exit_pct, "einr": exit_inr,
                    })
                    await db.commit()
        except Exception as exc:
            _log.debug("execution_slippage.record_exit_failed signal=%s: %s", signal_id, exc)

    async def record_fill_quality(
        self,
        signal_id: str,
        order_id: str | None = None,
        *,
        symbol: str | None = None,
        broker: str = "kite",
        fill_pct: float = 100.0,
        num_fills: int = 1,
        partial_fills: int = 0,
        avg_fill_price: float | None = None,
        best_fill_price: float | None = None,
        worst_fill_price: float | None = None,
    ) -> float:
        """Record fill quality and return computed quality score (0-100)."""
        try:
            score = _compute_quality_score(fill_pct, num_fills, partial_fills, avg_fill_price, best_fill_price, worst_fill_price)
            async with self._sf() as db:
                await db.execute(text("""
                    INSERT INTO execution_metrics
                        (signal_id, order_id, symbol, broker,
                         fill_pct, num_fills, partial_fills,
                         avg_fill_price, best_fill_price, worst_fill_price,
                         execution_quality_score, recorded_at)
                    VALUES
                        (:sid, :oid, :sym, :broker,
                         :fill_pct, :num_fills, :partial_fills,
                         :avg_fp, :best_fp, :worst_fp,
                         :score, NOW())
                """), {
                    "sid": signal_id, "oid": order_id, "sym": symbol, "broker": broker,
                    "fill_pct": fill_pct, "num_fills": num_fills, "partial_fills": partial_fills,
                    "avg_fp": avg_fill_price, "best_fp": best_fill_price, "worst_fp": worst_fill_price,
                    "score": score,
                })
                await db.commit()
            return score
        except Exception as exc:
            _log.debug("execution_slippage.fill_quality_failed signal=%s: %s", signal_id, exc)
            return 0.0

    async def get_slippage_stats(
        self, hours: int = 24, broker: str | None = None
    ) -> dict[str, Any]:
        """Aggregate slippage stats across recent orders."""
        try:
            params: dict[str, Any] = {"hrs": hours}
            broker_filter = "AND broker = :broker" if broker else ""
            if broker:
                params["broker"] = broker
            async with self._sf() as db:
                r = await db.execute(text(f"""
                    SELECT
                        COUNT(*) AS n,
                        AVG(entry_slippage_pct) AS avg_entry_slip_pct,
                        AVG(total_slippage_pct) AS avg_total_slip_pct,
                        AVG(total_slippage_rupees) AS avg_total_slip_inr,
                        MAX(total_slippage_pct) AS max_slip_pct,
                        AVG(liquidity_score) AS avg_liq_score
                    FROM execution_slippage
                    WHERE recorded_at > NOW() - :hrs * INTERVAL '1 hour'
                    {broker_filter}
                """), params)
                row = r.mappings().fetchone()
            return dict(row) if row else {}
        except Exception as exc:
            _log.debug("execution_slippage.get_stats_failed: %s", exc)
            return {"error": str(exc)}

    async def get_fill_quality_stats(self, hours: int = 24) -> dict[str, Any]:
        """Aggregate fill quality scores."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*) AS n,
                        AVG(execution_quality_score) AS avg_score,
                        MIN(execution_quality_score) AS min_score,
                        AVG(fill_pct) AS avg_fill_pct,
                        AVG(partial_fills) AS avg_partials
                    FROM execution_metrics
                    WHERE recorded_at > NOW() - :hrs * INTERVAL '1 hour'
                """), {"hrs": hours})
                row = r.mappings().fetchone()
            return dict(row) if row else {}
        except Exception as exc:
            _log.debug("execution_slippage.fill_quality_stats_failed: %s", exc)
            return {"error": str(exc)}


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _liquidity_score(spread_pct: float | None, available_qty: int | None) -> float:
    """Score liquidity 0-100. High spread or low qty → lower score."""
    score = 100.0
    if spread_pct is not None:
        # Deduct up to 60 points based on spread (0%=0 penalty, 2%+=60 penalty)
        score -= min(spread_pct * 30, 60.0)
    if available_qty is not None:
        # Deduct up to 40 points based on depth (0=40 deduction, 1000+=0)
        score -= max(0.0, 40.0 - (available_qty / 25.0))
    return round(max(0.0, min(100.0, score)), 2)


def _compute_quality_score(
    fill_pct: float,
    num_fills: int,
    partial_fills: int,
    avg_fill_price: float | None,
    best_fill_price: float | None,
    worst_fill_price: float | None,
) -> float:
    """Fill quality score 0-100.

    100 = instant complete fill at best price, single fill.
    Penalties: incomplete fill, multiple partial fills, large price range.
    """
    score = fill_pct  # starts at fill_pct (0-100)

    # Penalty for partial fills: -5 per partial (max -25)
    if partial_fills > 0:
        score -= min(partial_fills * 5, 25)

    # Penalty for large price range across fills
    if avg_fill_price and best_fill_price and worst_fill_price and avg_fill_price > 0:
        price_range_pct = ((worst_fill_price - best_fill_price) / avg_fill_price) * 100
        score -= min(price_range_pct * 10, 20)

    return round(max(0.0, min(100.0, score)), 2)
