"""ConfidenceCalculator — pure domain service for confidence score computation.

Deterministic and synchronous. All external data (win rates, consecutive losses,
recent outcomes, historical accuracy) is resolved by the caller before passing in.
Identical inputs always produce identical outputs (AC-11).

The result's calibrated_confidence and final_confidence are set to raw_confidence
as placeholders; ConfidenceEngineService applies the Redis calibration factor and
ceiling via dataclasses.replace() before returning to the caller.

Reference: docs/21_SIGNAL_ENGINE.md §Stage 3 — Confidence Engine
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.enums.market_regime import MarketRegime
from core.domain.value_objects.confidence_result import ConfidenceResult
from core.domain.value_objects.signal_fingerprint import SignalFingerprint

if TYPE_CHECKING:
    from core.domain.value_objects.component_output import ComponentOutput
    from core.domain.value_objects.score_context import ScoreContext
    from core.domain.value_objects.score_result import ScoreResult
    from core.infrastructure.config.confidence_config import ConfidenceConfig

_REGIME_DIRECTION: dict[MarketRegime, str] = {
    MarketRegime.TRENDING_BULLISH: "BULLISH",
    MarketRegime.TRENDING_BEARISH: "BEARISH",
    MarketRegime.SIDEWAYS: "NEUTRAL",
    MarketRegime.HIGH_VOLATILITY: "NEUTRAL",
    MarketRegime.LOW_VOLATILITY: "NEUTRAL",
}


class ConfidenceCalculator:
    """Pure domain computation of the 10-component additive confidence formula.

    No I/O, no side effects, no randomness. All external data is passed in
    as pre-fetched values by ConfidenceEngineService.
    """

    def __init__(self, config: ConfidenceConfig) -> None:
        self._cfg = config

    def calculate(
        self,
        context: ScoreContext,
        score_result: ScoreResult,
        component_outputs: list[ComponentOutput],
        win_rate: float | None,
        historical_accuracy: tuple[float, int] | None,
        consecutive_losses: int,
        recent_outcomes_short: list[str],
        recent_outcomes_long: list[str],
    ) -> ConfidenceResult:
        """Compute a fully populated ConfidenceResult from pre-fetched inputs.

        calibrated_confidence and final_confidence are set to raw_confidence;
        the service replaces them after resolving the Redis calibration factor.
        """
        cfg = self._cfg

        score_bucket = SignalFingerprint.score_bucket_for(score_result.adjusted_score)
        vix_bucket = SignalFingerprint.vix_bucket_for(context.features.india_vix)
        top_2 = self._top_2_components(score_result)
        fingerprint = SignalFingerprint(
            regime=context.regime.value,
            score_bucket=score_bucket,
            direction=score_result.direction,
            top_2_components=top_2,
            vix_bucket=vix_bucket,
        )

        base = min(cfg.base.ceiling, score_result.adjusted_score * cfg.base.score_multiplier)
        win_rate_adj = self._win_rate_adj(win_rate)
        regime_alignment_adj = self._regime_alignment_adj(context.regime, score_result.direction)

        dq = self._data_quality_composite(component_outputs, score_result)
        data_quality_adj = dq["adj"]

        momentum_adj: float = cfg.momentum.adj_neutral
        breakout_adj: float = cfg.breakout.adj_none
        loss_streak_adj = max(
            cfg.loss_streak.floor, cfg.loss_streak.adj_per_loss * consecutive_losses
        )
        historical_accuracy_adj = self._historical_accuracy_adj(historical_accuracy)

        sa = self._signal_agreement(component_outputs, score_result.direction)
        signal_agreement_adj = sa["adj"]

        rp = self._recent_performance(recent_outcomes_short, recent_outcomes_long)
        recent_performance_adj = rp["adj"]

        raw = max(
            0.0,
            min(
                100.0,
                base
                + win_rate_adj
                + regime_alignment_adj
                + data_quality_adj
                + momentum_adj
                + breakout_adj
                + loss_streak_adj
                + historical_accuracy_adj
                + signal_agreement_adj
                + recent_performance_adj,
            ),
        )

        components: dict[str, float] = {
            "base_confidence": round(base, 4),
            "win_rate_adj": round(win_rate_adj, 4),
            "regime_alignment_adj": round(regime_alignment_adj, 4),
            "data_quality_adj": round(data_quality_adj, 4),
            "momentum_adj": round(momentum_adj, 4),
            "breakout_adj": round(breakout_adj, 4),
            "loss_streak_adj": round(loss_streak_adj, 4),
            "historical_accuracy_adj": round(historical_accuracy_adj, 4),
            "signal_agreement_adj": round(signal_agreement_adj, 4),
            "recent_performance_adj": round(recent_performance_adj, 4),
            # Data quality sub-inputs (AC-13 auditability)
            "dq_score_quality_score": round(dq["sq_score"], 4),
            "dq_completeness_score": round(dq["completeness"], 4),
            "dq_freshness_score": round(dq["freshness"], 4),
            "dq_composite": round(dq["composite"], 4),
            # Signal agreement sub-inputs
            "sa_agreeing": float(sa["agreeing"]),
            "sa_available": float(sa["available"]),
            "sa_pct": round(sa["pct"], 4),
            # Recent performance sub-inputs
            "rp_short_win_pct": round(rp["short_pct"], 4),
            "rp_long_win_pct": round(rp["long_pct"], 4),
            "rp_combined_pct": round(rp["combined_pct"], 4),
        }

        return ConfidenceResult(
            base_confidence=round(base, 4),
            win_rate_adj=round(win_rate_adj, 4),
            regime_alignment_adj=round(regime_alignment_adj, 4),
            data_quality_adj=round(data_quality_adj, 4),
            momentum_adj=round(momentum_adj, 4),
            breakout_adj=round(breakout_adj, 4),
            loss_streak_adj=round(loss_streak_adj, 4),
            historical_accuracy_adj=round(historical_accuracy_adj, 4),
            signal_agreement_adj=round(signal_agreement_adj, 4),
            recent_performance_adj=round(recent_performance_adj, 4),
            raw_confidence=round(raw, 4),
            calibrated_confidence=round(raw, 4),
            final_confidence=round(raw, 4),
            passed_gate=raw >= cfg.gate.min_confidence,
            score_bucket=score_bucket,
            fingerprint=fingerprint.sha256,
            confidence_components=components,
            explanation=[],
        )

    # ------------------------------------------------------------------
    # Component formulas
    # ------------------------------------------------------------------

    def _win_rate_adj(self, win_rate: float | None) -> float:
        cfg = self._cfg.win_rate
        if win_rate is None:
            return 0.0
        win_pct = win_rate * 100.0
        if win_pct > cfg.threshold_high:
            return cfg.adj_high
        if win_pct > cfg.threshold_mid:
            return cfg.adj_mid
        if win_pct >= cfg.threshold_low:
            return cfg.adj_low
        return cfg.adj_below_low

    def _regime_alignment_adj(self, regime: MarketRegime, direction: str) -> float:
        cfg = self._cfg.regime_alignment
        direction_layer = _REGIME_DIRECTION.get(regime, "NEUTRAL")
        if direction_layer == "NEUTRAL":
            return cfg.adj_neutral
        if (direction == "LONG" and direction_layer == "BULLISH") or (
            direction == "SHORT" and direction_layer == "BEARISH"
        ):
            return cfg.adj_aligned
        return cfg.adj_misaligned

    def _data_quality_composite(
        self,
        component_outputs: list[ComponentOutput],
        score_result: ScoreResult,
    ) -> dict[str, float]:
        cfg = self._cfg.data_quality

        sq_map: dict[str, float] = {
            "HIGH": cfg.score_quality_scores.HIGH,
            "MEDIUM": cfg.score_quality_scores.MEDIUM,
            "LOW": cfg.score_quality_scores.LOW,
            "INSUFFICIENT": cfg.score_quality_scores.INSUFFICIENT,
        }
        sq_score = sq_map.get(score_result.score_quality, cfg.score_quality_scores.LOW)

        completeness = max(0.0, min(100.0, score_result.data_completeness_pct))

        freshness_deduction = 0.0
        for output in component_outputs:
            if not output.is_available:
                continue
            age = output.data_freshness_seconds
            if output.component_name == "OI_BUILDUP" and age <= cfg.oi_grace_seconds:
                continue
            if cfg.staleness_mild_min_seconds <= age <= cfg.staleness_mild_max_seconds:
                freshness_deduction += cfg.staleness_mild_pts
            elif age > cfg.staleness_mild_max_seconds:
                freshness_deduction += cfg.staleness_severe_pts
            if freshness_deduction >= cfg.staleness_cap_pts:
                freshness_deduction = cfg.staleness_cap_pts
                break

        option_chain_available = any(
            o.component_name in ("OPTION_CHAIN", "IV_ANALYSIS") and o.is_available
            for o in component_outputs
        )
        if not option_chain_available:
            freshness_deduction = min(
                cfg.staleness_cap_pts,
                freshness_deduction + cfg.option_chain_missing_pts,
            )

        freshness_score = max(0.0, 100.0 - freshness_deduction)

        composite = max(
            0.0,
            min(
                100.0,
                sq_score * cfg.weight_score_quality
                + completeness * cfg.weight_data_completeness
                + freshness_score * cfg.weight_data_freshness,
            ),
        )

        if composite >= cfg.threshold_high:
            adj = cfg.adj_high
        elif composite >= cfg.threshold_mid:
            adj = cfg.adj_mid
        elif composite >= cfg.threshold_low:
            adj = cfg.adj_low
        else:
            adj = cfg.adj_below_low

        return {
            "adj": adj,
            "sq_score": sq_score,
            "completeness": completeness,
            "freshness": freshness_score,
            "composite": composite,
        }

    def _signal_agreement(
        self,
        component_outputs: list[ComponentOutput],
        direction: str,
    ) -> dict[str, float]:
        cfg = self._cfg.signal_agreement
        available = [o for o in component_outputs if o.is_available]
        if not available:
            return {"adj": 0.0, "agreeing": 0.0, "available": 0.0, "pct": 0.0}

        agreeing = sum(1 for o in available if o.direction == direction)
        n_available = len(available)
        pct = (agreeing / n_available) * 100.0

        if pct >= cfg.threshold_high:
            adj = cfg.adj_high
        elif pct >= cfg.threshold_mid:
            adj = cfg.adj_mid
        elif pct >= cfg.threshold_low:
            adj = cfg.adj_low
        else:
            adj = cfg.adj_below_low

        return {
            "adj": adj,
            "agreeing": float(agreeing),
            "available": float(n_available),
            "pct": pct,
        }

    def _historical_accuracy_adj(
        self,
        historical_accuracy: tuple[float, int] | None,
    ) -> float:
        cfg = self._cfg.historical_accuracy
        if historical_accuracy is None:
            return cfg.adj_neutral
        accuracy, sample_count = historical_accuracy
        accuracy_pct = accuracy * 100.0
        is_full = sample_count >= cfg.min_samples_full
        if accuracy_pct > cfg.threshold_high:
            return cfg.adj_high_full if is_full else cfg.adj_high_partial
        if accuracy_pct > cfg.threshold_mid:
            return cfg.adj_mid_full if is_full else cfg.adj_mid_partial
        if accuracy_pct >= cfg.threshold_neutral:
            return cfg.adj_neutral
        return cfg.adj_low_full if is_full else cfg.adj_low_partial

    def _recent_performance(
        self,
        recent_outcomes_short: list[str],
        recent_outcomes_long: list[str],
    ) -> dict[str, float]:
        cfg = self._cfg.recent_performance

        def _win_pct(outcomes: list[str]) -> float:
            if not outcomes:
                return 0.0
            return sum(1 for o in outcomes if o == "WIN") / len(outcomes) * 100.0

        short_pct = _win_pct(recent_outcomes_short)
        long_pct = _win_pct(recent_outcomes_long)

        if not recent_outcomes_short and not recent_outcomes_long:
            return {"adj": 0.0, "short_pct": 0.0, "long_pct": 0.0, "combined_pct": 0.0}

        if not recent_outcomes_short:
            combined_pct = long_pct
        elif not recent_outcomes_long:
            combined_pct = short_pct
        else:
            combined_pct = cfg.weight_short * short_pct + cfg.weight_long * long_pct

        if combined_pct >= cfg.threshold_high:
            adj = cfg.adj_high
        elif combined_pct >= cfg.threshold_mid:
            adj = cfg.adj_mid
        elif combined_pct >= cfg.threshold_low:
            adj = cfg.adj_low
        else:
            adj = cfg.adj_below_low

        return {
            "adj": adj,
            "short_pct": short_pct,
            "long_pct": long_pct,
            "combined_pct": combined_pct,
        }

    @staticmethod
    def fingerprint_for(context: ScoreContext, score_result: ScoreResult) -> str:
        """Compute the SHA-256 fingerprint without running the full formula.

        Used by ConfidenceEngineService to resolve the fingerprint before
        the async historical_accuracy lookup.
        """
        score_bucket = SignalFingerprint.score_bucket_for(score_result.adjusted_score)
        vix_bucket = SignalFingerprint.vix_bucket_for(context.features.india_vix)
        top_2 = ConfidenceCalculator._top_2_components(score_result)
        fp = SignalFingerprint(
            regime=context.regime.value,
            score_bucket=score_bucket,
            direction=score_result.direction,
            top_2_components=top_2,
            vix_bucket=vix_bucket,
        )
        return fp.sha256

    @staticmethod
    def _top_2_components(score_result: ScoreResult) -> tuple[str, str]:
        bd = score_result.score_breakdown
        contribs = {
            "OI_BUILDUP": abs(bd.oi_buildup),
            "TREND": abs(bd.trend),
            "OPTION_CHAIN": abs(bd.option_chain),
            "VOLUME": abs(bd.volume),
            "VWAP": abs(bd.vwap),
            "SENTIMENT": abs(bd.sentiment),
            "IV_ANALYSIS": abs(bd.iv_analysis),
        }
        ranked = sorted(contribs.items(), key=lambda x: x[1], reverse=True)
        top = sorted([ranked[0][0], ranked[1][0]])
        return (top[0], top[1])
