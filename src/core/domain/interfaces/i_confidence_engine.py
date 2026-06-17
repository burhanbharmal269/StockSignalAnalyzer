"""IConfidenceEngine — abstract interface for the Phase 12 Confidence Engine.

Reference: docs/21_SIGNAL_ENGINE.md §Stage 3 — Confidence Engine
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.component_output import ComponentOutput
    from core.domain.value_objects.confidence_result import ConfidenceResult
    from core.domain.value_objects.score_context import ScoreContext
    from core.domain.value_objects.score_result import ScoreResult


class IConfidenceEngine(ABC):
    """Computes a calibrated confidence score from a ScoreResult.

    Confidence is independent of Score. A high-scoring signal may have
    low confidence (insufficient history, regime mismatch). A moderate
    signal may have high confidence (consistent pattern, aligned regime).

    Implementors must NEVER raise — return a ConfidenceResult with
    passed_gate=False when data is insufficient to warrant confidence.
    """

    @abstractmethod
    async def calculate_confidence(
        self,
        context: ScoreContext,
        score_result: ScoreResult,
        component_outputs: list[ComponentOutput],
    ) -> ConfidenceResult:
        """Run the 8-component formula and return a ConfidenceResult.

        Always returns a result — never raises. Callers check
        ``result.passed_gate`` before forwarding to the Risk Engine.
        """
