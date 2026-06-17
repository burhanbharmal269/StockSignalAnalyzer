"""Unit tests for Stage 1 — EligibilityFilter."""

from __future__ import annotations

from datetime import date

import pytest

from core.application.services.universe.eligibility_filter import apply_eligibility_filter
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import EligibilityConfig


_CFG = EligibilityConfig(
    allowed_instrument_classes=["OPTION", "FUTURE"],
    max_dte_days=30,
    exclude_banned=True,
)


def _make(**overrides: object) -> InstrumentData:
    defaults: dict[str, object] = {
        "instrument_token": 1001,
        "underlying": "NIFTY",
        "instrument_class": "OPTION",
        "expiry_date": date(2026, 6, 26),
        "sector": "Index",
        "spot_price": 23000.0,
        "is_banned": False,
        "dte": 12,
        "avg_traded_value_5d": 100.0,
        "active_strikes_count": 10,
        "today_volume": 5000.0,
        "avg_volume_20d": 4000.0,
        "atm_oi": 1000.0,
        "bid": 200.0,
        "ask": 201.0,
        "iv_pct": 15.0,
        "iv_rank": 45.0,
        "atr_14_pct": 1.2,
    }
    defaults.update(overrides)
    return InstrumentData(**defaults)  # type: ignore[arg-type]


class TestEligibilityFilter:
    def test_valid_instrument_passes(self) -> None:
        inst = _make()
        passed, excl = apply_eligibility_filter([inst], _CFG)
        assert len(passed) == 1
        assert not excl

    def test_banned_instrument_excluded(self) -> None:
        inst = _make(is_banned=True)
        passed, excl = apply_eligibility_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "ban_list" in excl[1001]

    def test_banned_passes_when_exclude_banned_false(self) -> None:
        cfg = EligibilityConfig(
            allowed_instrument_classes=["OPTION"],
            max_dte_days=30,
            exclude_banned=False,
        )
        inst = _make(is_banned=True)
        passed, excl = apply_eligibility_filter([inst], cfg)
        assert len(passed) == 1
        assert not excl

    def test_disallowed_class_excluded(self) -> None:
        inst = _make(instrument_class="BOND")
        passed, excl = apply_eligibility_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl

    def test_expired_instrument_excluded(self) -> None:
        inst = _make(dte=0)
        passed, excl = apply_eligibility_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl

    def test_dte_exceeds_max_excluded(self) -> None:
        inst = _make(dte=31)
        passed, excl = apply_eligibility_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl

    def test_dte_at_boundary_passes(self) -> None:
        inst = _make(dte=30)
        passed, _ = apply_eligibility_filter([inst], _CFG)
        assert len(passed) == 1

    def test_future_class_passes(self) -> None:
        inst = _make(instrument_class="FUTURE")
        passed, _ = apply_eligibility_filter([inst], _CFG)
        assert len(passed) == 1

    def test_empty_input(self) -> None:
        passed, excl = apply_eligibility_filter([], _CFG)
        assert passed == []
        assert excl == {}

    def test_mixed_batch(self) -> None:
        good = _make(instrument_token=1001)
        bad = _make(instrument_token=1002, is_banned=True)
        passed, excl = apply_eligibility_filter([good, bad], _CFG)
        assert len(passed) == 1
        assert passed[0].instrument_token == 1001
        assert 1002 in excl
