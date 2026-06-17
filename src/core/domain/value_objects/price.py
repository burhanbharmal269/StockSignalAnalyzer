"""Price value object — immutable Decimal wrapper.

Refuses float construction to prevent precision loss.
All arithmetic returns a new Price instance.

Rule: never store money as float. Always use Decimal or int.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


class Price:
    """Immutable monetary value. Backed by Decimal; refuses float inputs."""

    __slots__ = ("_value",)

    def __init__(self, value: Decimal | int | str) -> None:
        if isinstance(value, float):
            msg = (
                "Price cannot be constructed from float — use Decimal('1.5') or "
                "Price.from_str('1.5') to avoid precision loss."
            )
            raise TypeError(msg)
        try:
            self._value: Decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        except InvalidOperation as exc:
            msg = f"Cannot create Price from {value!r}: {exc}"
            raise ValueError(msg) from exc

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_str(cls, value: str) -> Price:
        return cls(Decimal(value))

    @classmethod
    def zero(cls) -> Price:
        return cls(Decimal("0"))

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def value(self) -> Decimal:
        return self._value

    # ------------------------------------------------------------------
    # Arithmetic (always return Price)
    # ------------------------------------------------------------------

    def __add__(self, other: Price) -> Price:
        if not isinstance(other, Price):
            return NotImplemented
        return Price(self._value + other._value)

    def __sub__(self, other: Price) -> Price:
        if not isinstance(other, Price):
            return NotImplemented
        return Price(self._value - other._value)

    def __mul__(self, scalar: Decimal | int) -> Price:
        if isinstance(scalar, float):
            msg = "Price multiplication by float is forbidden — use Decimal or int"
            raise TypeError(msg)
        return Price(self._value * Decimal(str(scalar)))

    def __truediv__(self, scalar: Decimal | int) -> Price:
        if isinstance(scalar, float):
            msg = "Price division by float is forbidden — use Decimal or int"
            raise TypeError(msg)
        return Price(self._value / Decimal(str(scalar)))

    def __neg__(self) -> Price:
        return Price(-self._value)

    def __abs__(self) -> Price:
        return Price(abs(self._value))

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Price):
            return NotImplemented
        return self._value == other._value

    def __lt__(self, other: Price) -> bool:
        if not isinstance(other, Price):
            return NotImplemented
        return self._value < other._value

    def __le__(self, other: Price) -> bool:
        return self == other or self < other

    def __gt__(self, other: Price) -> bool:
        if not isinstance(other, Price):
            return NotImplemented
        return self._value > other._value

    def __ge__(self, other: Price) -> bool:
        return self == other or self > other

    def __hash__(self) -> int:
        return hash(self._value)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Price({self._value!r})"

    def __str__(self) -> str:
        return str(self._value)
