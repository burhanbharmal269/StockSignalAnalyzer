"""ComponentOutput — the return value of every IScoreComponent.evaluate() call.

Each component produces both long_score and short_score independently.
The Phase 11 Scoring Engine aggregates these into a direction vote and
composite signal score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class ComponentOutput:
    """Immutable result from a single scoring component.

    long_score  — evidence for a LONG (bullish) position  (0 to max_weight)
    short_score — evidence for a SHORT (bearish) position (0 to max_weight)

    Components always evaluate both sides independently so the Phase 11
    direction voting can use the full distribution.
    """

    component_name: str
    max_weight: int

    long_score: float               # 0.0 to max_weight
    short_score: float              # 0.0 to max_weight

    direction: str                  # "LONG" | "SHORT" | "NEUTRAL"
    conviction: float               # 0.0-1.0 — how confident the component is

    is_available: bool              # False when required data was missing
    data_freshness_seconds: int     # Age of oldest data used (0 if not tracked)

    key_finding: str                # One-line explanation for signal output
    metadata: dict = field(default_factory=dict)  # Component-specific values

    evaluation_timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    def __post_init__(self) -> None:
        if not (0.0 <= self.long_score <= self.max_weight):
            msg = (
                f"{self.component_name}: long_score {self.long_score} "
                f"out of range [0, {self.max_weight}]"
            )
            raise ValueError(msg)
        if not (0.0 <= self.short_score <= self.max_weight):
            msg = (
                f"{self.component_name}: short_score {self.short_score} "
                f"out of range [0, {self.max_weight}]"
            )
            raise ValueError(msg)
        if self.direction not in ("LONG", "SHORT", "NEUTRAL"):
            msg = f"{self.component_name}: invalid direction '{self.direction}'"
            raise ValueError(msg)
        if not (0.0 <= self.conviction <= 1.0):
            msg = f"{self.component_name}: conviction {self.conviction} out of range [0, 1]"
            raise ValueError(msg)

    @classmethod
    def unavailable(cls, component_name: str, max_weight: int, reason: str) -> ComponentOutput:
        """Factory for when data is missing — contributes zero to both directions."""
        return cls(
            component_name=component_name,
            max_weight=max_weight,
            long_score=0.0,
            short_score=0.0,
            direction="NEUTRAL",
            conviction=0.0,
            is_available=False,
            data_freshness_seconds=0,
            key_finding=f"INSUFFICIENT_DATA: {reason}",
            metadata={"reason": reason},
        )
