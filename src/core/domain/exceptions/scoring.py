"""Domain exceptions for the Scoring Engine (Phase 11)."""

from __future__ import annotations


class ScoringError(Exception):
    """Base for all Scoring Engine errors."""


class InsufficientDataError(ScoringError):
    """Raised when available component count falls below the configured threshold."""

    def __init__(self, available: int, required_pct: float) -> None:
        super().__init__(
            f"Only {available}/7 components available "
            f"(need >= {required_pct}% completeness)"
        )
        self.available = available
        self.required_pct = required_pct


class DirectionUndecidedError(ScoringError):
    """Raised internally when direction voting produces NEUTRAL — not propagated to callers."""

    def __init__(self, long_votes: float, short_votes: float) -> None:
        super().__init__(
            f"Direction undecided: long_votes={long_votes:.1f}, "
            f"short_votes={short_votes:.1f}"
        )
        self.long_votes = long_votes
        self.short_votes = short_votes
