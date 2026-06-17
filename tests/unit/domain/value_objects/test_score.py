"""Unit tests for Score and Confidence value objects."""

from __future__ import annotations

import pytest

from core.domain.value_objects.confidence import Confidence
from core.domain.value_objects.score import Score


class TestScore:
    def test_valid_int_score(self) -> None:
        s = Score(85)
        assert s.value == 85

    def test_valid_float_score(self) -> None:
        s = Score(72.5)
        assert s.value == 72.5

    def test_zero_is_valid(self) -> None:
        assert Score(0).value == 0

    def test_100_is_valid(self) -> None:
        assert Score(100).value == 100

    def test_below_zero_raises(self) -> None:
        with pytest.raises(ValueError):
            Score(-1)

    def test_above_100_raises(self) -> None:
        with pytest.raises(ValueError):
            Score(101)

    def test_string_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            Score("85")  # type: ignore[arg-type]

    def test_zero_factory(self) -> None:
        assert Score.zero().value == 0

    def test_maximum_factory(self) -> None:
        assert Score.maximum().value == 100

    def test_passes_execution_gate_true(self) -> None:
        assert Score(70).passes_execution_gate() is True

    def test_passes_execution_gate_exactly_70(self) -> None:
        assert Score(70).passes_execution_gate() is True

    def test_fails_execution_gate_69(self) -> None:
        assert Score(69).passes_execution_gate() is False

    def test_equality(self) -> None:
        assert Score(80) == Score(80)

    def test_inequality(self) -> None:
        assert Score(80) != Score(81)

    def test_less_than(self) -> None:
        assert Score(70) < Score(80)

    def test_greater_than(self) -> None:
        assert Score(80) > Score(70)

    def test_hashable(self) -> None:
        scores = {Score(80), Score(80), Score(90)}
        assert len(scores) == 2

    def test_repr(self) -> None:
        assert "80" in repr(Score(80))


class TestConfidence:
    def test_valid_confidence(self) -> None:
        c = Confidence(75)
        assert c.value == 75

    def test_below_zero_raises(self) -> None:
        with pytest.raises(ValueError):
            Confidence(-1)

    def test_above_100_raises(self) -> None:
        with pytest.raises(ValueError):
            Confidence(101)

    def test_passes_gate_65(self) -> None:
        assert Confidence(65).passes_execution_gate() is True

    def test_fails_gate_64(self) -> None:
        assert Confidence(64).passes_execution_gate() is False

    def test_equality(self) -> None:
        assert Confidence(70) == Confidence(70)

    def test_less_than(self) -> None:
        assert Confidence(60) < Confidence(70)
