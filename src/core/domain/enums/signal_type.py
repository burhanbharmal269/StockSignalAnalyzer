"""SignalType — direction of a trading signal."""

from __future__ import annotations

from enum import StrEnum


class SignalType(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
