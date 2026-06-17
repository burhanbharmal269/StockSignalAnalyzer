"""ScorePenalty — a single deduction applied to raw_score."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScorePenalty:
    """An individual score deduction computed by ScoreCalculator.

    ``amount`` is always <= 0.0. ``component_name`` is populated only for
    DATA_STALENESS penalties, where one penalty is raised per stale component.
    """

    # DATA_STALENESS | LOW_CONVICTION | MARKET_HOURS | REGIME_MISMATCH | EXPIRY_RISK
    penalty_type: str
    amount: float           # <= 0.0
    reason: str
    component_name: str | None = None

    def __post_init__(self) -> None:
        if self.amount > 0.0:
            raise ValueError(f"ScorePenalty.amount must be <= 0, got {self.amount}")
        valid_types = {
            "DATA_STALENESS",
            "LOW_CONVICTION",
            "MARKET_HOURS",
            "REGIME_MISMATCH",
            "EXPIRY_RISK",
        }
        if self.penalty_type not in valid_types:
            raise ValueError(f"Unknown penalty_type: {self.penalty_type!r}")
