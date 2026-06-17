"""ScoreResult — the output of the Phase 11 Scoring Engine.

Deliberately contains NO signal labels (BUY / SELL / STRONG_BUY).
Signal classification belongs to the Phase 14 Signal Engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.domain.value_objects.score_breakdown import ScoreBreakdown
from core.domain.value_objects.score_penalty import ScorePenalty

_VALID_DIRECTIONS = frozenset({"LONG", "SHORT", "NEUTRAL"})
_VALID_QUALITIES = frozenset({"HIGH", "MEDIUM", "LOW", "INSUFFICIENT"})


@dataclass(frozen=True)
class ScoreResult:
    """Aggregated scoring output from the Scoring Engine.

    Produced by ScoringEngineService after running all 7 IScoreComponent
    evaluations through ScoreCalculator. This value object is the evidence
    layer — downstream phases (Confidence Engine, Risk Engine, Signal Engine)
    consume it but do NOT modify it.
    """

    direction: str                          # "LONG" | "SHORT" | "NEUTRAL"
    direction_conviction: float             # 0.0–1.0
    raw_score: float                        # 0.0–100.0, before penalties
    adjusted_score: float                   # 0.0–100.0, after penalties clamped
    score_breakdown: ScoreBreakdown
    penalties: list[ScorePenalty]
    data_completeness_pct: float            # available / 7 × 100
    is_eligible: bool                       # completeness_pct >= threshold AND direction != NEUTRAL
    score_quality: str                      # "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT"
    weights_sha256: str                     # SHA-256 of scoring_weights.yaml
    explanation: list[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.direction not in _VALID_DIRECTIONS:
            raise ValueError(f"Invalid direction: {self.direction!r}")
        if not 0.0 <= self.direction_conviction <= 1.0:
            raise ValueError(
                f"direction_conviction {self.direction_conviction} out of [0, 1]"
            )
        if not 0.0 <= self.raw_score <= 100.0:
            raise ValueError(f"raw_score {self.raw_score} out of [0, 100]")
        if not 0.0 <= self.adjusted_score <= 100.0:
            raise ValueError(f"adjusted_score {self.adjusted_score} out of [0, 100]")
        if self.score_quality not in _VALID_QUALITIES:
            raise ValueError(f"Invalid score_quality: {self.score_quality!r}")

    @property
    def total_penalty(self) -> float:
        return sum(p.amount for p in self.penalties)
