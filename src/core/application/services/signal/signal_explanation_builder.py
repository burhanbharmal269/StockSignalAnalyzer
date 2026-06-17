"""SignalExplanationBuilder — deterministic signal explanation assembly.

Combines lines from Score, Confidence, and Risk engine outputs into a
SignalExplanation. No AI. No external calls. Pure function of engine outputs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.value_objects.signal_explanation import SignalExplanation

if TYPE_CHECKING:
    from core.domain.risk.risk_decision import RiskDecision
    from core.domain.value_objects.confidence_result import ConfidenceResult
    from core.domain.value_objects.score_result import ScoreResult


class SignalExplanationBuilder:
    """Assembles a SignalExplanation from engine outputs.

    All inputs are optional so partial explanations can be built when
    processing stops early (e.g. score ineligible → no confidence output).
    """

    def build(
        self,
        score_result: ScoreResult | None = None,
        confidence_result: ConfidenceResult | None = None,
        risk_decision: RiskDecision | None = None,
        rejection_reason: str | None = None,
    ) -> SignalExplanation:
        score_lines = self._score_lines(score_result)
        confidence_lines = self._confidence_lines(confidence_result)
        risk_lines = self._risk_lines(risk_decision)
        return SignalExplanation(
            score_lines=tuple(score_lines),
            confidence_lines=tuple(confidence_lines),
            risk_lines=tuple(risk_lines),
            rejection_reason=rejection_reason,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _score_lines(self, result: ScoreResult | None) -> list[str]:
        if result is None:
            return []
        lines: list[str] = list(result.explanation)
        lines.append(
            f"direction={result.direction} score={result.adjusted_score:.1f} "
            f"quality={result.score_quality} "
            f"completeness={result.data_completeness_pct:.0f}%"
        )
        return lines

    def _confidence_lines(self, result: ConfidenceResult | None) -> list[str]:
        if result is None:
            return []
        lines: list[str] = list(result.explanation)
        lines.append(
            f"final_confidence={result.final_confidence:.1f} "
            f"score_bucket={result.score_bucket} "
            f"gate={'PASSED' if result.passed_gate else 'FAILED'}"
        )
        return lines

    def _risk_lines(self, decision: RiskDecision | None) -> list[str]:
        if decision is None:
            return []
        lines: list[str] = []
        for check in decision.checks:
            status = "PASS" if check.passed else ("WARN" if check.is_warning else "FAIL")
            lines.append(f"[{status}] {check.check_name}: {check.message}")
        if decision.approved:
            lines.append(f"APPROVED — {decision.position_size_lots} lot(s)")
        else:
            lines.append(f"REJECTED — {decision.rejection_code}: {decision.rejection_reason}")
        return lines
