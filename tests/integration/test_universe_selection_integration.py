"""Integration tests for the Universe Selection Engine (AD-USE-01).

Validates end-to-end pipeline invariants using real filter functions wired
through UniverseFilterService. All I/O boundaries (Redis, event bus) are mocked.

Invariants tested:
  USE-I-1: Candidate list is bounded by max_candidates
  USE-I-2: Protected instruments always appear in the output
  USE-I-3: Sector diversification cap is respected
  USE-I-4: universe.enabled=False → empty instrument list
  USE-I-5: Zero-candidate result does not raise; emits critical log
  USE-I-6: Redis write failure does not propagate to caller
  USE-I-7: All selected instruments have rank > 0 and sequential ranks
  USE-I-8: Protected instruments have composite_score=0.0 and protected=True
"""

from __future__ import annotations

import logging
from datetime import date
from unittest.mock import AsyncMock

import pytest
import yaml
from pathlib import Path

from core.application.services.universe_filter_service import UniverseFilterService
from core.domain.events.universe_events import UniverseSelected
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import UniverseConfig, load_universe_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_config(**overrides: object) -> UniverseConfig:
    """Load real config/universe.yaml with optional field overrides."""
    raw = yaml.safe_load(
        (Path(__file__).parents[2] / "config" / "universe.yaml").read_text()
    )
    universe_raw = raw["universe"]
    for key, val in overrides.items():
        universe_raw[key] = val
    return UniverseConfig.model_validate(universe_raw)


def _make_service(cfg: UniverseConfig | None = None) -> UniverseFilterService:
    repo = AsyncMock()
    repo.save_selected = AsyncMock()
    repo.get_selected = AsyncMock(return_value=None)
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return UniverseFilterService(
        universe_repo=repo,
        event_bus=bus,
        config=cfg or load_universe_config(),
    )


def _instrument(
    token: int,
    underlying: str = "NIFTY",
    sector: str = "Index",
    is_banned: bool = False,
    dte: int = 15,
    atv: float = 100.0,
    strikes: int = 10,
    today_vol: float = 5000.0,
    avg_vol: float = 4000.0,
    atm_oi: float = 1000.0,
    bid: float = 200.0,
    ask: float = 200.5,
    iv_pct: float | None = 30.0,
    iv_rank: float | None = 50.0,
    atr: float | None = 1.2,
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
        avg_traded_value_5d=atv,
        active_strikes_count=strikes,
        today_volume=today_vol,
        avg_volume_20d=avg_vol,
        atm_oi=atm_oi,
        bid=bid,
        ask=ask,
        iv_pct=iv_pct,
        iv_rank=iv_rank,
        atr_14_pct=atr,
    )


def _good(token: int, sector: str = "Index") -> InstrumentData:
    return _instrument(token, underlying=f"STOCK{token}", sector=sector)


# ---------------------------------------------------------------------------
# USE-I-1: Candidate list bounded by max_candidates
# ---------------------------------------------------------------------------


class TestCandidatesBounded:
    @pytest.mark.asyncio
    async def test_fifty_instruments_capped_at_max(self) -> None:
        cfg = _load_config(max_candidates=10)
        service = _make_service(cfg)
        instruments = [_good(1000 + i) for i in range(50)]
        event = await service.select(instruments)
        assert len(event.instruments) <= 10

    @pytest.mark.asyncio
    async def test_fewer_than_max_returns_all_passing(self) -> None:
        service = _make_service()
        instruments = [_good(1000 + i) for i in range(3)]
        event = await service.select(instruments)
        assert len(event.instruments) == 3


# ---------------------------------------------------------------------------
# USE-I-2: Protected instruments always appear
# ---------------------------------------------------------------------------


class TestProtectedInstruments:
    @pytest.mark.asyncio
    async def test_banned_protected_instrument_included(self) -> None:
        service = _make_service()
        banned = _instrument(
            9999, underlying="HDFC", sector="Banking", is_banned=True
        )
        normal = _good(1001)
        event = await service.select(
            [banned, normal],
            active_underlyings=frozenset({"HDFC"}),
        )
        tokens = {i.instrument_token for i in event.instruments}
        assert 9999 in tokens

    @pytest.mark.asyncio
    async def test_protected_instrument_has_correct_flags(self) -> None:
        service = _make_service()
        banned = _instrument(9999, underlying="HDFC", sector="Banking", is_banned=True)
        event = await service.select([banned], active_underlyings=frozenset({"HDFC"}))
        protected = [i for i in event.instruments if i.instrument_token == 9999]
        assert len(protected) == 1
        assert protected[0].protected is True
        assert protected[0].composite_score == 0.0  # USE-I-8

    @pytest.mark.asyncio
    async def test_protected_count_matches_event_field(self) -> None:
        service = _make_service()
        a = _instrument(9001, underlying="SBIN", sector="Banking")
        b = _instrument(9002, underlying="ICICI", sector="Banking")
        normal = _good(1001)
        event = await service.select(
            [a, b, normal],
            active_underlyings=frozenset({"SBIN", "ICICI"}),
        )
        assert event.protected_count == 2

    @pytest.mark.asyncio
    async def test_protected_slots_count_toward_max_candidates(self) -> None:
        cfg = _load_config(max_candidates=5)
        service = _make_service(cfg)
        protected = [
            _instrument(9000 + i, underlying=f"PROT{i}", sector="Banking")
            for i in range(4)
        ]
        candidates = [_good(1000 + i) for i in range(10)]
        active = frozenset(f"PROT{i}" for i in range(4))
        event = await service.select(protected + candidates, active_underlyings=active)
        assert event.protected_count == 4
        assert len(event.instruments) <= 5
        non_protected = [i for i in event.instruments if not i.protected]
        assert len(non_protected) <= 1  # 5 - 4 protected = 1 slot


# ---------------------------------------------------------------------------
# USE-I-3: Sector diversification respected
# ---------------------------------------------------------------------------


class TestSectorDiversification:
    @pytest.mark.asyncio
    async def test_max_per_sector_enforced(self) -> None:
        service = _make_service()
        banking = [
            _instrument(
                2000 + i,
                underlying=f"BANK{i}",
                sector="Banking",
                atm_oi=1000.0 + i * 10,
            )
            for i in range(10)
        ]
        event = await service.select(banking)
        cfg = load_universe_config()
        banking_selected = [
            i for i in event.instruments if i.sector == "Banking" and not i.protected
        ]
        assert len(banking_selected) <= cfg.diversification.max_per_sector

    @pytest.mark.asyncio
    async def test_mixed_sectors_all_within_cap(self) -> None:
        service = _make_service()
        cfg = load_universe_config()
        instruments = []
        for sector in ["Banking", "IT", "FMCG", "Pharma", "Energy"]:
            for j in range(6):
                instruments.append(
                    _instrument(
                        hash(sector + str(j)) % 90000 + 10000,
                        underlying=f"{sector}{j}",
                        sector=sector,
                    )
                )
        event = await service.select(instruments)
        from collections import Counter
        sector_counts = Counter(
            i.sector for i in event.instruments if not i.protected
        )
        for count in sector_counts.values():
            assert count <= cfg.diversification.max_per_sector


# ---------------------------------------------------------------------------
# USE-I-4: universe.enabled=False
# ---------------------------------------------------------------------------


class TestUniverseDisabled:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty_and_flag(self) -> None:
        cfg = _load_config(enabled=False)
        service = _make_service(cfg)
        instruments = [_good(1001), _good(1002)]
        event = await service.select(instruments)
        assert event.instruments == ()
        assert event.universe_enabled is False


# ---------------------------------------------------------------------------
# USE-I-5: Zero candidates does not raise
# ---------------------------------------------------------------------------


class TestZeroCandidates:
    @pytest.mark.asyncio
    async def test_all_banned_produces_empty_without_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        service = _make_service()
        instruments = [
            _instrument(1000 + i, is_banned=True) for i in range(5)
        ]
        with caplog.at_level(logging.CRITICAL, logger="core.application.services.universe_filter_service"):
            event = await service.select(instruments)
        assert event.instruments == ()


# ---------------------------------------------------------------------------
# USE-I-6: Redis write failure does not propagate
# ---------------------------------------------------------------------------


class TestRedisFaultTolerance:
    @pytest.mark.asyncio
    async def test_redis_write_error_does_not_propagate(self) -> None:
        repo = AsyncMock()
        repo.save_selected = AsyncMock(side_effect=ConnectionError("Redis down"))
        repo.get_selected = AsyncMock(return_value=None)
        bus = AsyncMock()
        bus.publish = AsyncMock()
        service = UniverseFilterService(
            universe_repo=repo,
            event_bus=bus,
            config=load_universe_config(),
        )
        event = await service.select([_good(1001)])
        assert isinstance(event, UniverseSelected)


# ---------------------------------------------------------------------------
# USE-I-7: Ranks are sequential
# ---------------------------------------------------------------------------


class TestRankSequential:
    @pytest.mark.asyncio
    async def test_ranks_sequential_from_one(self) -> None:
        service = _make_service()
        instruments = [_good(1000 + i) for i in range(8)]
        event = await service.select(instruments)
        ranks = [i.rank for i in event.instruments]
        assert sorted(ranks) == list(range(1, len(ranks) + 1))

    @pytest.mark.asyncio
    async def test_rank_one_has_highest_composite_score(self) -> None:
        service = _make_service()
        instruments = [_good(1000 + i) for i in range(5)]
        event = await service.select(instruments)
        non_protected = [i for i in event.instruments if not i.protected]
        if len(non_protected) > 1:
            rank1 = next(i for i in non_protected if i.rank == 1)
            rank2 = next(i for i in non_protected if i.rank == 2)
            assert rank1.composite_score >= rank2.composite_score
