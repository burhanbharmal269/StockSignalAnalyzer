"""Unit tests for Stage 8 — CandidateRanker."""

from __future__ import annotations

from datetime import date

import pytest

from core.application.services.universe.candidate_ranker import (
    _minmax_normalise,
    rank_candidates,
)
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import (
    ATRConfig,
    DiversificationConfig,
    OIConfig,
    SpreadConfig,
    VolumeConfig,
)


_VOL_CFG = VolumeConfig(min_volume_ratio=0.5, weight=0.30)
_OI_CFG = OIConfig(min_oi_lots=500, atm_oi_band_pct=10.0, weight=0.30)
_SPREAD_CFG = SpreadConfig(max_spread_pct=0.50, weight=0.20)
_ATR_CFG = ATRConfig(min_atr_pct=0.30, max_atr_pct=5.00, weight=0.20)
_DIV_CFG = DiversificationConfig(enabled=True, max_per_sector=3)
_DIV_DISABLED = DiversificationConfig(enabled=False, max_per_sector=3)


def _make(
    token: int,
    sector: str = "Index",
    today_vol: float = 5000.0,
    avg_vol: float = 4000.0,
    atm_oi: float = 1000.0,
    bid: float = 200.0,
    ask: float = 201.0,
    atr: float = 1.2,
) -> InstrumentData:
    return InstrumentData(
        instrument_token=token,
        underlying=f"STOCK{token}",
        instrument_class="OPTION",
        expiry_date=date(2026, 6, 26),
        sector=sector,
        spot_price=1000.0,
        is_banned=False,
        dte=12,
        avg_traded_value_5d=100.0,
        active_strikes_count=10,
        today_volume=today_vol,
        avg_volume_20d=avg_vol,
        atm_oi=atm_oi,
        bid=bid,
        ask=ask,
        iv_pct=15.0,
        iv_rank=45.0,
        atr_14_pct=atr,
    )


class TestMinmaxNormalise:
    def test_normal_range(self) -> None:
        result = _minmax_normalise([0.0, 5.0, 10.0])
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(0.5)
        assert result[2] == pytest.approx(1.0)

    def test_all_equal_returns_zeros(self) -> None:
        result = _minmax_normalise([3.0, 3.0, 3.0])
        assert result == [0.0, 0.0, 0.0]

    def test_empty_returns_empty(self) -> None:
        assert _minmax_normalise([]) == []


class TestRankCandidates:
    def _rank(
        self,
        instruments: list[InstrumentData],
        max_slots: int = 20,
        div_cfg: DiversificationConfig = _DIV_CFG,
    ) -> list:
        return rank_candidates(
            instruments=instruments,
            max_slots=max_slots,
            volume_cfg=_VOL_CFG,
            oi_cfg=_OI_CFG,
            spread_cfg=_SPREAD_CFG,
            atr_cfg=_ATR_CFG,
            diversification_cfg=div_cfg,
        )

    def test_empty_input(self) -> None:
        assert self._rank([]) == []

    def test_single_instrument_rank_one(self) -> None:
        inst = _make(1001)
        result = self._rank([inst])
        assert len(result) == 1
        assert result[0].rank == 1
        assert result[0].instrument_token == 1001
        assert result[0].protected is False

    def test_max_slots_respected(self) -> None:
        instruments = [_make(i, sector=f"Sector{i}") for i in range(1, 11)]
        result = self._rank(instruments, max_slots=5)
        assert len(result) == 5

    def test_higher_oi_ranks_better_all_else_equal(self) -> None:
        low_oi = _make(1001, atm_oi=600.0)
        high_oi = _make(1002, atm_oi=2000.0)
        result = self._rank([low_oi, high_oi])
        assert result[0].instrument_token == 1002
        assert result[1].instrument_token == 1001

    def test_sector_cap_enforced(self) -> None:
        div = DiversificationConfig(enabled=True, max_per_sector=2)
        instruments = [_make(token=1000 + i, sector="Banking") for i in range(5)]
        result = self._rank(instruments, div_cfg=div)
        assert len(result) == 2
        for r in result:
            assert r.sector == "Banking"

    def test_sector_cap_disabled(self) -> None:
        div = _DIV_DISABLED
        instruments = [_make(token=1000 + i, sector="Banking") for i in range(5)]
        result = self._rank(instruments, div_cfg=div)
        assert len(result) == 5

    def test_sector_cap_mixed_sectors(self) -> None:
        div = DiversificationConfig(enabled=True, max_per_sector=2)
        banking = [_make(token=1000 + i, sector="Banking") for i in range(4)]
        it = [_make(token=2000 + i, sector="IT") for i in range(4)]
        result = self._rank(banking + it, div_cfg=div, max_slots=10)
        banking_count = sum(1 for r in result if r.sector == "Banking")
        it_count = sum(1 for r in result if r.sector == "IT")
        assert banking_count <= 2
        assert it_count <= 2

    def test_ranks_are_sequential(self) -> None:
        instruments = [_make(1000 + i) for i in range(5)]
        result = self._rank(instruments)
        ranks = [r.rank for r in result]
        assert ranks == list(range(1, len(result) + 1))

    def test_metadata_contains_stage8_fields(self) -> None:
        inst = _make(1001)
        result = self._rank([inst])
        meta = result[0].filter_metadata
        assert "stage8_composite_score" in meta
        assert "stage8_rank" in meta

    def test_composite_score_in_zero_to_one(self) -> None:
        instruments = [_make(1000 + i) for i in range(10)]
        result = self._rank(instruments)
        for r in result:
            assert 0.0 <= r.composite_score <= 1.0
