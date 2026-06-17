"""IScoringEngine — abstract interface for the Phase 11 Scoring Engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.score_context import ScoreContext
    from core.domain.value_objects.score_result import ScoreResult


class IScoringEngine(ABC):
    """Aggregates 7 component outputs into a composite ScoreResult.

    Implementors must NEVER raise for missing data — instead return a
    ScoreResult with is_eligible=False when data is insufficient.
    Implementors must NEVER produce trade signals, order types, or price
    levels. Output is evidence only; signal classification is Phase 14.
    """

    @abstractmethod
    async def calculate_score(self, context: ScoreContext) -> ScoreResult:
        """Evaluate all components and return a ScoreResult.

        Always returns a result — never raises. Callers should check
        ``result.is_eligible`` before forwarding downstream.
        """
