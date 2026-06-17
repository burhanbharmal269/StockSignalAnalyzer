"""Unit tests for the complete 12-event risk_events schema (Phase 13 H-6 resolution)."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest

from core.domain.events.risk_events import (
    DailyLossLimitBreached,
    DataSourceUnavailable,
    DrawdownLimitBreached,
    GraduatedResponseActivated,
    HighWaterMarkUpdated,
    KillSwitchActivated,
    KillSwitchDeactivated,
    MarginAlertBreached,
    PaperModeActivated,
    RiskApproved,
    RiskRejected,
    WeeklyLossLimitBreached,
)

_NOW = datetime.now(UTC)
_SIG_ID = uuid.uuid4()


class TestRiskApproved:
    def test_construction(self) -> None:
        event = RiskApproved(
            signal_id=_SIG_ID,
            risk_decision_id=42,
            approved_lots=2,
            position_size_multiplier=1.0,
            kelly_fraction_effective=0.25,
            sizing_note=None,
        )
        assert event.risk_decision_id == 42
        assert event.approved_lots == 2
        assert event.sizing_note is None

    def test_is_frozen(self) -> None:
        event = RiskApproved(
            signal_id=_SIG_ID,
            risk_decision_id=1,
            approved_lots=1,
            position_size_multiplier=0.5,
            kelly_fraction_effective=0.25,
            sizing_note="below_minimum_samples",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.approved_lots = 5  # type: ignore[misc]

    def test_event_type_name(self) -> None:
        event = RiskApproved(
            signal_id=_SIG_ID,
            risk_decision_id=1,
            approved_lots=2,
            position_size_multiplier=1.0,
            kelly_fraction_effective=0.25,
            sizing_note=None,
        )
        assert event.event_type == "RiskApproved"

    def test_has_event_id_and_occurred_at(self) -> None:
        event = RiskApproved(
            signal_id=_SIG_ID,
            risk_decision_id=1,
            approved_lots=2,
            position_size_multiplier=1.0,
            kelly_fraction_effective=0.0,
            sizing_note="no_historical_losses",
        )
        assert isinstance(event.event_id, uuid.UUID)
        assert isinstance(event.occurred_at, datetime)


class TestRiskRejected:
    def test_construction(self) -> None:
        event = RiskRejected(
            signal_id=_SIG_ID,
            failed_check="DAILY_LOSS_LIMIT",
            reason="Daily loss limit breached",
            checks_passed_count=1,
        )
        assert event.failed_check == "DAILY_LOSS_LIMIT"
        assert event.checks_passed_count == 1

    def test_is_frozen(self) -> None:
        event = RiskRejected(
            signal_id=_SIG_ID,
            failed_check="KILL_SWITCH_ACTIVE",
            reason="Kill switch is active",
            checks_passed_count=0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.failed_check = "OTHER"  # type: ignore[misc]


class TestDailyLossLimitBreached:
    def test_construction(self) -> None:
        event = DailyLossLimitBreached(current_loss_pct=100.0, limit_pct=2.0)
        assert event.current_loss_pct == 100.0
        assert event.limit_pct == 2.0

    def test_is_frozen(self) -> None:
        event = DailyLossLimitBreached(current_loss_pct=100.0, limit_pct=2.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.current_loss_pct = 50.0  # type: ignore[misc]


class TestWeeklyLossLimitBreached:
    def test_construction(self) -> None:
        event = WeeklyLossLimitBreached(current_loss_pct=100.0, limit_pct=5.0, rolling_days=5)
        assert event.rolling_days == 5

    def test_is_frozen(self) -> None:
        event = WeeklyLossLimitBreached(current_loss_pct=100.0, limit_pct=5.0, rolling_days=5)
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.rolling_days = 7  # type: ignore[misc]


class TestDrawdownLimitBreached:
    def test_construction(self) -> None:
        event = DrawdownLimitBreached(current_drawdown_pct=10.0, limit_pct=10.0)
        assert event.current_drawdown_pct == 10.0
        assert event.limit_pct == 10.0


class TestGraduatedResponseActivated:
    def test_construction_with_state(self) -> None:
        event = GraduatedResponseActivated(
            state="REDUCED",
            daily_loss_pct=55.0,
            position_size_multiplier=0.5,
        )
        assert event.state == "REDUCED"
        assert event.position_size_multiplier == 0.5

    def test_state_field_is_present(self) -> None:
        event = GraduatedResponseActivated(
            state="KILLED", daily_loss_pct=100.0, position_size_multiplier=0.0
        )
        assert hasattr(event, "state")
        assert event.state == "KILLED"

    def test_is_frozen(self) -> None:
        event = GraduatedResponseActivated(
            state="PAPER", daily_loss_pct=80.0, position_size_multiplier=0.0
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.state = "NORMAL"  # type: ignore[misc]


class TestPaperModeActivated:
    def test_construction(self) -> None:
        event = PaperModeActivated(
            daily_loss_pct=76.0,
            paper_mode_at_pct=75.0,
            activated_at=_NOW,
        )
        assert event.paper_mode_at_pct == 75.0
        assert event.activated_at == _NOW

    def test_is_frozen(self) -> None:
        event = PaperModeActivated(daily_loss_pct=76.0, paper_mode_at_pct=75.0, activated_at=_NOW)
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.daily_loss_pct = 0.0  # type: ignore[misc]


class TestHighWaterMarkUpdated:
    def test_construction(self) -> None:
        event = HighWaterMarkUpdated(previous_hwm=500000.0, new_hwm=510000.0, updated_at=_NOW)
        assert event.new_hwm > event.previous_hwm
        assert event.updated_at == _NOW

    def test_is_frozen(self) -> None:
        event = HighWaterMarkUpdated(previous_hwm=100.0, new_hwm=200.0, updated_at=_NOW)
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.new_hwm = 300.0  # type: ignore[misc]


class TestMarginAlertBreached:
    def test_construction_with_instrument_token(self) -> None:
        event = MarginAlertBreached(
            available_margin=100000.0,
            used_margin=400000.0,
            utilization_pct=80.0,
            limit_pct=80.0,
            instrument_token=12345678,
        )
        assert event.utilization_pct == 80.0
        assert event.instrument_token == 12345678

    def test_construction_without_instrument_token(self) -> None:
        event = MarginAlertBreached(
            available_margin=100000.0,
            used_margin=400000.0,
            utilization_pct=80.0,
            limit_pct=80.0,
            instrument_token=None,
        )
        assert event.instrument_token is None

    def test_is_frozen(self) -> None:
        event = MarginAlertBreached(
            available_margin=100000.0,
            used_margin=400000.0,
            utilization_pct=80.0,
            limit_pct=80.0,
            instrument_token=None,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.utilization_pct = 0.0  # type: ignore[misc]


class TestKillSwitchActivated:
    def test_construction(self) -> None:
        event = KillSwitchActivated(
            reason="Daily loss limit hit 100%",
            activated_by="risk_engine",
            trigger_source="daily_loss_100pct",
            activated_at=_NOW,
        )
        assert event.activated_by == "risk_engine"
        assert event.trigger_source == "daily_loss_100pct"

    def test_is_frozen(self) -> None:
        event = KillSwitchActivated(
            reason="manual",
            activated_by="operator",
            trigger_source="manual",
            activated_at=_NOW,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.reason = "other"  # type: ignore[misc]

    def test_event_type_name(self) -> None:
        event = KillSwitchActivated(
            reason="r",
            activated_by="operator",
            trigger_source="manual",
            activated_at=_NOW,
        )
        assert event.event_type == "KillSwitchActivated"


class TestKillSwitchDeactivated:
    def test_construction(self) -> None:
        event = KillSwitchDeactivated(
            deactivated_by="admin_user",
            deactivated_at=_NOW,
            deactivation_note="Recovery confirmed",
            override_loss_check=False,
        )
        assert event.deactivated_by == "admin_user"
        assert event.override_loss_check is False

    def test_override_flag(self) -> None:
        event = KillSwitchDeactivated(
            deactivated_by="admin",
            deactivated_at=_NOW,
            deactivation_note="Manual override",
            override_loss_check=True,
        )
        assert event.override_loss_check is True

    def test_is_frozen(self) -> None:
        event = KillSwitchDeactivated(
            deactivated_by="admin",
            deactivated_at=_NOW,
            deactivation_note="note",
            override_loss_check=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.deactivated_by = "other"  # type: ignore[misc]


class TestDataSourceUnavailable:
    def test_construction(self) -> None:
        event = DataSourceUnavailable(
            signal_id=_SIG_ID,
            failed_source="account_state",
            failure_type="redis_error",
            evaluated_at=_NOW,
        )
        assert event.failed_source == "account_state"
        assert event.failure_type == "redis_error"

    def test_is_frozen(self) -> None:
        event = DataSourceUnavailable(
            signal_id=_SIG_ID,
            failed_source="kill_switch",
            failure_type="redis_error",
            evaluated_at=_NOW,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.failed_source = "other"  # type: ignore[misc]


class TestEventSchema:
    def test_all_12_events_importable(self) -> None:
        event_classes = [
            RiskApproved, RiskRejected, DailyLossLimitBreached, WeeklyLossLimitBreached,
            DrawdownLimitBreached, GraduatedResponseActivated, PaperModeActivated,
            HighWaterMarkUpdated, MarginAlertBreached, KillSwitchActivated,
            KillSwitchDeactivated, DataSourceUnavailable,
        ]
        assert len(event_classes) == 12

    def test_all_events_inherit_from_domain_event(self) -> None:
        from core.domain.events.base import DomainEvent
        for event_cls in [
            RiskApproved, RiskRejected, DailyLossLimitBreached, WeeklyLossLimitBreached,
            DrawdownLimitBreached, GraduatedResponseActivated, PaperModeActivated,
            HighWaterMarkUpdated, MarginAlertBreached, KillSwitchActivated,
            KillSwitchDeactivated, DataSourceUnavailable,
        ]:
            msg = f"{event_cls.__name__} must inherit DomainEvent"
            assert issubclass(event_cls, DomainEvent), msg
