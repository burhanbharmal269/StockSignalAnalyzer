"""Domain exceptions for the Confidence Engine (Phase 12)."""

from __future__ import annotations


class ConfidenceError(Exception):
    """Base exception for Confidence Engine failures."""


class CalibrationDataError(ConfidenceError):
    """Raised when calibration data cannot be loaded or computed."""
