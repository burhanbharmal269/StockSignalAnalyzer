"""Unit tests for SqlAlchemyRiskDecisionRepository.

All tests use AsyncMock for the session_factory — no real DB connection is
required.  Tests cover: core contract, JSONB serialization correctness, RC-2
(portfolio_snapshot nullable), RC-5 (no internal timeout enforcement), error
mapping, and append-only invariants.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from core.domain.exceptions.risk import RiskDecisionPersistenceError
from core.domain.risk.account_state import AccountState
from core.domain.risk.risk_decision import (
    RiskCheckResult,
    RiskDecision,
    RiskRejectionCode,
    SizingResult,
)
from core.infrastructure.database.models.risk_models import RiskDecisionModel
from core.infrastructure.database.repositories.risk_decision_repository import (
    SqlAlchemyRiskDecisionRepository,
)

_SIG_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_EVAL_AT = datetime(2026, 6, 14, 9, 16, 0, tzinfo=UTC)
_CAPTURED_AT = datetime(2026, 6, 14, 9, 15, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    # add() is synchronous in SQLAlchemy — use MagicMock to avoid coroutine warnings
    session.add = MagicMock()
    _counter = [0]

    async def _set_pk_on_flush() -> None:
        if session.add.called:
            obj = session.add.call_args[0][0]
            if hasattr(obj, "id"):
                _counter[0] += 1
                obj.id = _counter[0]

    session.flush = AsyncMock(side_effect=_set_pk_on_flush)
    return session


@pytest.fixture
def session_factory(mock_session: AsyncMock) -> MagicMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=cm)
    return factory


@pytest.fixture
def repo(session_factory: MagicMock) -> SqlAlchemyRiskDecisionRepository:
    return SqlAlchemyRiskDecisionRepository(session_factory=session_factory)


@pytest.fixture
def account_state() -> AccountState:
    return AccountState(
        account_capital=Decimal("500000"),
        session_capital=Decimal("500000"),
        available_margin=Decimal("400000"),
        used_margin=Decimal("100000"),
        margin_utilization_pct=20.0,
        daily_pnl=Decimal("0"),
        daily_loss_consumed_pct=0.0,
        weekly_pnl=Decimal("0"),
        weekly_loss_consumed_pct=0.0,
        drawdown_from_hwm_pct=0.0,
        open_positions_count=2,
        position_size_multiplier=1.0,
        trading_mode="LIVE",
        captured_at=_CAPTURED_AT,
    )


def _pass_check(name: str = "KillSwitch") -> RiskCheckResult:
    return RiskCheckResult(
        check_name=name,
        passed=True,
        current_value=None,
        limit_value=None,
        message="passed",
    )


def _fail_check(name: str = "KillSwitch") -> RiskCheckResult:
    return RiskCheckResult(
        check_name=name,
        passed=False,
        current_value=None,
        limit_value=None,
        message="kill switch active",
    )


@pytest.fixture
def sizing() -> SizingResult:
    return SizingResult(
        lots=2,
        atr_lots_pre_cap=3,
        kelly_lots_pre_cap=4,
        kelly_fraction_effective=0.5,
        kelly_sample_count=100,
        sizing_note=None,
    )


@pytest.fixture
def approved_decision(account_state: AccountState, sizing: SizingResult) -> RiskDecision:
    return RiskDecision(
        signal_id=_SIG_ID,
        approved=True,
        rejection_code=None,
        rejection_reason=None,
        position_size_lots=2,
        size_reduction_pct=0.0,
        checks=(_pass_check(),),
        sizing=sizing,
        account_snapshot=account_state,
        failed_data_sources=(),
        risk_decision_id=None,
        evaluated_at=_EVAL_AT,
    )


@pytest.fixture
def rejected_decision(account_state: AccountState) -> RiskDecision:
    return RiskDecision(
        signal_id=_SIG_ID,
        approved=False,
        rejection_code=RiskRejectionCode.KILL_SWITCH_ACTIVE,
        rejection_reason="Kill switch is active",
        position_size_lots=None,
        size_reduction_pct=0.0,
        checks=(_fail_check(),),
        sizing=None,
        account_snapshot=account_state,
        failed_data_sources=("kill_switch",),
        risk_decision_id=None,
        evaluated_at=_EVAL_AT,
    )


def _get_added_orm(mock_session: AsyncMock) -> RiskDecisionModel:
    return mock_session.add.call_args[0][0]


# ---------------------------------------------------------------------------
# Core contract
# ---------------------------------------------------------------------------


class TestCoreContract:
    async def test_insert_approved_decision_returns_positive_id(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
    ) -> None:
        result = await repo.insert(approved_decision, timeout_seconds=5.0)
        assert result == 1

    async def test_insert_rejected_decision_returns_positive_id(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        rejected_decision: RiskDecision,
    ) -> None:
        result = await repo.insert(rejected_decision, timeout_seconds=5.0)
        assert result == 1

    async def test_sequential_inserts_return_distinct_ids(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
    ) -> None:
        id1 = await repo.insert(approved_decision, timeout_seconds=5.0)
        id2 = await repo.insert(approved_decision, timeout_seconds=5.0)
        assert id1 != id2
        assert id1 == 1
        assert id2 == 2


# ---------------------------------------------------------------------------
# Serialization: primitive fields
# ---------------------------------------------------------------------------


class TestPrimitiveFieldSerialization:
    async def test_signal_id_stored_as_uuid_object(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        orm = _get_added_orm(mock_session)
        assert orm.signal_id == _SIG_ID

    async def test_approved_true_stored(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).approved is True

    async def test_approved_false_stored(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        rejected_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(rejected_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).approved is False

    async def test_rejection_code_stored_as_string_value(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        rejected_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(rejected_decision, timeout_seconds=5.0)
        orm = _get_added_orm(mock_session)
        assert orm.rejection_code == "KILL_SWITCH_ACTIVE"

    async def test_none_rejection_code_stored_as_none(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).rejection_code is None

    async def test_evaluated_at_stored_from_decision(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).evaluated_at == _EVAL_AT


# ---------------------------------------------------------------------------
# Serialization: JSONB fields
# ---------------------------------------------------------------------------


class TestJsonbSerialization:
    async def test_checks_serialised_as_list_of_dicts(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        checks = _get_added_orm(mock_session).checks
        assert isinstance(checks, list)
        assert isinstance(checks[0], dict)

    async def test_check_dict_contains_required_fields(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        check_dict = _get_added_orm(mock_session).checks[0]
        assert "check_name" in check_dict
        assert "passed" in check_dict
        assert "current_value" in check_dict
        assert "limit_value" in check_dict
        assert "message" in check_dict
        assert "is_warning" in check_dict

    async def test_check_dict_excludes_is_hard_failure_property(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        check_dict = _get_added_orm(mock_session).checks[0]
        assert "is_hard_failure" not in check_dict

    async def test_account_snapshot_decimal_fields_as_strings(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        snap = _get_added_orm(mock_session).account_snapshot
        assert snap["account_capital"] == "500000"
        assert snap["session_capital"] == "500000"
        assert snap["available_margin"] == "400000"

    async def test_account_snapshot_datetime_as_iso8601(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        snap = _get_added_orm(mock_session).account_snapshot
        assert snap["captured_at"] == _CAPTURED_AT.isoformat()

    async def test_sizing_snapshot_stored_as_dict_when_present(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        snap = _get_added_orm(mock_session).sizing_snapshot
        assert isinstance(snap, dict)
        assert snap["lots"] == 2

    async def test_sizing_snapshot_null_when_none(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        rejected_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(rejected_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).sizing_snapshot is None

    async def test_failed_data_sources_serialised_as_list(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        rejected_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(rejected_decision, timeout_seconds=5.0)
        sources = _get_added_orm(mock_session).failed_data_sources
        assert sources == ["kill_switch"]

    async def test_empty_failed_data_sources_stored_as_empty_list(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).failed_data_sources == []


# ---------------------------------------------------------------------------
# RC-2: portfolio_snapshot is NULL in Phase C
# ---------------------------------------------------------------------------


class TestRC2PortfolioSnapshot:
    async def test_portfolio_snapshot_column_is_none(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).portfolio_snapshot is None

    async def test_insert_with_null_portfolio_snapshot_does_not_raise(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
    ) -> None:
        result = await repo.insert(approved_decision, timeout_seconds=5.0)
        assert result >= 1


# ---------------------------------------------------------------------------
# New columns: risk_config_version, risk_config_sha256, evaluation_duration_ms
# ---------------------------------------------------------------------------


class TestPhaseCAuditColumns:
    async def test_risk_config_version_is_none(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).risk_config_version is None

    async def test_risk_config_sha256_is_none(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).risk_config_sha256 is None

    async def test_evaluation_duration_ms_is_none(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        await repo.insert(approved_decision, timeout_seconds=5.0)
        assert _get_added_orm(mock_session).evaluation_duration_ms is None


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    async def test_operational_error_raises_persistence_error(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        mock_session.flush.side_effect = OperationalError("conn lost", {}, Exception())
        with pytest.raises(RiskDecisionPersistenceError):
            await repo.insert(approved_decision, timeout_seconds=5.0)

    async def test_integrity_error_raises_persistence_error(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        mock_session.flush.side_effect = IntegrityError("constraint", {}, Exception())
        with pytest.raises(RiskDecisionPersistenceError):
            await repo.insert(approved_decision, timeout_seconds=5.0)

    async def test_persistence_error_preserves_original_cause(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
        mock_session: AsyncMock,
    ) -> None:
        original = OperationalError("conn lost", {}, Exception())
        mock_session.flush.side_effect = original
        with pytest.raises(RiskDecisionPersistenceError) as exc_info:
            await repo.insert(approved_decision, timeout_seconds=5.0)
        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# RC-5: no internal timeout enforcement
# ---------------------------------------------------------------------------


class TestRC5NoTimeoutEnforcement:
    async def test_tiny_timeout_does_not_self_cancel(
        self,
        repo: SqlAlchemyRiskDecisionRepository,
        approved_decision: RiskDecision,
    ) -> None:
        # timeout_seconds=0.0001 must NOT cause TimeoutError from the repo itself
        result = await repo.insert(approved_decision, timeout_seconds=0.0001)
        assert result == 1

    def test_no_asyncio_import_in_repository_module(self) -> None:
        import core.infrastructure.database.repositories.risk_decision_repository as mod

        source = inspect.getsource(mod)
        assert "import asyncio" not in source

    def test_timeout_seconds_parameter_accepted(self) -> None:
        sig = inspect.signature(
            SqlAlchemyRiskDecisionRepository.insert
        )
        assert "timeout_seconds" in sig.parameters


# ---------------------------------------------------------------------------
# Append-only invariants
# ---------------------------------------------------------------------------


class TestAppendOnlyInvariants:
    def test_no_update_method(
        self, repo: SqlAlchemyRiskDecisionRepository
    ) -> None:
        assert not hasattr(repo, "update")

    def test_no_delete_method(
        self, repo: SqlAlchemyRiskDecisionRepository
    ) -> None:
        assert not hasattr(repo, "delete")

    def test_no_update_all_method(
        self, repo: SqlAlchemyRiskDecisionRepository
    ) -> None:
        assert not hasattr(repo, "update_all")

    def test_no_delete_all_method(
        self, repo: SqlAlchemyRiskDecisionRepository
    ) -> None:
        assert not hasattr(repo, "delete_all")

    def test_no_get_method(
        self, repo: SqlAlchemyRiskDecisionRepository
    ) -> None:
        assert not hasattr(repo, "get")

    def test_no_list_method(
        self, repo: SqlAlchemyRiskDecisionRepository
    ) -> None:
        assert not hasattr(repo, "list")
