"""Unit tests — RiskProfileService."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.risk_profile_service import RiskProfileService
from core.domain.entities.risk_profile import RiskProfile
from core.domain.enums.risk_profile_type import RiskProfileType
from core.domain.enums.universe_scope import UniverseScope


def _make_repo(
    active: RiskProfile | None = None,
    by_id: RiskProfile | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.get_active = AsyncMock(return_value=active)
    repo.get_by_id = AsyncMock(return_value=by_id)
    repo.list_all = AsyncMock(return_value=[])
    repo.deactivate_all = AsyncMock()
    return repo


def _make_service(repo: MagicMock | None = None) -> RiskProfileService:
    return RiskProfileService(repository=repo or _make_repo())


def _moderate_profile() -> RiskProfile:
    p = RiskProfile.moderate()
    p.activate()
    return p


class TestCreateRiskProfile:
    async def test_create_saves_profile(self) -> None:
        repo = _make_repo()
        service = _make_service(repo)
        p = await service.create(
            name="Test",
            profile_type=RiskProfileType.MODERATE,
            universe_scope=UniverseScope.ALL_FNO,
            risk_per_trade_pct=Decimal("2.0"),
            max_open_positions=5,
            daily_loss_pct=Decimal("3.0"),
            weekly_loss_pct=Decimal("8.0"),
            drawdown_pct=Decimal("12.0"),
            max_position_size_pct=Decimal("20.0"),
        )
        repo.save.assert_awaited_once()
        assert p.name == "Test"

    async def test_create_validates_risk_per_trade_too_high(self) -> None:
        service = _make_service()
        with pytest.raises(ValueError, match="risk_per_trade_pct"):
            await service.create(
                name="X",
                profile_type=RiskProfileType.CUSTOM,
                universe_scope=UniverseScope.ALL_FNO,
                risk_per_trade_pct=Decimal("15.0"),
                max_open_positions=5,
                daily_loss_pct=Decimal("3.0"),
                weekly_loss_pct=Decimal("8.0"),
                drawdown_pct=Decimal("12.0"),
                max_position_size_pct=Decimal("20.0"),
            )

    async def test_create_from_preset(self) -> None:
        repo = _make_repo()
        service = _make_service(repo)
        p = await service.create_from_preset(RiskProfileType.CONSERVATIVE)
        repo.save.assert_awaited_once()
        assert p.profile_type == RiskProfileType.CONSERVATIVE

    async def test_create_custom_from_preset_raises(self) -> None:
        service = _make_service()
        with pytest.raises(ValueError, match="Use create"):
            await service.create_from_preset(RiskProfileType.CUSTOM)


class TestActivateRiskProfile:
    async def test_activate_deactivates_all_then_activates(self) -> None:
        profile = _moderate_profile()
        profile.is_active = False
        repo = _make_repo(by_id=profile)
        service = _make_service(repo)

        result = await service.activate(profile.profile_id)

        repo.deactivate_all.assert_awaited_once()
        assert result.is_active is True

    async def test_activate_not_found_raises(self) -> None:
        repo = _make_repo(by_id=None)
        service = _make_service(repo)
        with pytest.raises(ValueError, match="not found"):
            await service.activate(uuid.uuid4())

    async def test_deactivate_profile(self) -> None:
        profile = _moderate_profile()
        repo = _make_repo(by_id=profile)
        service = _make_service(repo)
        result = await service.deactivate(profile.profile_id)
        assert result.is_active is False

    async def test_deactivate_not_found_raises(self) -> None:
        repo = _make_repo(by_id=None)
        service = _make_service(repo)
        with pytest.raises(ValueError, match="not found"):
            await service.deactivate(uuid.uuid4())


class TestGetRiskProfile:
    async def test_get_active_returns_profile(self) -> None:
        profile = _moderate_profile()
        repo = _make_repo(active=profile)
        service = _make_service(repo)
        result = await service.get_active()
        assert result is profile

    async def test_get_active_none_when_no_active(self) -> None:
        service = _make_service(_make_repo(active=None))
        assert await service.get_active() is None

    async def test_list_all(self) -> None:
        profiles = [RiskProfile.moderate(), RiskProfile.conservative()]
        repo = _make_repo()
        repo.list_all = AsyncMock(return_value=profiles)
        service = _make_service(repo)
        result = await service.list_all()
        assert len(result) == 2
