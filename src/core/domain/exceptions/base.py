"""Base domain exception hierarchy.

All domain exceptions inherit from DomainError. This allows callers to
catch all domain-layer errors with a single except clause while still
handling specific subtypes individually.

No infrastructure imports permitted in this module.
"""

from __future__ import annotations


class DomainError(Exception):
    """Root of the domain exception hierarchy.

    All business rule violations, invariant breaches, and invalid state
    transitions raise a subclass of DomainError.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.message!r})"


class ConfigurationError(DomainError):
    """Raised when a required configuration value is missing or invalid.

    Distinct from pydantic ValidationError — this is a domain-level guard
    for business configuration (risk limits, strategy weights) rather than
    type validation.
    """


class InvariantViolationError(DomainError):
    """Raised when a domain invariant is broken.

    Example: a Score value outside the 0–100 range.
    """
