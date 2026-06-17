"""Score value object — integer percentage in [0, 100]."""

from __future__ import annotations


class Score:
    """Signal score in the range 0–100.

    Passed through the scoring pipeline as a typed container so
    callers cannot accidentally confuse score with confidence or other integers.
    """

    __slots__ = ("_value",)

    def __init__(self, value: int | float) -> None:
        if not isinstance(value, int | float):
            msg = f"Score must be int or float, got {type(value).__name__}"
            raise TypeError(msg)
        if not (0 <= value <= 100):
            msg = f"Score must be in [0, 100], got {value}"
            raise ValueError(msg)
        self._value: int | float = value

    @classmethod
    def zero(cls) -> Score:
        return cls(0)

    @classmethod
    def maximum(cls) -> Score:
        return cls(100)

    @property
    def value(self) -> int | float:
        return self._value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Score):
            return NotImplemented
        return self._value == other._value

    def __lt__(self, other: Score) -> bool:
        if not isinstance(other, Score):
            return NotImplemented
        return self._value < other._value

    def __le__(self, other: Score) -> bool:
        return self == other or self < other

    def __gt__(self, other: Score) -> bool:
        if not isinstance(other, Score):
            return NotImplemented
        return self._value > other._value

    def __ge__(self, other: Score) -> bool:
        return self == other or self > other

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"Score({self._value!r})"

    def __str__(self) -> str:
        return str(self._value)

    def passes_execution_gate(self, min_score: int = 70) -> bool:
        """Return True if this score meets the execution gate minimum."""
        return float(self._value) >= min_score
