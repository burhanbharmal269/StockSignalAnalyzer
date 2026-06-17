"""Validity — order validity duration at the exchange."""

from __future__ import annotations

from enum import StrEnum


class Validity(StrEnum):
    DAY = "DAY"  # Valid for the entire trading day
    IOC = "IOC"  # Immediate or Cancel — fill now or cancel remainder
