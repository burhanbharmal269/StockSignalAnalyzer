"""Unit tests for ComponentOutput value object."""

from __future__ import annotations

import pytest

from core.domain.value_objects.component_output import ComponentOutput


def _valid(**kwargs) -> ComponentOutput:
    defaults = {
        "component_name": "TEST",
        "max_weight": 20,
        "long_score": 10.0,
        "short_score": 5.0,
        "direction": "LONG",
        "conviction": 0.5,
        "is_available": True,
        "data_freshness_seconds": 0,
        "key_finding": "test finding",
    }
    return ComponentOutput(**{**defaults, **kwargs})


class TestComponentOutputValidation:
    def test_valid_output_creates_successfully(self) -> None:
        out = _valid()
        assert out.component_name == "TEST"
        assert out.long_score == 10.0

    def test_long_score_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="long_score"):
            _valid(long_score=25.0)

    def test_short_score_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="short_score"):
            _valid(short_score=25.0)

    def test_negative_long_score_raises(self) -> None:
        with pytest.raises(ValueError, match="long_score"):
            _valid(long_score=-1.0)

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            _valid(direction="UP")

    def test_conviction_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="conviction"):
            _valid(conviction=1.5)

    def test_conviction_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="conviction"):
            _valid(conviction=-0.1)

    def test_zero_scores_valid(self) -> None:
        out = _valid(long_score=0.0, short_score=0.0, direction="NEUTRAL", conviction=0.0)
        assert out.long_score == 0.0

    def test_max_score_valid(self) -> None:
        out = _valid(long_score=20.0, short_score=0.0, conviction=1.0)
        assert out.long_score == 20.0


class TestComponentOutputUnavailable:
    def test_unavailable_factory_returns_zero_scores(self) -> None:
        out = ComponentOutput.unavailable("TEST", 20, "no data")
        assert out.long_score == 0.0
        assert out.short_score == 0.0
        assert not out.is_available
        assert out.direction == "NEUTRAL"
        assert out.conviction == 0.0

    def test_unavailable_key_finding_contains_reason(self) -> None:
        out = ComponentOutput.unavailable("TEST", 20, "my reason")
        assert "my reason" in out.key_finding

    def test_unavailable_metadata_has_reason(self) -> None:
        out = ComponentOutput.unavailable("TEST", 20, "some reason")
        assert out.metadata["reason"] == "some reason"


class TestComponentOutputImmutability:
    def test_output_is_frozen(self) -> None:
        out = _valid()
        with pytest.raises((AttributeError, TypeError)):
            out.long_score = 99.0  # type: ignore[misc]
