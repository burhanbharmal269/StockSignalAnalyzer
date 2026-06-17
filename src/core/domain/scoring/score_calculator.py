"""ScoreCalculator — pure domain service for Phase 11 score aggregation.

Implements:
  1. Direction voting (base weights as votes)
  2. Regime multiplier application (effective_weight = base × multiplier)
  3. Weighted score aggregation with directional adjustment
     - Aligned component:      contribution = directional_score × eff_weight
     - Opposing component:     contribution = −(opposing_score × 0.30) × eff_weight
     - Neutral component:      contribution = long_score × 0.40 × eff_weight
  4. Raw score normalisation: (weighted_numerator / weighted_denominator) × 100
  5. Five penalty types
  6. Data completeness gate (>= 75%)
  7. Score quality classification
"""

from __future__ import annotations

import logging
from datetime import time, timedelta, timezone
from typing import TYPE_CHECKING

from core.domain.enums.market_regime import MarketRegime
from core.domain.value_objects.score_breakdown import ScoreBreakdown
from core.domain.value_objects.score_penalty import ScorePenalty
from core.domain.value_objects.score_result import ScoreResult

if TYPE_CHECKING:
    from core.domain.value_objects.component_output import ComponentOutput
    from core.domain.value_objects.score_context import ScoreContext
    from core.infrastructure.config.scoring_config import ScoringConfig
    from core.infrastructure.config.strategy_config import StrategyConfig

_log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
_MARKET_OPEN_START = time(9, 15)
_MARKET_OPEN_END = time(9, 30)
_MARKET_CLOSE_START = time(15, 15)

# Map regime → "expected" direction (used for REGIME_MISMATCH penalty)
_REGIME_DIRECTION: dict[MarketRegime, str] = {
    MarketRegime.TRENDING_BULLISH: "LONG",
    MarketRegime.TRENDING_BEARISH: "SHORT",
    MarketRegime.SIDEWAYS: "NEUTRAL",
    MarketRegime.HIGH_VOLATILITY: "NEUTRAL",
    MarketRegime.LOW_VOLATILITY: "NEUTRAL",
}

# Canonical order — breakdown fields follow this order
_COMPONENT_ORDER = [
    "OI_BUILDUP",
    "TREND",
    "OPTION_CHAIN",
    "VOLUME",
    "VWAP",
    "SENTIMENT",
    "IV_ANALYSIS",
]


class ScoreCalculator:
    """Pure domain service — no I/O, no side effects, no logging to callers."""

    def __init__(self, strategy_cfg: StrategyConfig, scoring_cfg: ScoringConfig) -> None:
        self._strategy = strategy_cfg
        self._scoring = scoring_cfg

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def calculate(
        self,
        component_outputs: list[ComponentOutput],
        context: ScoreContext,
    ) -> ScoreResult:
        """Run the full scoring pipeline and return a ScoreResult.

        Never raises — on insufficient data returns is_eligible=False.
        """
        # Step 1: data completeness gate (must compute before direction vote)
        available = [o for o in component_outputs if o.is_available]
        total = len(component_outputs)
        completeness_pct = (len(available) / total * 100.0) if total > 0 else 0.0
        min_pct = self._scoring.data_quality.data_completeness_min_pct

        # Step 2: direction vote
        direction, conviction = self._direction_vote(component_outputs)

        # For NEUTRAL or insufficient data — return zero score immediately
        if direction == "NEUTRAL" or completeness_pct < min_pct:
            is_eligible = False
            return self._empty_result(
                direction=direction,
                conviction=conviction,
                completeness_pct=completeness_pct,
                is_eligible=is_eligible,
                context=context,
            )

        is_eligible = True

        # Step 3: regime multipliers → effective weights (available only)
        regime_mults = self._regime_multipliers(context.regime)
        eff_weights: dict[str, float] = {
            o.component_name: (
                self._base_weight(o.component_name)
                * regime_mults.get(o.component_name, 1.0)
            )
            for o in available
        }

        # Step 4: weighted score aggregation
        raw_score, contributions = self._aggregate(available, direction, eff_weights)

        # Step 5: regime alignment
        regime_dir = _REGIME_DIRECTION.get(context.regime, "NEUTRAL")
        if regime_dir == "NEUTRAL":
            regime_alignment = "NEUTRAL"
            regime_mismatch = False
        elif regime_dir == direction:
            regime_alignment = "ALIGNED"
            regime_mismatch = False
        else:
            regime_alignment = "OPPOSED"
            regime_mismatch = True

        # Step 6: score breakdown
        breakdown = ScoreBreakdown(
            oi_buildup=contributions.get("OI_BUILDUP", 0.0),
            trend=contributions.get("TREND", 0.0),
            option_chain=contributions.get("OPTION_CHAIN", 0.0),
            volume=contributions.get("VOLUME", 0.0),
            vwap=contributions.get("VWAP", 0.0),
            sentiment=contributions.get("SENTIMENT", 0.0),
            iv_analysis=contributions.get("IV_ANALYSIS", 0.0),
            regime_alignment=regime_alignment,
            regime_mismatch=regime_mismatch,
            total_before_penalties=raw_score,
        )

        # Step 7: penalties
        penalties = self._compute_penalties(
            component_outputs=component_outputs,
            direction=direction,
            conviction=conviction,
            context=context,
            regime_mismatch=regime_mismatch,
        )
        penalty_total = sum(p.amount for p in penalties)
        adjusted_score = max(0.0, min(100.0, raw_score + penalty_total))

        # Step 8: score quality
        staleness_pts = sum(
            p.amount for p in penalties if p.penalty_type == "DATA_STALENESS"
        )
        score_quality = self._score_quality(completeness_pct, staleness_pts, conviction)

        return ScoreResult(
            direction=direction,
            direction_conviction=conviction,
            raw_score=raw_score,
            adjusted_score=adjusted_score,
            score_breakdown=breakdown,
            penalties=penalties,
            data_completeness_pct=completeness_pct,
            is_eligible=is_eligible,
            score_quality=score_quality,
            weights_sha256=self._scoring.sha256,
        )

    # ------------------------------------------------------------------
    # Direction voting
    # ------------------------------------------------------------------

    def _direction_vote(
        self, outputs: list[ComponentOutput]
    ) -> tuple[str, float]:
        long_votes = 0.0
        short_votes = 0.0
        for o in outputs:
            if not o.is_available:
                continue
            w = float(o.max_weight)
            if o.direction == "LONG":
                long_votes += w
            elif o.direction == "SHORT":
                short_votes += w
        total = long_votes + short_votes
        if total == 0.0:
            return "NEUTRAL", 0.0

        min_conviction = self._strategy.gates.direction_conviction_min
        if long_votes > short_votes:
            conviction = long_votes / total
            if conviction < min_conviction:
                return "NEUTRAL", conviction
            return "LONG", conviction
        if short_votes > long_votes:
            conviction = short_votes / total
            if conviction < min_conviction:
                return "NEUTRAL", conviction
            return "SHORT", conviction
        return "NEUTRAL", 0.5

    # ------------------------------------------------------------------
    # Regime multipliers
    # ------------------------------------------------------------------

    def _regime_multipliers(self, regime: MarketRegime) -> dict[str, float]:
        row = getattr(self._strategy.weights.regime_multipliers, regime.value)
        return {name: getattr(row, name) for name in _COMPONENT_ORDER}

    def _base_weight(self, component_name: str) -> int:
        return getattr(self._strategy.weights.base, component_name)  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Weighted score aggregation
    # ------------------------------------------------------------------

    def _aggregate(
        self,
        available: list[ComponentOutput],
        direction: str,
        eff_weights: dict[str, float],
    ) -> tuple[float, dict[str, float]]:
        """Return (raw_score 0–100, per-component contributions dict)."""
        weighted_num = 0.0
        weighted_den = 0.0
        contributions: dict[str, float] = {}

        for output in available:
            ew = eff_weights[output.component_name]
            bw = float(self._base_weight(output.component_name))
            weighted_den += bw * ew

            if output.direction == direction:
                # Aligned: use directional score directly
                ds = output.long_score if direction == "LONG" else output.short_score
                weighted_num += ds * ew
                contributions[output.component_name] = ds * ew
            elif output.direction != "NEUTRAL":
                # Opposing: −30% drag on the opposing score
                opposing = (
                    output.short_score if direction == "LONG" else output.long_score
                )
                drag = -(opposing * 0.30) * ew
                weighted_num += drag
                contributions[output.component_name] = drag
            else:
                # Neutral component: +40% partial credit using long_score
                partial = output.long_score * 0.40 * ew
                weighted_num += partial
                contributions[output.component_name] = partial

        if weighted_den == 0.0:
            raw_score = 0.0
            normalised: dict[str, float] = dict.fromkeys(contributions, 0.0)
        else:
            raw_score = max(0.0, min(100.0, (weighted_num / weighted_den) * 100.0))
            # Normalise contributions to sum to raw_score
            normalised = {
                k: (v / weighted_den * 100.0)
                for k, v in contributions.items()
            }

        return raw_score, normalised

    # ------------------------------------------------------------------
    # Penalties
    # ------------------------------------------------------------------

    def _compute_penalties(
        self,
        component_outputs: list[ComponentOutput],
        direction: str,
        conviction: float,
        context: ScoreContext,
        regime_mismatch: bool,
    ) -> list[ScorePenalty]:
        cfg = self._scoring.penalties
        penalties: list[ScorePenalty] = []

        # 1. DATA_STALENESS
        stale_count = 0
        stale_total = 0.0
        for output in component_outputs:
            if not output.is_available:
                continue
            max_age = self._max_age_for_component(output.component_name)
            if output.data_freshness_seconds > max_age:
                stale_penalty = -float(cfg.data_staleness_per_component)
                stale_total += stale_penalty
                if abs(stale_total) > cfg.data_staleness_cap:
                    # Cap reached — adjust last penalty to not exceed cap
                    overage = abs(stale_total) - cfg.data_staleness_cap
                    stale_penalty += overage
                    stale_total = -float(cfg.data_staleness_cap)
                if stale_penalty < 0.0:
                    penalties.append(
                        ScorePenalty(
                            penalty_type="DATA_STALENESS",
                            amount=stale_penalty,
                            reason=(
                                f"{output.component_name} data age "
                                f"{output.data_freshness_seconds}s "
                                f"exceeds {max_age}s threshold"
                            ),
                            component_name=output.component_name,
                        )
                    )
                stale_count += 1
                if abs(stale_total) >= cfg.data_staleness_cap:
                    break

        # 2. LOW_CONVICTION
        min_conv = self._strategy.gates.direction_conviction_min
        if conviction < min_conv:
            # Should not happen (direction would be NEUTRAL) but guard anyway
            penalties.append(
                ScorePenalty(
                    penalty_type="LOW_CONVICTION",
                    amount=-float(cfg.low_conviction_severe),
                    reason=f"Direction conviction {conviction:.2f} below minimum {min_conv:.2f}",
                )
            )
        elif conviction < 0.60:
            penalties.append(
                ScorePenalty(
                    penalty_type="LOW_CONVICTION",
                    amount=-float(cfg.low_conviction_moderate),
                    reason=f"Moderate conviction {conviction:.2f} (< 0.60)",
                )
            )

        # 3. MARKET_HOURS (IST)
        ist_time = context.evaluation_timestamp.astimezone(_IST).time()
        if _MARKET_OPEN_START <= ist_time < _MARKET_OPEN_END:
            penalties.append(
                ScorePenalty(
                    penalty_type="MARKET_HOURS",
                    amount=-float(cfg.market_hours_opening),
                    reason="Opening volatility window 09:15–09:30 IST",
                )
            )
        elif ist_time >= _MARKET_CLOSE_START:
            penalties.append(
                ScorePenalty(
                    penalty_type="MARKET_HOURS",
                    amount=-float(cfg.market_hours_closing),
                    reason="Post 15:15 IST closing illiquidity",
                )
            )

        # 4. REGIME_MISMATCH
        if regime_mismatch:
            penalties.append(
                ScorePenalty(
                    penalty_type="REGIME_MISMATCH",
                    amount=-float(cfg.regime_mismatch),
                    reason=(
                        f"{direction} signal opposes "
                        f"{context.regime.value} market regime"
                    ),
                )
            )

        # 5. EXPIRY_RISK
        if context.dte is not None:
            if context.dte == 0:
                penalties.append(
                    ScorePenalty(
                        penalty_type="EXPIRY_RISK",
                        amount=-float(cfg.expiry_dte_zero),
                        reason="Expiry day (DTE=0) — max pain dominates",
                    )
                )
            elif context.dte == 1:
                penalties.append(
                    ScorePenalty(
                        penalty_type="EXPIRY_RISK",
                        amount=-float(cfg.expiry_dte_one),
                        reason="Day before expiry (DTE=1) — elevated pin risk",
                    )
                )

        return penalties

    def _max_age_for_component(self, component_name: str) -> int:
        df = self._scoring.data_freshness
        if component_name in ("OI_BUILDUP", "TREND", "VOLUME", "VWAP"):
            return df.tick_data_max_age
        if component_name in ("OPTION_CHAIN", "IV_ANALYSIS"):
            return df.option_chain_max_age
        if component_name == "SENTIMENT":
            return df.news_max_age
        return df.tick_data_max_age

    # ------------------------------------------------------------------
    # Score quality
    # ------------------------------------------------------------------

    def _score_quality(
        self,
        completeness_pct: float,
        staleness_pts: float,
        conviction: float,
    ) -> str:
        cfg = self._scoring.data_quality
        min_pct = cfg.data_completeness_min_pct
        if completeness_pct < min_pct:
            return "INSUFFICIENT"
        high_conv = cfg.score_quality_high_min_conviction
        high_comp = cfg.score_quality_high_min_completeness_pct
        if (
            completeness_pct >= high_comp
            and staleness_pts == 0.0
            and conviction >= high_conv
        ):
            return "HIGH"
        med_conv = cfg.score_quality_medium_min_conviction
        med_stale = cfg.score_quality_medium_max_staleness_points
        if conviction >= med_conv and abs(staleness_pts) <= med_stale:
            return "MEDIUM"
        return "LOW"

    # ------------------------------------------------------------------
    # Helper — zero result for NEUTRAL / insufficient data
    # ------------------------------------------------------------------

    def _empty_result(
        self,
        direction: str,
        conviction: float,
        completeness_pct: float,
        is_eligible: bool,
        context: ScoreContext,
    ) -> ScoreResult:
        breakdown = ScoreBreakdown(
            oi_buildup=0.0,
            trend=0.0,
            option_chain=0.0,
            volume=0.0,
            vwap=0.0,
            sentiment=0.0,
            iv_analysis=0.0,
            regime_alignment="NEUTRAL",
            regime_mismatch=False,
            total_before_penalties=0.0,
        )
        return ScoreResult(
            direction=direction,
            direction_conviction=conviction,
            raw_score=0.0,
            adjusted_score=0.0,
            score_breakdown=breakdown,
            penalties=[],
            data_completeness_pct=completeness_pct,
            is_eligible=is_eligible,
            score_quality="INSUFFICIENT",
            weights_sha256=self._scoring.sha256,
            evaluated_at=context.evaluation_timestamp,
        )
