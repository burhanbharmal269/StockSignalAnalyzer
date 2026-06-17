"""Unit tests for RiskDecision, RiskRejectionCode, RiskCheckResult, and SizingResult."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest

from core.domain.exceptions.risk import RiskInvariantError
from core.domain.risk.risk_decision import (
    RiskCheckResult,
    RiskDecision,
    RiskRejectionCode,
    SizingResult,
)

_NOW = datetime.now(UTC)
_SIG_ID = uuid.uuid4()
_SENTINEL_ACCOUNT = object()


def _make_check(**overrides: object) -> RiskCheckResult:
    defaults: dict[str, object] = {
        "check_name": "DailyLoss",
        "passed": True,
        "current_value": 30.0,
        "limit_value": 100.0,
        "message": "Daily loss within limits",
    }
    defaults.update(overrides)
    return RiskCheckResult(**defaults)  # type: ignore[arg-type]


def _make_sizing(**overrides: object) -> SizingResult:
    defaults: dict[str, object] = {
        "lots": 2,
        "atr_lots_pre_cap": 3,
        "kelly_lots_pre_cap": 2,
        "kelly_fraction_effective": 0.25,
        "kelly_sample_count": 50,
        "sizing_note": None,
    }
    defaults.update(overrides)
    return SizingResult(**defaults)  # type: ignore[arg-type]


def _make_approved(**overrides: object) -> RiskDecision:
    defaults: dict[str, object] = {
        "signal_id": _SIG_ID,
        "approved": True,
        "rejection_code": None,
        "rejection_reason": None,
        "position_size_lots": 2,
        "size_reduction_pct": 0.0,
        "checks": (_make_check(),),
        "sizing": _make_sizing(),
        "account_snapshot": _SENTINEL_ACCOUNT,
        "failed_data_sources": (),
        "risk_decision_id": None,
        "evaluated_at": _NOW,
    }
    defaults.update(overrides)
    return RiskDecision(**defaults)  # type: ignore[arg-type]


def _make_rejected(**overrides: object) -> RiskDecision:
    defaults: dict[str, object] = {
        "signal_id": _SIG_ID,
        "approved": False,
        "rejection_code": RiskRejectionCode.DAILY_LOSS_LIMIT,
        "rejection_reason": "Daily loss limit breached",
        "position_size_lots": None,
        "size_reduction_pct": 0.0,
        "checks": (_make_check(passed=False, message="FAIL"),),
        "sizing": None,
        "account_snapshot": _SENTINEL_ACCOUNT,
        "failed_data_sources": (),
        "risk_decision_id": None,
        "evaluated_at": _NOW,
    }
    defaults.update(overrides)
    return RiskDecision(**defaults)  # type: ignore[arg-type]


class TestRiskRejectionCode:
    def test_all_20_codes_exist(self) -> None:
        codes = {code.value for code in RiskRejectionCode}
        expected = {
            "KILL_SWITCH_ACTIVE", "DATA_SOURCE_UNAVAILABLE", "AUDIT_PERSISTENCE_FAILURE",
            "AUDIT_PERSISTENCE_TIMEOUT", "GREEKS_UNAVAILABLE", "MARGIN_DATA_UNAVAILABLE",
            "UNSUPPORTED_INSTRUMENT_CLASS", "DAILY_LOSS_LIMIT", "WEEKLY_LOSS_LIMIT",
            "DRAWDOWN_LIMIT", "MAX_OPEN_POSITIONS", "SYMBOL_CONCENTRATION",
            "CAPITAL_CONCENTRATION", "NET_DELTA_LIMIT", "CORRELATION_LIMIT", "VEGA_LIMIT",
            "INSUFFICIENT_MARGIN", "RISK_REWARD_BELOW_MINIMUM", "ORDER_RATE_LIMIT",
            "POSITION_SIZE_ZERO",
        }
        assert codes == expected

    def test_is_str_subtype(self) -> None:
        code = RiskRejectionCode.KILL_SWITCH_ACTIVE
        assert isinstance(code, str)
        assert code == "KILL_SWITCH_ACTIVE"

    def test_json_serializable_without_custom_encoder(self) -> None:
        import json
        code = RiskRejectionCode.DAILY_LOSS_LIMIT
        result = json.dumps({"code": code})
        assert '"DAILY_LOSS_LIMIT"' in result


class TestRiskCheckResult:
    def test_valid_passed_check(self) -> None:
        check = _make_check()
        assert check.passed is True
        assert check.is_warning is False

    def test_warning_flag(self) -> None:
        check = _make_check(is_warning=True, check_name="ThetaDecay")
        assert check.is_warning is True

    def test_empty_check_name_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="check_name"):
            _make_check(check_name="")

    def test_none_current_value_allowed(self) -> None:
        check = _make_check(current_value=None, limit_value=None)
        assert check.current_value is None

    def test_is_hard_failure_when_failed_and_not_warning(self) -> None:
        check = _make_check(passed=False, is_warning=False)
        assert check.is_hard_failure is True

    def test_not_hard_failure_when_passed_true(self) -> None:
        check = _make_check(passed=True, is_warning=False)
        assert check.is_hard_failure is False

    def test_not_hard_failure_when_warning_even_if_failed(self) -> None:
        check = _make_check(passed=False, is_warning=True, check_name="ThetaDecay")
        assert check.is_hard_failure is False

    def test_not_hard_failure_when_passed_and_is_warning(self) -> None:
        check = _make_check(passed=True, is_warning=True, check_name="ThetaDecay")
        assert check.is_hard_failure is False


class TestSizingResult:
    def test_valid_sizing(self) -> None:
        sizing = _make_sizing()
        assert sizing.lots == 2
        assert sizing.kelly_fraction_effective == 0.25

    def test_negative_lots_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="lots"):
            _make_sizing(lots=-1)

    def test_negative_atr_lots_pre_cap_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="atr_lots_pre_cap"):
            _make_sizing(atr_lots_pre_cap=-1)

    def test_negative_kelly_lots_pre_cap_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="kelly_lots_pre_cap"):
            _make_sizing(kelly_lots_pre_cap=-1)

    def test_kelly_fraction_above_1_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="kelly_fraction_effective"):
            _make_sizing(kelly_fraction_effective=1.1)

    def test_kelly_fraction_below_0_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="kelly_fraction_effective"):
            _make_sizing(kelly_fraction_effective=-0.01)

    def test_negative_sample_count_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="kelly_sample_count"):
            _make_sizing(kelly_sample_count=-1)

    def test_zero_lots_valid(self) -> None:
        sizing = _make_sizing(lots=0)
        assert sizing.lots == 0

    def test_sizing_note_variants(self) -> None:
        for note in (None, "below_minimum_samples", "no_historical_losses"):
            sizing = _make_sizing(sizing_note=note)
            assert sizing.sizing_note == note


class TestRiskDecision:
    def test_valid_approved_decision(self) -> None:
        decision = _make_approved()
        assert decision.approved is True
        assert decision.rejection_code is None
        assert decision.position_size_lots == 2

    def test_valid_rejected_decision(self) -> None:
        decision = _make_rejected()
        assert decision.approved is False
        assert decision.rejection_code == RiskRejectionCode.DAILY_LOSS_LIMIT

    def test_approved_with_rejection_code_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="rejection_code"):
            _make_approved(rejection_code=RiskRejectionCode.DAILY_LOSS_LIMIT)

    def test_approved_with_none_lots_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="position_size_lots"):
            _make_approved(position_size_lots=None)

    def test_approved_with_zero_lots_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="approved_lots"):
            _make_approved(position_size_lots=0)

    def test_rejected_without_rejection_code_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="rejection_code"):
            _make_rejected(rejection_code=None)

    def test_invalid_size_reduction_pct_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="size_reduction_pct"):
            _make_approved(size_reduction_pct=25.0)

    def test_valid_size_reduction_pct_values(self) -> None:
        for pct in (0.0, 50.0):
            decision = _make_approved(size_reduction_pct=pct)
            assert decision.size_reduction_pct == pct

    def test_risk_decision_id_zero_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="risk_decision_id"):
            _make_approved(risk_decision_id=0)

    def test_risk_decision_id_negative_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="risk_decision_id"):
            _make_approved(risk_decision_id=-1)

    def test_risk_decision_id_set_after_insert(self) -> None:
        decision = _make_approved(risk_decision_id=42)
        assert decision.risk_decision_id == 42

    def test_checks_is_tuple(self) -> None:
        decision = _make_approved()
        assert isinstance(decision.checks, tuple)

    def test_failed_data_sources_is_tuple(self) -> None:
        decision = _make_rejected(failed_data_sources=("account_state",))
        assert isinstance(decision.failed_data_sources, tuple)
        assert decision.failed_data_sources == ("account_state",)

    def test_is_frozen(self) -> None:
        decision = _make_approved()
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.approved = False  # type: ignore[misc]
