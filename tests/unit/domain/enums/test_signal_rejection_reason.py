"""Unit tests for SignalRejectionReason enum."""

from __future__ import annotations

from core.domain.enums.signal_rejection_reason import SignalRejectionReason


class TestSignalRejectionReason:
    def test_all_values_are_strings(self) -> None:
        for member in SignalRejectionReason:
            assert isinstance(member.value, str)

    def test_expected_members(self) -> None:
        members = {m.value for m in SignalRejectionReason}
        assert "DUPLICATE" in members
        assert "SCORE_INELIGIBLE" in members
        assert "WEAK_SIGNAL" in members
        assert "RISK_REJECTED" in members
        assert "EXPIRED" in members

    def test_str_equality(self) -> None:
        assert SignalRejectionReason.DUPLICATE == "DUPLICATE"
        assert SignalRejectionReason.WEAK_SIGNAL == "WEAK_SIGNAL"
