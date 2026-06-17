"""IScoreComponent — contract every scoring component must implement.

Each component evaluates one dimension of the FnO signal (OI, Trend,
Volume, etc.) and returns both a LONG score and a SHORT score.
The Phase 11 Scoring Engine aggregates these outputs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.component_output import ComponentOutput
    from core.domain.value_objects.score_context import ScoreContext


class IScoreComponent(ABC):
    """Base interface for all scoring components.

    Implementations are pure, stateless functions. They may not:
    - Access the database
    - Call external APIs
    - Maintain mutable state
    - Import from infrastructure layer

    All thresholds come from StrategyConfig injected at construction time.
    """

    @property
    @abstractmethod
    def component_name(self) -> str:
        """Unique identifier used in score breakdown JSONB."""

    @property
    @abstractmethod
    def max_weight(self) -> int:
        """Maximum points this component can contribute (before regime multiplier)."""

    @abstractmethod
    def evaluate(self, context: ScoreContext) -> ComponentOutput:
        """Evaluate both LONG and SHORT scores given the current market context.

        Returns a ComponentOutput with long_score, short_score, direction
        (whichever is higher), conviction, and an explanation string.
        Never raises — returns ComponentOutput.unavailable() when data is missing.
        """
