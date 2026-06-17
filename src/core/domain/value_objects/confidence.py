"""Confidence value object — integer percentage in [0, 100]."""

from __future__ import annotations


class Confidence:
    """Signal confidence level in the range 0–100.

    Separate type from Score to prevent mix-ups in function signatures.
    """

    __slots__ = ("_value",)

    def __init__(self, value: int | float) -> None:
        if not isinstance(value, int | float):
            msg = f"Confidence must be int or float, got {type(value).__name__}"
            raise TypeError(msg)
        if not (0 <= value <= 100):
            msg = f"Confidence must be in [0, 100], got {value}"
            raise ValueError(msg)
        self._value: int | float = value

    @classmethod
    def zero(cls) -> Confidence:
        return cls(0)

    @property
    def value(self) -> int | float:
        return self._value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Confidence):
            return NotImplemented
        return self._value == other._value

    def __lt__(self, other: Confidence) -> bool:
        if not isinstance(other, Confidence):
            return NotImplemented
        return self._value < other._value

    def __le__(self, other: Confidence) -> bool:
        return self == other or self < other

    def __gt__(self, other: Confidence) -> bool:
        if not isinstance(other, Confidence):
            return NotImplemented
        return self._value > other._value

    def __ge__(self, other: Confidence) -> bool:
        return self == other or self > other

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"Confidence({self._value!r})"

    def __str__(self) -> str:
        return str(self._value)

    def passes_execution_gate(self, min_confidence: int = 65) -> bool:
        """Return True if this confidence meets the execution gate minimum."""
        return float(self._value) >= min_confidence
