"""ScoreValidationService — Phase 16 evidence collection with milestone gates.

Wraps SignalIntelligenceService with:
  - Trade count milestones: 200 / 500 / 1000
  - SCORE_CALIBRATION_REQUIRED flag when bucket performance is non-monotonic
  - UNDERPERFORMING_REGIME flag when regime Profit Factor < 1.0
  - BEST_TRADING_WINDOW / WORST_TRADING_WINDOW identification
  - Written recommendations — never modifies weights automatically

All methods are read-only. Fail-open: DB errors return structured empty reports.

Phase 16 Sections:
  A. Score Validation    — score bucket monotonicity gated by trade milestone
  B. Regime Validation   — regime ranking with UNDERPERFORMING_REGIME flags
  C. Time Window         — window ranking with BEST/WORST identification
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.signal_intelligence_service import SignalIntelligenceService

_log = logging.getLogger(__name__)

_MILESTONES = [200, 500, 1000]

_BUCKET_ORDER = ["85+", "80-84", "75-79", "70-74", "65-69", "60-64"]  # best → worst

# Regime flag threshold
_UNDERPERFORMING_PF_THRESHOLD = 1.0

# Slippage alert thresholds
_HIGH_SLIPPAGE_PCT = 0.5


class ScoreValidationService:
    """Evidence collection, milestone gating, and calibration flag generation."""

    def __init__(self, intelligence_svc: "SignalIntelligenceService") -> None:
        self._svc = intelligence_svc

    # ------------------------------------------------------------------
    # Section A — Score Validation (Phase 16A)
    # ------------------------------------------------------------------

    async def get_score_validation_report(
        self, lookback_days: int = 90
    ) -> dict:
        """Score bucket performance report with milestone gate and calibration flag.

        Returns:
          milestone_reached  — which milestone (200/500/1000) is currently satisfied
          buckets            — per-bucket metrics (descending score order)
          monotonic          — True if all metrics improve bucket-over-bucket
          flag               — "SCORE_CALIBRATION_REQUIRED" or None
          recommendations    — list of written recommendations (never auto-applied)
        """
        from sqlalchemy import text

        buckets = await self._svc.get_score_bucket_performance(lookback_days=lookback_days)
        total_trades = sum(int(b.get("trades") or 0) for b in buckets)

        # Milestone gate
        milestone_reached = None
        for m in sorted(_MILESTONES):
            if total_trades >= m:
                milestone_reached = m

        if milestone_reached is None:
            return {
                "milestone_reached": None,
                "trades_needed_for_first_milestone": _MILESTONES[0] - total_trades,
                "total_trades": total_trades,
                "status": "COLLECTING",
                "message": f"Need {_MILESTONES[0] - total_trades} more trades to reach first milestone.",
            }

        # Sort buckets by score bucket order (high → low)
        bucket_map = {b["score_bucket"]: b for b in buckets}
        ordered = [bucket_map[k] for k in _BUCKET_ORDER if k in bucket_map]

        # Monotonicity check: higher score bucket should have higher win_rate AND profit_factor
        win_rates = [float(b.get("win_rate_pct") or 0) for b in ordered]
        pfs       = [float(b.get("profit_factor") or 0) for b in ordered]

        non_monotonic_win = []
        non_monotonic_pf  = []
        for i in range(len(ordered) - 1):
            if win_rates[i] < win_rates[i + 1]:
                non_monotonic_win.append(
                    f"{ordered[i]['score_bucket']} win_rate {win_rates[i]:.1f}% "
                    f"< {ordered[i+1]['score_bucket']} win_rate {win_rates[i+1]:.1f}%"
                )
            if pfs[i] < pfs[i + 1]:
                non_monotonic_pf.append(
                    f"{ordered[i]['score_bucket']} PF {pfs[i]:.3f} "
                    f"< {ordered[i+1]['score_bucket']} PF {pfs[i+1]:.3f}"
                )

        calibration_required = bool(non_monotonic_win or non_monotonic_pf)
        flag = "SCORE_CALIBRATION_REQUIRED" if calibration_required else None

        recommendations = []
        if calibration_required:
            if non_monotonic_win:
                recommendations.append(
                    "WIN_RATE: High-score buckets are NOT outperforming lower buckets on win rate. "
                    "Review scoring component weights — one component may be scoring noise rather than signal. "
                    "Run per-component attribution on the non-monotonic bucket boundary."
                )
                recommendations.extend([f"  - {v}" for v in non_monotonic_win])
            if non_monotonic_pf:
                recommendations.append(
                    "PROFIT_FACTOR: Non-monotonic profit factor suggests entry or exit timing issue. "
                    "Check if high-score trades are entering later in the move (IV already expanded). "
                    "Consider tightening ADX gate for 80+ scores."
                )
                recommendations.extend([f"  - {v}" for v in non_monotonic_pf])
        else:
            recommendations.append(
                f"Score buckets show correct monotonic ordering at {milestone_reached}+ trade milestone. "
                "No weight changes required at this time. Re-evaluate at next milestone."
            )

        return {
            "milestone_reached":         milestone_reached,
            "next_milestone":            next((m for m in _MILESTONES if m > total_trades), None),
            "total_trades":              total_trades,
            "status":                    "CALIBRATION_REQUIRED" if calibration_required else "VALIDATED",
            "flag":                      flag,
            "monotonic_win_rate":        not bool(non_monotonic_win),
            "monotonic_profit_factor":   not bool(non_monotonic_pf),
            "non_monotonic_violations":  non_monotonic_win + non_monotonic_pf,
            "buckets":                   ordered,
            "recommendations":           recommendations,
        }

    # ------------------------------------------------------------------
    # Section B — Regime Validation (Phase 16B)
    # ------------------------------------------------------------------

    async def get_regime_validation_report(
        self, lookback_days: int = 60
    ) -> dict:
        """Regime performance ranked best → worst with UNDERPERFORMING_REGIME flags.

        Returns:
          ranked      — regimes sorted by profit_factor descending
          underperforming — list of regime names flagged with UNDERPERFORMING_REGIME
          recommendations — written suggestions, not auto-applied
        """
        rows = await self._svc.get_regime_performance(lookback_days=lookback_days)

        # Sort by profit_factor descending
        ranked = sorted(rows, key=lambda r: float(r.get("profit_factor") or 0), reverse=True)
        for i, r in enumerate(ranked):
            r["rank"] = i + 1

        underperforming = []
        for r in ranked:
            pf = float(r.get("profit_factor") or 0)
            if pf < _UNDERPERFORMING_PF_THRESHOLD and int(r.get("accepted") or 0) >= 10:
                r["flag"] = "UNDERPERFORMING_REGIME"
                underperforming.append(r["regime"])
            else:
                r["flag"] = None

        recommendations = []
        if underperforming:
            for regime in underperforming:
                recommendations.append(
                    f"UNDERPERFORMING_REGIME: {regime} has Profit Factor < 1.0. "
                    f"Options: (1) Raise the score floor for {regime} signals by +5 pts. "
                    f"(2) Tighten the regime-specific ADX gate. "
                    f"(3) If underperformance persists at 500+ trades, disable this regime. "
                    f"Do NOT change weights automatically until 100+ regime-specific trades."
                )
        else:
            recommendations.append(
                "All active regimes have Profit Factor ≥ 1.0. No regime-specific action required."
            )

        return {
            "ranked":            ranked,
            "underperforming":   underperforming,
            "flag":              "UNDERPERFORMING_REGIME" if underperforming else None,
            "recommendations":   recommendations,
        }

    # ------------------------------------------------------------------
    # Section C — Time Window Validation (Phase 16C)
    # ------------------------------------------------------------------

    async def get_time_window_validation_report(
        self, lookback_days: int = 60
    ) -> dict:
        """Time window performance with BEST/WORST identification.

        Returns:
          windows           — all windows with metrics
          best_window       — window with highest win_rate + profit_factor
          worst_window      — window with lowest profit_factor
          recommendations   — written suggestions
        """
        rows = await self._svc.get_time_window_performance(lookback_days=lookback_days)

        if not rows:
            return {"windows": [], "best_window": None, "worst_window": None, "recommendations": []}

        # Score each window: win_rate * 0.6 + profit_factor * 0.4 (capped at 3 for PF)
        def _composite(r: dict) -> float:
            wr = float(r.get("win_rate_pct") or 0) / 100
            pf = min(float(r.get("profit_factor") or 0), 3.0)
            return wr * 0.6 + pf * 0.4

        scored = sorted(rows, key=_composite, reverse=True)
        for r in scored:
            r["composite_score"] = round(_composite(r), 4)

        best  = scored[0]  if scored else None
        worst = scored[-1] if scored else None

        if best:
            best["tag"] = "BEST_TRADING_WINDOW"
        if worst and worst is not best:
            worst["tag"] = "WORST_TRADING_WINDOW"

        recommendations = []
        if worst:
            worst_pf = float(worst.get("profit_factor") or 0)
            if worst_pf < 1.0:
                recommendations.append(
                    f"WORST_TRADING_WINDOW: {worst['time_window']} has Profit Factor {worst_pf:.3f} < 1.0. "
                    f"Consider blocking new signals in this window. "
                    f"Minimum adjustment: raise score floor by +8 pts for this window. "
                    f"Do NOT implement until 50+ trades per window are observed."
                )
        if best:
            recommendations.append(
                f"BEST_TRADING_WINDOW: {best['time_window']} shows strongest performance. "
                f"This window is a candidate for slightly relaxed score floor (−2 pts) once 200+ window trades confirmed."
            )

        return {
            "windows":        scored,
            "best_window":    best["time_window"] if best else None,
            "worst_window":   worst["time_window"] if worst else None,
            "recommendations": recommendations,
        }
