"""Domain exceptions for signal lifecycle errors."""

from __future__ import annotations

from core.domain.exceptions.base import DomainError


class SignalStateError(DomainError):
    """Raised when an illegal signal state transition is attempted."""

    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(
            f"Invalid signal transition: {from_state!r} → {to_state!r}"
        )
        self.from_state = from_state
        self.to_state = to_state


class SignalPersistenceError(Exception):
    """Raised when a signal cannot be persisted to the database.

    This is NOT a DomainError — it is a hard infrastructure failure.
    Callers must NOT silently swallow this; fail-open is unacceptable for
    persistence. The caller should retry or surface the error.
    """


class WeakSignalError(DomainError):
    """Raised to communicate that a signal did not pass the execution gate."""

    def __init__(self, score: int | float, confidence: int | float) -> None:
        super().__init__(
            f"Signal below execution gate: score={score}, confidence={confidence} "
            "(min score=70, min confidence=65)"
        )
        self.score = score
        self.confidence = confidence
