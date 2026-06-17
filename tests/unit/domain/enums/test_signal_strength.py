"""Unit tests for SignalStrength enum."""

from __future__ import annotations

from core.domain.enums.signal_strength import SignalStrength


class TestSignalStrength:
    def test_values(self) -> None:
        assert SignalStrength.STRONG == "STRONG"
        assert SignalStrength.STANDARD == "STANDARD"

    def test_membership(self) -> None:
        assert "STRONG" in [s.value for s in SignalStrength]
        assert "STANDARD" in [s.value for s in SignalStrength]

    def test_count(self) -> None:
        assert len(SignalStrength) == 2
