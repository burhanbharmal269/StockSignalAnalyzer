"""Domain exceptions for the Risk Engine (Phase 13).

All exceptions inherit from DomainError so callers can catch the full
domain exception hierarchy with a single except clause.

No infrastructure imports permitted in this module.
"""

from __future__ import annotations

from core.domain.exceptions.base import DomainError


class RiskError(DomainError):
    """Base exception for Risk Engine failures."""


class RiskInvariantError(RiskError):
    """Raised when a domain value object fails an invariant check in __post_init__."""


class RiskDecisionPersistenceError(RiskError):
    """Raised when the risk_decisions INSERT fails or the connection is lost."""


class DataSourceUnavailableError(RiskError):
    """Raised when a required data source (Redis key or broker API) is unavailable.

    Args:
        source:  Identifies which data source failed (e.g. 'account_state', 'margin_api').
        message: Human-readable description of the failure.
    """

    def __init__(self, source: str, message: str) -> None:
        super().__init__(message)
        self.source = source


class MarginDataUnavailableError(DataSourceUnavailableError):
    """Raised when the broker margin API is unreachable or times out.

    Inherits DataSourceUnavailableError.source so callers receive the API
    endpoint name alongside the exception.
    """


class GreeksUnavailableError(DataSourceUnavailableError):
    """Raised when both the primary and fallback Greeks cache tiers miss
    for a position that has exceeded the new-position grace period.
    """


class ConcurrentEvaluationError(RiskError):
    """Raised when RiskEngineService.evaluate() is called while another
    evaluation is already in progress (lock is contested via direct call).

    This exception signals a design violation — the event consumer must
    maintain parallelism = 1.
    """


class UnsupportedInstrumentClassError(RiskError):
    """Raised when a RiskRequest contains an instrument class the Risk Engine
    cannot evaluate in Phase 13 (e.g. EQUITY).
    """
