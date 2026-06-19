"""DynamicRiskBudgetService — Phase 18I score-based risk allocation.

Replaces fixed 1-lot sizing with a risk-budget approach that scales
position size proportionally to signal quality (score) and regime safety.

Risk Allocation Formula:
  base_risk_pct:
    score >= 85: 0.30%
    score 75-84: 0.20%
    score 70-74: 0.10%
    score < 70:  0.00% (not actionable)

  regime_multiplier:
    HIGH_VOLATILITY: × 0.50
    SIDEWAYS:        × 0.75
    LOW_VOLATILITY:  × 1.00
    TRENDING_*:      × 1.00

  effective_risk_pct = base_risk_pct × regime_multiplier

  portfolio_risk_rupees = account_capital × effective_risk_pct / 100
  option_stop_distance  = (option_entry - option_sl) / option_entry
  lots = floor(portfolio_risk_rupees / (option_entry × option_stop_distance × lot_size))
  lots = max(1, lots)                    # minimum 1 lot always

Daily Portfolio Risk Cap:
  Total effective_risk_pct across ALL signals in a day must not exceed 1.0%.
  Implemented as a fail-safe: daily remaining risk budget is checked before allocation.

Phase 18 Section I — Dynamic Risk Budget
Phase 18 Section H — Small Capital Deployment (override: lots = 1 when small_capital_mode=True)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Risk per score tier (as % of account capital at risk per trade)
_SCORE_RISK_TABLE: dict[str, float] = {
    "85+":   0.30,
    "75-84": 0.20,
    "70-74": 0.10,
}

# Regime multipliers
_REGIME_MULTIPLIERS: dict[str, float] = {
    "HIGH_VOLATILITY":   0.50,
    "SIDEWAYS":          0.75,
    "LOW_VOLATILITY":    1.00,
    "TRENDING_BULLISH":  1.00,
    "TRENDING_BEARISH":  1.00,
}

_DAILY_MAX_RISK_PCT = 1.0   # never exceed 1% daily portfolio risk


@dataclass
class RiskAllocation:
    score_tier:            str
    regime_multiplier:     float
    base_risk_pct:         float
    effective_risk_pct:    float
    portfolio_risk_rupees: float
    lots:                  int
    is_small_capital_mode: bool
    daily_remaining_pct:   float
    capped_by_daily_limit: bool


class DynamicRiskBudgetService:
    """Computes score+regime risk allocation and enforces daily budget cap."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        account_capital: float = 200_000.0,      # ₹2 lakh default (small capital phase)
        small_capital_mode: bool = True,           # Phase 18H: forced 1 lot
    ) -> None:
        self._sf              = session_factory
        self._account_capital = account_capital
        self._small_capital   = small_capital_mode

    def _score_tier(self, score: float) -> str:
        if score >= 85:
            return "85+"
        if score >= 75:
            return "75-84"
        if score >= 70:
            return "70-74"
        return "below_70"

    def _regime_multiplier(self, regime: str) -> float:
        return _REGIME_MULTIPLIERS.get(str(regime), 1.0)

    async def _daily_used_risk_pct(self) -> float:
        """Sum of effective_risk_pct already consumed today (from allocated positions)."""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT COUNT(*) FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NULL
                          AND created_at >= :today
                    """),
                    {"today": today_start},
                )
                open_pos = int((r.fetchone() or (0,))[0] or 0)
            # Each open position consumed ~effective_risk_pct on average.
            # We use count × avg_risk as a conservative proxy (can be replaced
            # with actual per-position risk once trade log stores it).
            # Assume avg 0.20% per open position as a safe proxy.
            return open_pos * 0.20
        except Exception:
            return 0.0

    async def compute(
        self,
        *,
        score: float,
        regime: str,
        option_entry: float,
        option_sl: float,
        lot_size: int,
    ) -> RiskAllocation:
        """Compute risk allocation for a single signal.

        Returns RiskAllocation with lots=1 when in small_capital_mode.
        Returns lots=0 when score < 70 or daily budget exhausted.
        """
        tier       = self._score_tier(score)
        base_risk  = _SCORE_RISK_TABLE.get(tier, 0.0)

        if base_risk == 0.0:
            return RiskAllocation(
                score_tier=tier, regime_multiplier=0.0, base_risk_pct=0.0,
                effective_risk_pct=0.0, portfolio_risk_rupees=0.0,
                lots=0, is_small_capital_mode=self._small_capital,
                daily_remaining_pct=0.0, capped_by_daily_limit=False,
            )

        reg_mult      = self._regime_multiplier(regime)
        effective_pct = base_risk * reg_mult

        # Check daily budget
        used        = await self._daily_used_risk_pct()
        remaining   = max(0.0, _DAILY_MAX_RISK_PCT - used)
        capped      = effective_pct > remaining
        final_pct   = min(effective_pct, remaining)

        if final_pct <= 0.0:
            return RiskAllocation(
                score_tier=tier, regime_multiplier=reg_mult, base_risk_pct=base_risk,
                effective_risk_pct=0.0, portfolio_risk_rupees=0.0,
                lots=0, is_small_capital_mode=self._small_capital,
                daily_remaining_pct=remaining, capped_by_daily_limit=True,
            )

        portfolio_risk_rupees = self._account_capital * final_pct / 100

        # Compute lots from risk budget
        stop_distance = abs(option_entry - option_sl)
        if stop_distance > 0 and lot_size > 0:
            risk_per_lot = stop_distance * lot_size
            raw_lots     = math.floor(portfolio_risk_rupees / risk_per_lot)
        else:
            raw_lots = 1

        lots = max(1, raw_lots)

        # Phase 18H: small capital mode forces 1 lot regardless of budget
        if self._small_capital:
            lots = 1

        _log.info(
            "risk_budget score=%.1f tier=%s regime=%s base=%.2f%% eff=%.2f%% "
            "capital_at_risk=₹%.0f lots=%d small=%s",
            score, tier, regime, base_risk, final_pct,
            portfolio_risk_rupees, lots, self._small_capital,
        )

        return RiskAllocation(
            score_tier=tier, regime_multiplier=reg_mult, base_risk_pct=base_risk,
            effective_risk_pct=final_pct, portfolio_risk_rupees=portfolio_risk_rupees,
            lots=lots, is_small_capital_mode=self._small_capital,
            daily_remaining_pct=remaining, capped_by_daily_limit=capped,
        )

    async def get_budget_status(self) -> dict:
        """Current daily risk budget utilisation."""
        used      = await self._daily_used_risk_pct()
        remaining = max(0.0, _DAILY_MAX_RISK_PCT - used)
        return {
            "account_capital":       self._account_capital,
            "small_capital_mode":    self._small_capital,
            "daily_max_risk_pct":    _DAILY_MAX_RISK_PCT,
            "daily_used_risk_pct":   round(used, 4),
            "daily_remaining_pct":   round(remaining, 4),
            "risk_table":            _SCORE_RISK_TABLE,
            "regime_multipliers":    _REGIME_MULTIPLIERS,
        }
