"""SignalResult — output of SignalEngineService.process().

Returned for every processed SignalRequest regardless of acceptance or
rejection. Callers check `accepted` first; rejected results carry a
`rejection_reason` and partial engine outputs for observability.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.domain.enums.signal_rejection_reason import SignalRejectionReason
from core.domain.value_objects.signal_explanation import SignalExplanation

if TYPE_CHECKING:
    from core.domain.value_objects.score_breakdown import ScoreBreakdown


@dataclass(frozen=True)
class SignalResult:
    """Complete output from one SignalEngineService.process() call.

    Invariants:
    - accepted=True  → signal_id is set, rejection_reason is None
    - accepted=False → rejection_reason is set, signal_id may or may not be set
    - is_duplicate=True → accepted is always False
    """

    accepted: bool
    signal_id: uuid.UUID | None
    rejection_reason: SignalRejectionReason | None
    explanation: SignalExplanation | None
    is_duplicate: bool

    # Observability fields — populated whenever engines ran
    adjusted_score: float | None = None
    final_confidence: float | None = None
    risk_approved: bool = False
    position_size_lots: int | None = None

    # Component score breakdown — populated when scoring ran successfully
    direction: str | None = None          # "LONG" | "SHORT" | "NEUTRAL"
    score_breakdown: "ScoreBreakdown | None" = None
