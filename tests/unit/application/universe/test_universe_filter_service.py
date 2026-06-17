"""Unit tests for UniverseFilterService orchestrator."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from core.application.services.universe_filter_service import UniverseFilterService
from core.domain.events.universe_events import UniverseSelected
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import load_universe_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def config():
    return load_universe_config()


def _make_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save_selected = AsyncMock()
    repo.get_selected = AsyncMock(return_value=None)
    return repo


def _make_event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


def _make_instrument(
    token: int,
    underlying: str = "NIFTY",
    sector: str = "Index",
    iv_pct: float | None = 30.0,
    atr_14_pct: float | None = 1.2,
    is_banned: bool = False,
    dte: int = 12,
) -> InstrumentData:
    return InstrumentData(
        instrument_token=token,
        underlying=underlying,
        instrument_class="OPTION",
        expiry_date=date(2026, 6, 26),
        sector=sector,
        spot_price=23000.0,
        is_banned=is_banned,
        dte=dte,
        avg_traded_value_5d=100.0,
        active_strikes_count=10,
        today_volume=5000.0,
        avg_volume_20d=4000.0,
        atm_oi=1000.0,
        bid=200.0,
        ask=200.5,
        iv_pct=iv_pct,
        iv_rank=50.0,
        atr_14_pct=atr_14_pct,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUniverseFilterServiceEnabled:
    @pytest.mark.asyncio
    async def test_select_returns_universe_selected_event(self, config) -> None:
        service = UniverseFilterService(
            universe_repo=_make_repo(),
            event_bus=_make_event_bus(),
            config=config,
        )
        instruments = [_make_instrument(1000 + i) for i in range(5)]
        event = await service.select(instruments)
        assert isinstance(event, UniverseSelected)
        assert event.universe_enabled is True

    @pytest.mark.asyncio
    async def test_select_publishes_event(self, config) -> None:
        bus = _make_event_bus()
        service = UniverseFilterService(
            universe_repo=_make_repo(),
            event_bus=bus,
            config=config,
        )
        instruments = [_make_instrument(1000 + i) for i in range(3)]
        await service.select(instruments)
        bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_saves_to_repo(self, config) -> None:
        repo = _make_repo()
        service = UniverseFilterService(
            universe_repo=repo,
            event_bus=_make_event_bus(),
            config=config,
        )
        instruments = [_make_instrument(1000 + i) for i in range(3)]
        await service.select(instruments)
        repo.save_selected.assert_called_once()

    @pytest.mark.asyncio
    async def test_candidates_bounded_by_max_candidates(self, config) -> None:
        service = UniverseFilterService(
            universe_repo=_make_repo(),
            event_bus=_make_event_bus(),
            config=config,
        )
        instruments = [_make_instrument(1000 + i) for i in range(50)]
        event = await service.select(instruments)
        assert len(event.instruments) <= config.max_candidates

    @pytest.mark.asyncio
    async def test_empty_input_returns_zero_candidates(self, config) -> None:
        service = UniverseFilterService(
            universe_repo=_make_repo(),
            event_bus=_make_event_bus(),
            config=config,
        )
        event = await service.select([])
        assert event.instruments == ()
        assert event.total_eligible == 0


class TestActivePositionProtection:
    @pytest.mark.asyncio
    async def test_protected_instruments_always_included(self, config) -> None:
        service = UniverseFilterService(
            universe_repo=_make_repo(),
            event_bus=_make_event_bus(),
            config=config,
        )
        # One banned instrument that would be excluded by eligibility filter
        banned = _make_instrument(9999, underlying="RELIANCE", sector="Oil", is_banned=True)
        normal = _make_instrument(1001)
        event = await service.select(
            [banned, normal],
            active_underlyings=frozenset({"RELIANCE"}),
        )
        tokens = {i.instrument_token for i in event.instruments}
        assert 9999 in tokens
        protected = [i for i in event.instruments if i.protected]
        assert len(protected) == 1
        assert protected[0].instrument_token == 9999

    @pytest.mark.asyncio
    async def test_protected_count_in_event(self, config) -> None:
        service = UniverseFilterService(
            universe_repo=_make_repo(),
            event_bus=_make_event_bus(),
            config=config,
        )
        active = _make_instrument(9001, underlying="SBIN", sector="Banking")
        normal = _make_instrument(1001)
        event = await service.select(
            [active, normal],
            active_underlyings=frozenset({"SBIN"}),
        )
        assert event.protected_count == 1

    @pytest.mark.asyncio
    async def test_no_active_underlyings_none_protected(self, config) -> None:
        service = UniverseFilterService(
            universe_repo=_make_repo(),
            event_bus=_make_event_bus(),
            config=config,
        )
        instruments = [_make_instrument(1000 + i) for i in range(3)]
        event = await service.select(instruments, active_underlyings=None)
        assert event.protected_count == 0
        assert all(not i.protected for i in event.instruments)


class TestUniverseDisabled:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty_list(self) -> None:
        from pydantic import ValidationError
        import yaml
        from pathlib import Path
        from core.infrastructure.config.universe_config import UniverseConfig

        raw = yaml.safe_load(
            (Path(__file__).parents[4] / "config" / "universe.yaml").read_text()
        )
        raw["universe"]["enabled"] = False
        cfg = UniverseConfig.model_validate(raw["universe"])

        service = UniverseFilterService(
            universe_repo=_make_repo(),
            event_bus=_make_event_bus(),
            config=cfg,
        )
        instruments = [_make_instrument(1001)]
        event = await service.select(instruments)
        assert event.instruments == ()
        assert event.universe_enabled is False


class TestRepoCacheFailure:
    @pytest.mark.asyncio
    async def test_repo_write_failure_does_not_raise(self, config) -> None:
        repo = AsyncMock()
        repo.save_selected = AsyncMock(side_effect=Exception("Redis down"))
        repo.get_selected = AsyncMock(return_value=None)
        service = UniverseFilterService(
            universe_repo=repo,
            event_bus=_make_event_bus(),
            config=config,
        )
        instruments = [_make_instrument(1001)]
        event = await service.select(instruments)
        assert isinstance(event, UniverseSelected)
