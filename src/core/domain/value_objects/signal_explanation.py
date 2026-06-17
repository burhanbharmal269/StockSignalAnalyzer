"""SignalExplanation — deterministic, human-readable explanation of a signal.

Assembled by SignalExplanationBuilder from Score, Confidence, and Risk engine
outputs. No AI. No external calls. Pure function of engine outputs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalExplanation:
    """Immutable, deterministic explanation for a signal evaluation.

    Lines are sourced directly from engine outputs:
    - score_lines: from ScoreResult.explanation
    - confidence_lines: from ConfidenceResult.explanation
    - risk_lines: human-readable summary of RiskCheckResult entries
    - rejection_reason: populated only when the signal was rejected

    Consumers may display full_text or process individual sections.
    """

    score_lines: tuple[str, ...]
    confidence_lines: tuple[str, ...]
    risk_lines: tuple[str, ...]
    rejection_reason: str | None = None

    @property
    def full_text(self) -> str:
        parts: list[str] = []
        if self.score_lines:
            parts.append("Score:")
            parts.extend(f"  {line}" for line in self.score_lines)
        if self.confidence_lines:
            parts.append("Confidence:")
            parts.extend(f"  {line}" for line in self.confidence_lines)
        if self.risk_lines:
            parts.append("Risk:")
            parts.extend(f"  {line}" for line in self.risk_lines)
        if self.rejection_reason:
            parts.append(f"Rejected: {self.rejection_reason}")
        return "\n".join(parts)

    @property
    def is_empty(self) -> bool:
        return (
            not self.score_lines
            and not self.confidence_lines
            and not self.risk_lines
        )
