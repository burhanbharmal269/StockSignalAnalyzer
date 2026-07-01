"""Unit tests for Phase 21.1 OI Analytics Layer.

Covers:
  - OI regime classifier (oi_regime.py)
  - OIQualityTier enum
  - OIAnalyticsService: quality scoring, anomaly detection, signal context
  - FeatureRegistry: registration, ranking, category filter
  - FailureAttributionService: instantiation (DB queries mocked)
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.domain.value_objects.oi_regime import (
    OIQualityTier,
    OIRegime,
    classify_oi_regime,
)
from core.application.services.feature_registry import FeatureMetadata, FeatureRegistry
from core.application.services.oi_analytics_service import OIAnalyticsService
from core.infrastructure.config.oi_analytics_config import OIAnalyticsConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg(**overrides) -> OIAnalyticsConfig:
    return OIAnalyticsConfig(**overrides)


def _snap(
    underlying: str = "NIFTY",
    oi: int = 500_000,
    previous_oi: int | None = 490_000,
    last_price: float = 24_000.0,
    oi_change_pct: float | None = 2.0,
    oi_direction: str = "Increasing",
    tradingsymbol: str = "NIFTY26JULFUT",
    expiry: date | None = None,
    age_seconds: float = 30.0,
) -> MagicMock:
    """Return a lightweight FuturesOISnapshot mock."""
    now = datetime.now(UTC)
    snap = MagicMock()
    snap.underlying        = underlying
    snap.tradingsymbol     = tradingsymbol
    snap.expiry            = expiry or date(2026, 7, 29)
    snap.last_price        = last_price
    snap.oi                = oi
    snap.previous_oi       = previous_oi
    snap.oi_change         = (oi - previous_oi) if previous_oi is not None else None
    snap.oi_change_pct     = oi_change_pct
    snap.oi_direction      = oi_direction
    snap.timestamp         = now - timedelta(seconds=age_seconds)
    snap.rolling_stats.return_value = {"n": 15, "avg": oi, "std": 1000, "trend": "UP"}
    return snap


def _svc(config: OIAnalyticsConfig | None = None) -> OIAnalyticsService:
    return OIAnalyticsService(config=config or _cfg(), oi_history_repo=None)


# ── OI Regime Classifier ──────────────────────────────────────────────────────

class TestClassifyOIRegime:
    def test_long_buildup(self):
        assert classify_oi_regime(0.5, 2.0) == OIRegime.LONG_BUILDUP

    def test_short_buildup(self):
        assert classify_oi_regime(-0.5, 2.0) == OIRegime.SHORT_BUILDUP

    def test_long_unwinding(self):
        assert classify_oi_regime(-0.5, -2.0) == OIRegime.LONG_UNWINDING

    def test_short_covering(self):
        assert classify_oi_regime(0.5, -2.0) == OIRegime.SHORT_COVERING

    def test_neutral_small_moves(self):
        assert classify_oi_regime(0.05, 0.1) == OIRegime.NEUTRAL

    def test_unknown_on_none(self):
        assert classify_oi_regime(None, 2.0) == OIRegime.UNKNOWN
        assert classify_oi_regime(0.5, None) == OIRegime.UNKNOWN

    def test_custom_thresholds(self):
        # With tight thresholds, small moves still qualify
        result = classify_oi_regime(0.05, 0.1, price_threshold=0.01, oi_threshold=0.05)
        assert result == OIRegime.LONG_BUILDUP

    def test_oi_regime_values(self):
        assert OIRegime.LONG_BUILDUP.value   == "Long Build-up"
        assert OIRegime.SHORT_BUILDUP.value  == "Short Build-up"
        assert OIRegime.LONG_UNWINDING.value == "Long Unwinding"
        assert OIRegime.SHORT_COVERING.value == "Short Covering"
        assert OIRegime.NEUTRAL.value        == "Neutral"

    def test_boundary_exactly_at_threshold(self):
        # price_change_pct == threshold → NOT > threshold → neutral (requires strict >)
        result = classify_oi_regime(0.1, 0.5)   # exactly at defaults
        assert result == OIRegime.NEUTRAL        # boundary is exclusive


# ── OI Quality Tier ───────────────────────────────────────────────────────────

class TestOIQualityTier:
    def test_tier_values(self):
        assert OIQualityTier.EXCELLENT.value   == "Excellent"
        assert OIQualityTier.UNAVAILABLE.value == "Unavailable"

    def test_tier_ordering(self):
        tiers = [OIQualityTier.EXCELLENT, OIQualityTier.GOOD,
                 OIQualityTier.FAIR, OIQualityTier.POOR, OIQualityTier.UNAVAILABLE]
        assert len(tiers) == 5


# ── OIAnalyticsService — quality scoring ─────────────────────────────────────

class TestOIAnalyticsQuality:
    def test_excellent_fresh_data(self):
        svc  = _svc()
        snap = _snap(age_seconds=30.0)
        tier, score = svc._compute_quality(snap, datetime.now(UTC))
        assert tier == OIQualityTier.EXCELLENT
        assert score >= 85

    def test_poor_stale_data(self):
        svc  = _svc()
        snap = _snap(age_seconds=700.0)   # > quality_max_age_seconds=600
        tier, score = svc._compute_quality(snap, datetime.now(UTC))
        assert tier == OIQualityTier.UNAVAILABLE
        assert score == 0

    def test_zero_oi_degrades_score(self):
        svc  = _svc()
        snap = _snap(oi=0, age_seconds=30.0)
        _, score = svc._compute_quality(snap, datetime.now(UTC))
        assert score <= 60   # -40 penalty for oi==0

    def test_no_previous_oi_penalty(self):
        svc  = _svc()
        snap = _snap(previous_oi=None, age_seconds=30.0)
        _, score_no_prev = svc._compute_quality(snap, datetime.now(UTC))
        snap2 = _snap(previous_oi=490_000, age_seconds=30.0)
        _, score_with_prev = svc._compute_quality(snap2, datetime.now(UTC))
        assert score_with_prev > score_no_prev

    def test_low_observations_penalty(self):
        svc  = _svc()
        snap = _snap()
        snap.rolling_stats.return_value = {"n": 2, "avg": 500_000}
        _, score_low = svc._compute_quality(snap, datetime.now(UTC))
        snap2 = _snap()
        snap2.rolling_stats.return_value = {"n": 15, "avg": 500_000}
        _, score_high = svc._compute_quality(snap2, datetime.now(UTC))
        assert score_high > score_low


# ── OIAnalyticsService — anomaly detection ───────────────────────────────────

class TestOIAnomalyDetection:
    def _state(self, freeze_count: int = 0, last_oi: int | None = None):
        from core.application.services.oi_analytics_service import _SymbolState
        s = _SymbolState()
        s.freeze_count = freeze_count
        s.last_oi = last_oi
        return s

    def test_no_anomaly_normal(self):
        svc   = _svc()
        snap  = _snap(oi_change_pct=2.0, age_seconds=30.0)
        state = self._state()
        assert svc._detect_anomaly(snap, state, datetime.now(UTC)) is None

    def test_spike_detected(self):
        svc   = _svc()
        snap  = _snap(oi_change_pct=25.0, age_seconds=30.0)
        state = self._state()
        assert svc._detect_anomaly(snap, state, datetime.now(UTC)) == "SPIKE"

    def test_collapse_detected(self):
        svc   = _svc()
        snap  = _snap(oi_change_pct=-25.0, age_seconds=30.0)
        state = self._state()
        assert svc._detect_anomaly(snap, state, datetime.now(UTC)) == "COLLAPSE"

    def test_freeze_detected(self):
        svc   = _svc()
        snap  = _snap(oi_change_pct=0.5, age_seconds=30.0)
        state = self._state(freeze_count=3)   # >= anomaly_freeze_polls=3
        assert svc._detect_anomaly(snap, state, datetime.now(UTC)) == "FREEZE"

    def test_stale_detected(self):
        svc   = _svc()
        snap  = _snap(oi_change_pct=1.0, age_seconds=1000.0)   # > stale_threshold=900
        state = self._state()
        assert svc._detect_anomaly(snap, state, datetime.now(UTC)) == "STALE"

    def test_stale_takes_priority_over_spike(self):
        """Stale check runs before spike — stale should win."""
        svc   = _svc()
        snap  = _snap(oi_change_pct=50.0, age_seconds=1000.0)
        state = self._state()
        assert svc._detect_anomaly(snap, state, datetime.now(UTC)) == "STALE"


# ── OIAnalyticsService — update path ─────────────────────────────────────────

class TestOIAnalyticsUpdate:
    @pytest.mark.asyncio
    async def test_state_populated_after_update(self):
        svc  = _svc()
        snap = _snap(underlying="RELIANCE", oi_change_pct=3.0)
        await svc.update_from_snapshot(snap, price_change_pct=0.5)
        assert svc.get_regime("RELIANCE") == OIRegime.LONG_BUILDUP.value
        q = svc.get_quality("RELIANCE")
        assert q["tier"] != OIQualityTier.UNAVAILABLE.value

    @pytest.mark.asyncio
    async def test_freeze_counter_increments(self):
        svc  = _svc()
        snap = _snap(underlying="NIFTY", oi=500_000)
        await svc.update_from_snapshot(snap, price_change_pct=0.2)
        await svc.update_from_snapshot(snap, price_change_pct=0.2)  # same OI
        state = svc._state["NIFTY"]
        assert state.freeze_count == 1   # incremented on 2nd call

    @pytest.mark.asyncio
    async def test_anomaly_logged_in_state(self):
        svc  = _svc()
        snap = _snap(underlying="INFY", oi_change_pct=50.0, age_seconds=30.0)
        await svc.update_from_snapshot(snap, price_change_pct=0.5)
        state = svc._state["INFY"]
        assert state.is_anomaly
        assert state.anomaly_type == "SPIKE"
        assert len(state.recent_anomalies) == 1

    @pytest.mark.asyncio
    async def test_no_repo_no_error(self):
        """With oi_history_repo=None, snapshots should still be processed."""
        svc  = OIAnalyticsService(config=_cfg(), oi_history_repo=None)
        snap = _snap(underlying="TCS")
        await svc.update_from_snapshot(snap)   # must not raise
        assert svc.get_regime("TCS") is not None

    @pytest.mark.asyncio
    async def test_market_breadth_aggregates_regimes(self):
        svc = _svc()
        for sym, price_chg, oi_chg in [
            ("NIFTY",    0.5,  3.0),   # LONG_BUILDUP
            ("RELIANCE", -0.5, 3.0),   # SHORT_BUILDUP
            ("INFY",     0.5, -3.0),   # SHORT_COVERING
        ]:
            snap = _snap(underlying=sym, oi_change_pct=oi_chg)
            await svc.update_from_snapshot(snap, price_change_pct=price_chg)
        breadth = svc.get_market_breadth_oi()
        assert breadth["symbols_tracked"] == 3
        assert breadth["long_buildup_pct"]  > 0
        assert breadth["short_buildup_pct"] > 0
        assert breadth["short_cover_pct"]   > 0

    @pytest.mark.asyncio
    async def test_get_context_for_signal(self):
        svc  = _svc()
        snap = _snap(underlying="WIPRO", oi_change_pct=1.5)
        await svc.update_from_snapshot(snap, price_change_pct=0.3)
        ctx = svc.get_context_for_signal("WIPRO", snap)
        assert "futures_oi"  in ctx
        assert "oi_regime"   in ctx
        assert "oi_direction" in ctx
        assert ctx["futures_oi"] == snap.oi

    @pytest.mark.asyncio
    async def test_get_context_no_snap(self):
        svc = _svc()
        ctx = svc.get_context_for_signal("UNKNOWN", None)
        assert ctx == {}


# ── FeatureRegistry ───────────────────────────────────────────────────────────

class TestFeatureRegistry:
    def test_bootstrap_registers_defaults(self):
        reg = FeatureRegistry()
        all_features = reg.get_all()
        assert len(all_features) >= 17

    def test_get_by_name(self):
        reg = FeatureRegistry()
        f = reg.get("trend")
        assert f is not None
        assert f.category == "technical"

    def test_get_by_category(self):
        reg = FeatureRegistry()
        options_features = reg.get_by_category("options")
        names = [f["name"] for f in options_features]
        assert "option_chain" in names
        assert "iv" in names

    def test_register_custom(self):
        reg = FeatureRegistry()
        meta = FeatureMetadata("my_feature", "technical", "computed")
        reg.register("my_feature", meta)
        assert reg.get("my_feature") is not None

    def test_update_quality(self):
        reg = FeatureRegistry()
        reg.update_quality("trend", quality_score=92.0, availability_pct=99.5)
        f = reg.get("trend")
        assert f.quality_score == 92.0
        assert f.availability_pct == 99.5

    def test_update_predictive_power(self):
        reg = FeatureRegistry()
        reg.update_predictive_power("trend", 0.72)
        f = reg.get("trend")
        assert f.predictive_power == 0.72

    def test_ranked_sorts_by_predictive_power(self):
        reg = FeatureRegistry()
        reg.update_predictive_power("volume", 0.9)
        reg.update_predictive_power("trend", 0.5)
        ranked = reg.get_ranked()
        names = [r["name"] for r in ranked]
        assert names.index("volume") < names.index("trend")

    def test_get_degraded_filters_correctly(self):
        reg = FeatureRegistry()
        reg.update_quality("vix", quality_score=10.0, availability_pct=20.0, status="DEGRADED")
        degraded = reg.get_degraded()
        assert any(f["name"] == "vix" for f in degraded)

    def test_update_unknown_feature_does_not_raise(self):
        reg = FeatureRegistry()
        reg.update_quality("does_not_exist", quality_score=50.0, availability_pct=80.0)

    def test_to_dict_contains_all_fields(self):
        reg = FeatureRegistry()
        f = reg.get_all()[0]
        required = {"name", "category", "source", "version",
                    "refresh_frequency_seconds", "dependencies",
                    "quality_score", "availability_pct", "predictive_power",
                    "current_status", "registered_at", "last_updated_at"}
        assert required.issubset(f.keys())


# ── FailureAttributionService ─────────────────────────────────────────────────

class TestFailureAttributionService:
    def test_instantiation(self):
        from core.application.services.failure_attribution_service import FailureAttributionService
        sf = MagicMock()
        svc = FailureAttributionService(session_factory=sf)
        assert svc is not None

    @pytest.mark.asyncio
    async def test_get_oi_failure_patterns_returns_error_on_db_fail(self):
        from core.application.services.failure_attribution_service import FailureAttributionService

        async def _bad_ctx():
            raise RuntimeError("DB down")

        sf = MagicMock()
        sf.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
        sf.return_value.__aexit__  = AsyncMock(return_value=False)

        svc = FailureAttributionService(session_factory=sf)
        result = await svc.get_oi_failure_patterns(days=30)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_tmi_by_oi_regime_returns_error_on_db_fail(self):
        from core.application.services.failure_attribution_service import FailureAttributionService

        sf = MagicMock()
        sf.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
        sf.return_value.__aexit__  = AsyncMock(return_value=False)

        svc = FailureAttributionService(session_factory=sf)
        result = await svc.get_tmi_by_oi_regime(days=30)
        assert "error" in result
