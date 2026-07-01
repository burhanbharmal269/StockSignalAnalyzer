"""Unit tests for FuturesOIService — Phase 21: Futures OI Integration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from core.application.services.futures_oi_service import FuturesOIService, FuturesOISnapshot
from core.infrastructure.config.futures_oi_config import FuturesOIConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JULY_EXPIRY = date(2026, 7, 29)
_AUG_EXPIRY  = date(2026, 8, 26)


def _cfg(**kwargs) -> FuturesOIConfig:
    return FuturesOIConfig(**kwargs)


def _svc(**kwargs) -> FuturesOIService:
    return FuturesOIService(config=_cfg(**kwargs))


def _feed(
    svc: FuturesOIService,
    underlying: str = "NIFTY",
    tradingsymbol: str = "NIFTY26JULFUT",
    oi: int = 100_000,
    expiry: date = _JULY_EXPIRY,
) -> None:
    svc.update(
        underlying=underlying,
        tradingsymbol=tradingsymbol,
        instrument_token=12345,
        expiry=expiry,
        last_price=24500.0,
        oi=oi,
        oi_day_high=110_000,
        oi_day_low=90_000,
    )


# ---------------------------------------------------------------------------
# Basic update and retrieval
# ---------------------------------------------------------------------------


def test_update_and_get_cached_returns_snapshot():
    svc = _svc()
    _feed(svc, oi=100_000)
    snap = svc.get_cached("NIFTY")
    assert snap is not None
    assert snap.underlying == "NIFTY"
    assert snap.oi == 100_000
    assert snap.oi_change is None          # no previous poll yet
    assert snap.oi_change_pct is None


def test_has_data_true_after_update():
    svc = _svc()
    _feed(svc)
    assert svc.has_data("NIFTY") is True


def test_has_data_false_before_update():
    svc = _svc()
    assert svc.has_data("NIFTY") is False


def test_unknown_symbol_returns_none():
    svc = _svc()
    _feed(svc, underlying="BANKNIFTY")
    assert svc.get_cached("NIFTY") is None


# ---------------------------------------------------------------------------
# Sequential OI change calculation
# ---------------------------------------------------------------------------


def test_sequential_oi_change_computed_on_second_poll():
    svc = _svc()
    _feed(svc, oi=100_000)
    _feed(svc, oi=105_000)   # second poll
    snap = svc.get_cached("NIFTY")
    assert snap is not None
    assert snap.previous_oi == 100_000
    assert snap.oi_change == 5_000
    assert snap.oi_change_pct == pytest.approx(5.0, rel=1e-3)


def test_oi_decrease_gives_negative_change_pct():
    svc = _svc()
    _feed(svc, oi=100_000)
    _feed(svc, oi=80_000)
    snap = svc.get_cached("NIFTY")
    assert snap is not None
    assert snap.oi_change == -20_000
    assert snap.oi_change_pct == pytest.approx(-20.0, rel=1e-3)


def test_oi_change_is_sequential_not_from_day_extrema():
    """Verify change = current_poll - previous_poll, not oi_day_high - oi_day_low."""
    svc = _svc()
    _feed(svc, oi=100_000)
    # day extrema deliberately not related to the sequential change
    svc.update(
        underlying="NIFTY",
        tradingsymbol="NIFTY26JULFUT",
        instrument_token=12345,
        expiry=_JULY_EXPIRY,
        last_price=24500.0,
        oi=102_000,
        oi_day_high=200_000,   # irrelevant to sequential change
        oi_day_low=50_000,
    )
    snap = svc.get_cached("NIFTY")
    assert snap is not None
    assert snap.oi_change == 2_000            # current(102k) - prev(100k)
    assert snap.oi_change_pct == pytest.approx(2.0, rel=1e-3)


# ---------------------------------------------------------------------------
# OI direction classification
# ---------------------------------------------------------------------------


def test_oi_direction_increasing():
    svc = _svc(oi_direction_threshold=0.5)
    _feed(svc, oi=100_000)
    _feed(svc, oi=110_000)   # +10% > 0.5%
    assert svc.get_cached("NIFTY").oi_direction == "Increasing"


def test_oi_direction_falling():
    svc = _svc(oi_direction_threshold=0.5)
    _feed(svc, oi=100_000)
    _feed(svc, oi=90_000)    # -10% < -0.5%
    assert svc.get_cached("NIFTY").oi_direction == "Falling"


def test_oi_direction_flat_within_threshold():
    svc = _svc(oi_direction_threshold=0.5)
    _feed(svc, oi=100_000)
    _feed(svc, oi=100_400)   # +0.4% inside ±0.5% threshold
    assert svc.get_cached("NIFTY").oi_direction == "Flat"


def test_oi_direction_threshold_is_configurable():
    # With a 5% threshold, 3% change should still be Flat
    svc = _svc(oi_direction_threshold=5.0)
    _feed(svc, oi=100_000)
    _feed(svc, oi=103_000)   # +3% — inside ±5%
    assert svc.get_cached("NIFTY").oi_direction == "Flat"

    # With a 1% threshold, 3% should be Increasing
    svc2 = _svc(oi_direction_threshold=1.0)
    _feed(svc2, oi=100_000)
    _feed(svc2, oi=103_000)
    assert svc2.get_cached("NIFTY").oi_direction == "Increasing"


# ---------------------------------------------------------------------------
# Cache TTL / staleness
# ---------------------------------------------------------------------------


def test_stale_cache_returns_none(monkeypatch):
    svc = _svc(oi_cache_ttl=60)
    _feed(svc)

    # Monkey-patch the snapshot timestamp to be older than TTL
    snap = svc._cache["NIFTY"]
    old_ts = datetime.now(UTC) - timedelta(seconds=120)
    object.__setattr__(snap, "timestamp", old_ts)

    assert svc.get_cached("NIFTY") is None
    assert svc.has_data("NIFTY") is False


def test_fresh_cache_within_ttl_returns_snapshot():
    svc = _svc(oi_cache_ttl=600)
    _feed(svc)
    assert svc.get_cached("NIFTY") is not None


# ---------------------------------------------------------------------------
# Contract rollover
# ---------------------------------------------------------------------------


def test_contract_rollover_resets_previous_oi():
    svc = _svc()
    _feed(svc, tradingsymbol="NIFTY26JULFUT", expiry=_JULY_EXPIRY, oi=100_000)
    # Next poll with new contract month
    svc.update(
        underlying="NIFTY",
        tradingsymbol="NIFTY26AUGFUT",
        instrument_token=99999,
        expiry=_AUG_EXPIRY,
        last_price=24600.0,
        oi=50_000,       # new contract; smaller OI is normal for next month
        oi_day_high=55_000,
        oi_day_low=45_000,
    )
    snap = svc.get_cached("NIFTY")
    assert snap is not None
    assert snap.tradingsymbol == "NIFTY26AUGFUT"
    # After rollover, previous_oi must be None (stale expiry discarded)
    assert snap.previous_oi is None
    assert snap.oi_change is None
    assert snap.oi_change_pct is None


def test_rollover_counter_increments():
    svc = _svc()
    _feed(svc, tradingsymbol="NIFTY26JULFUT", expiry=_JULY_EXPIRY)
    svc.update(
        underlying="NIFTY",
        tradingsymbol="NIFTY26AUGFUT",
        instrument_token=99999,
        expiry=_AUG_EXPIRY,
        last_price=24600.0,
        oi=50_000,
        oi_day_high=55_000,
        oi_day_low=45_000,
    )
    assert svc.get_metrics()["futures_oi_rolls"] == 1


# ---------------------------------------------------------------------------
# Rolling statistics
# ---------------------------------------------------------------------------


def test_rolling_stats_return_none_below_min_observations():
    svc = _svc()
    _feed(svc, oi=100_000)
    _feed(svc, oi=101_000)
    # Only 2 observations — below _MIN_ROLLING=3
    snap = svc.get_cached("NIFTY")
    assert snap is not None
    stats = snap.rolling_stats(5)
    assert stats["avg"] is None


def test_rolling_stats_return_values_with_enough_observations():
    svc = _svc()
    for oi in [100_000, 101_000, 102_000]:
        _feed(svc, oi=oi)
    snap = svc.get_cached("NIFTY")
    assert snap is not None
    stats = snap.rolling_stats(5)
    assert stats["avg"] == pytest.approx(101_000.0, rel=1e-3)
    assert stats["n"] == 3
    assert stats["trend"] == "UP"


def test_rolling_window_5_maxlen():
    svc = _svc()
    for i in range(10):   # feed 10 observations into a window-5 buffer
        _feed(svc, oi=100_000 + i * 1_000)
    snap = svc.get_cached("NIFTY")
    assert snap is not None
    # Window-5 should only hold the last 5
    assert snap.rolling_stats(5)["n"] == 5


# ---------------------------------------------------------------------------
# Failure and missing tracking
# ---------------------------------------------------------------------------


def test_mark_missing_increments_counter():
    svc = _svc()
    svc.mark_missing("NIFTY", "no_fut_in_chain")
    svc.mark_missing("BANKNIFTY", "market_closed")
    assert svc.get_metrics()["futures_oi_missing"] == 2


def test_mark_failure_increments_counter():
    svc = _svc()
    svc.mark_failure("NIFTY", "timeout")
    assert svc.get_metrics()["futures_oi_failure"] == 1


# ---------------------------------------------------------------------------
# Analytics and observability
# ---------------------------------------------------------------------------


def test_get_analytics_empty_when_no_data():
    svc = _svc()
    analytics = svc.get_analytics()
    assert analytics["symbols_cached"] == 0


def test_get_analytics_aggregates_cached_symbols():
    svc = _svc()
    _feed(svc, underlying="NIFTY",     oi=100_000)
    _feed(svc, underlying="NIFTY",     oi=110_000)   # OI change +10%
    _feed(svc, underlying="BANKNIFTY", tradingsymbol="BANKNIFTY26JULFUT", oi=50_000)
    _feed(svc, underlying="BANKNIFTY", tradingsymbol="BANKNIFTY26JULFUT", oi=50_000)  # flat
    analytics = svc.get_analytics()
    assert analytics["symbols_cached"] == 2
    assert analytics["symbols_with_change"] == 2


def test_get_symbol_detail_returns_full_snapshot():
    svc = _svc()
    _feed(svc, oi=100_000)
    _feed(svc, oi=105_000)
    detail = svc.get_symbol_detail("NIFTY")
    assert detail is not None
    assert detail["oi"] == 105_000
    assert detail["previous_oi"] == 100_000
    assert detail["oi_change"] == 5_000
    assert detail["oi_change_pct"] == pytest.approx(5.0, rel=1e-3)
    assert detail["oi_direction"] == "Increasing"
    assert "rolling_5" in detail
    assert "rolling_15" in detail
    assert "rolling_60" in detail


def test_get_symbol_detail_returns_none_for_unknown():
    svc = _svc()
    assert svc.get_symbol_detail("NOTEXIST") is None


def test_get_all_symbols_lists_cached():
    svc = _svc()
    _feed(svc, underlying="NIFTY")
    _feed(svc, underlying="BANKNIFTY", tradingsymbol="BANKNIFTY26JULFUT")
    all_syms = svc.get_all_symbols()
    underlyings = {s["underlying"] for s in all_syms}
    assert underlyings == {"NIFTY", "BANKNIFTY"}


# ---------------------------------------------------------------------------
# oi_poll_enabled master switch
# ---------------------------------------------------------------------------


def test_config_defaults_poll_enabled():
    cfg = FuturesOIConfig()
    assert cfg.oi_poll_enabled is True


def test_config_can_disable_poll():
    cfg = FuturesOIConfig(oi_poll_enabled=False)
    assert cfg.oi_poll_enabled is False
