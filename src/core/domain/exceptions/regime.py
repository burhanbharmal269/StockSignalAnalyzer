"""Domain exceptions for the Market Regime Engine."""

from __future__ import annotations


class RegimeEngineError(Exception):
    """Base class for all regime engine errors."""


class InsufficientFeaturesError(RegimeEngineError):
    """Raised when mandatory indicator fields are missing from FeatureSnapshot."""


class RegimeConfigError(RegimeEngineError):
    """Raised when regime.yaml is missing, malformed, or fails Pydantic validation."""
