"""Domain exceptions for the Strategy Framework (Phase 10)."""

from __future__ import annotations

from core.domain.exceptions.base import DomainError


class StrategyError(DomainError):
    """Base exception for all strategy scoring errors."""


class InsufficientScoreDataError(StrategyError):
    """Raised when < 60% of components have data — signal is ineligible."""


class InvalidComponentOutputError(StrategyError):
    """Raised when a component returns an output that violates its contract."""


class StrategyConfigError(StrategyError):
    """Raised when strategy.yaml is invalid or cannot be loaded."""
