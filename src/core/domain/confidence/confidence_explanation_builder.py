"""ConfidenceExplanationBuilder — human-readable explanation for ConfidenceResult.

Pure domain service. Deterministic given identical inputs. No I/O.

Forbidden words in any output line: BUY, SELL, ORDER, TRADE, ENTRY,
STOP_LOSS, TARGET. The explanation describes signal trustworthiness only.

Reference: docs/21_SIGNAL_ENGINE.md §Stage 3 — Confidence Engine
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.enums.market_regime import MarketRegime

if TYPE_CHECKING:
    from core.domain.value_objects.confidence_result import ConfidenceResult
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


class ConfidenceExplanationBuilder:
    """Builds explanation list from a complete ConfidenceResult.

    Called by ConfidenceEngineService after calibration and ceiling are
    applied. The returned list is attached to the result via dataclasses.replace().
    """

    def __init__(self, config: ConfidenceConfig) -> None:
        self._cfg = config

    def build(
        self,
        result: ConfidenceResult,
        context: ScoreContext,
        score_result: ScoreResult,
    ) -> list[str]:
        """Produce explanation lines. Never contains forbidden trading labels."""
        gate_label = "PASS" if result.passed_gate else "FAIL"
        lines: list[str] = [
            (
                f"confidence={result.final_confidence:.1f}"
                f" | direction={score_result.direction}"
                f" | bucket={result.score_bucket}"
                f" | gate={gate_label}"
            ),
        ]

        # Top 3 adjustments by absolute value (excluding base_confidence)
        adj_fields: dict[str, float] = {
            "win_rate_adj": result.win_rate_adj,
            "regime_alignment_adj": result.regime_alignment_adj,
            "data_quality_adj": result.data_quality_adj,
            "momentum_adj": result.momentum_adj,
            "breakout_adj": result.breakout_adj,
            "loss_streak_adj": result.loss_streak_adj,
            "historical_accuracy_adj": result.historical_accuracy_adj,
            "signal_agreement_adj": result.signal_agreement_adj,
            "recent_performance_adj": result.recent_performance_adj,
        }
        top3 = sorted(adj_fields.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        top3_str = " | ".join(f"{k}={v:+.1f}" for k, v in top3)
        lines.append(f"Top adjustments: {top3_str}")

        # Signal agreement
        cc = result.confidence_components
        agreeing = int(cc.get("sa_agreeing", 0.0))
        available = int(cc.get("sa_available", 0.0))
        sa_pct = cc.get("sa_pct", 0.0)
        if available > 0:
            lines.append(
                f"Agreement: {agreeing}/{available} components aligned ({sa_pct:.1f}%)"
            )
        else:
            lines.append("Agreement: no components available")

        # Recent performance
        rp_cfg = self._cfg.recent_performance
        short_pct = cc.get("rp_short_win_pct", 0.0)
        long_pct = cc.get("rp_long_win_pct", 0.0)
        lines.append(
            f"Recent: last-{rp_cfg.window_short} win rate {short_pct:.0f}%"
            f" | last-{rp_cfg.window_long} win rate {long_pct:.0f}%"
        )

        # Data quality sub-inputs
        sq_score = cc.get("dq_score_quality_score", 0.0)
        completeness = cc.get("dq_completeness_score", 0.0)
        freshness = cc.get("dq_freshness_score", 0.0)
        dq_composite = cc.get("dq_composite", 0.0)
        lines.append(
            f"Data quality: composite={dq_composite:.0f}"
            f" score_q={sq_score:.0f}"
            f" completeness={completeness:.1f}%"
            f" freshness={freshness:.0f}"
        )

        # Regime alignment context
        regime_dir = _REGIME_DIRECTION.get(context.regime, "NEUTRAL")
        if regime_dir == "NEUTRAL":
            alignment_label = "NEUTRAL"
        elif (score_result.direction == "LONG" and regime_dir == "BULLISH") or (
            score_result.direction == "SHORT" and regime_dir == "BEARISH"
        ):
            alignment_label = "ALIGNED"
        else:
            alignment_label = "MISALIGNED"
        lines.append(f"Regime: {context.regime.value} [{alignment_label}]")

        # Gate failure detail
        if not result.passed_gate:
            lines.append(
                f"NOT eligible for downstream:"
                f" confidence={result.final_confidence:.1f}"
                f" < threshold={self._cfg.gate.min_confidence:.0f}"
            )

        return lines
