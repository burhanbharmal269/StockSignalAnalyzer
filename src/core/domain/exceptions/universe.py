"""Domain exceptions for the Universe Selection Engine."""

from __future__ import annotations

from core.domain.exceptions.base import DomainError


class UniverseSelectionError(DomainError):
    """Raised when the Universe Selection Engine cannot produce a valid candidate list."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Universe selection failed: {reason}")
        self.reason = reason


class UniverseConfigError(DomainError):
    """Raised when universe configuration is invalid (e.g. weights do not sum to 1.0)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Universe config invalid: {reason}")
        self.reason = reason
