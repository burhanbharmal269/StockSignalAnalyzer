"""Phase 22 — Scanner Intelligence unit tests.

Covers:
  §1  OptionChainIntelligenceWorker — compute_intel, liquidity_score, caching
  §2  StrikeScore / _score_strike — 6-component weighted score
  §3  MarketRegimeSnapshotService — classification priority
  §6  IndicatorCacheService — get/set/miss/hit/stats
  §7  MarketBreadthService._ema helper
  §8  ExecutionReadinessService — check count
  §12 ScannerReplayService — extract_top_scores
  §13 ResourceMonitorService — psutil optional
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── §6 IndicatorCacheService ──────────────────────────────────────────────────

class TestIndicatorCacheService:
    def _make_svc(self, redis_get_return=None):
        from core.application.services.indicator_cache_service import IndicatorCacheService
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps(redis_get_return) if redis_get_return else None)
        redis.setex = AsyncMock()
        return IndicatorCacheService(redis_client=redis), redis

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self):
        svc, _ = self._make_svc(None)
        result = await svc.get("RELIANCE", "2026-07-02T10:00:00")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_returns_dict(self):
        payload = {"adx": 28.5, "rsi_14": 62.1}
        svc, _ = self._make_svc(payload)
        result = await svc.get("RELIANCE", "2026-07-02T10:00:00")
        assert result == payload

    @pytest.mark.asyncio
    async def test_set_calls_setex(self):
        svc, redis = self._make_svc()
        await svc.set("NIFTY", "2026-07-02T10:15:00", {"adx": 35.0})
        redis.setex.assert_called_once()
        key = redis.setex.call_args[0][0]
        assert key.startswith("ind:NIFTY:")

    def test_stats_hit_rate(self):
        from core.application.services.indicator_cache_service import IndicatorCacheService
        svc = IndicatorCacheService(redis_client=AsyncMock())
        svc._hits = 7
        svc._misses = 3
        stats = svc.stats()
        assert stats["hit_rate_pct"] == 70
        assert stats["total"] == 10


# ── §7 MarketBreadthService._ema ──────────────────────────────────────────────

class TestEmaHelper:
    def test_ema_single_period(self):
        from core.application.services.market_breadth_service import _ema
        closes = [100.0] * 20
        result = _ema(closes, 20)
        assert abs(result - 100.0) < 0.01

    def test_ema_rising_series(self):
        from core.application.services.market_breadth_service import _ema
        closes = list(range(1, 52))  # 1..51
        ema20 = _ema(closes, 20)
        ema50 = _ema(closes, 50)
        # EMA50 covers more history so it should be lower than EMA20 in rising series
        assert ema50 < ema20

    def test_ema_short_data_returns_last(self):
        from core.application.services.market_breadth_service import _ema
        closes = [50.0, 60.0]
        result = _ema(closes, 20)
        assert result == 60.0


# ── §2 StrikeScore / _score_strike ───────────────────────────────────────────

class TestStrikeScore:
    def _make_entries(self, strikes_oi):
        """Build minimal option chain entries list."""
        return [
            {
                "strike": s,
                "oi": oi,
                "volume": oi // 2,
                "ltp": 50.0,
                "option_type": "CE",
                "underlying": "NIFTY",
            }
            for s, oi in strikes_oi
        ]

    def test_score_strike_zero_oi(self):
        from core.application.services.option_strike_selector import _score_strike
        entries = self._make_entries([(24500, 5000), (24600, 0)])
        entry_0oi = entries[1]
        score = _score_strike(entry_0oi, atm_price=24550, all_entries=entries, opt_type="CE")
        assert score.total >= 0
        assert score.components["oi_score"] == 0.0

    def test_score_strike_best_oi_selected(self):
        from core.application.services.option_strike_selector import _score_strike
        entries = self._make_entries([(24500, 20000), (24600, 500)])
        score_high = _score_strike(entries[0], atm_price=24550, all_entries=entries, opt_type="CE")
        score_low  = _score_strike(entries[1], atm_price=24550, all_entries=entries, opt_type="CE")
        assert score_high.total > score_low.total

    def test_score_strike_total_in_range(self):
        from core.application.services.option_strike_selector import _score_strike
        entries = self._make_entries([(24500, 10000), (24600, 8000)])
        score = _score_strike(entries[0], atm_price=24550, all_entries=entries, opt_type="CE")
        assert 0 <= score.total <= 100


# ── §3 MarketRegimeSnapshotService ───────────────────────────────────────────

class TestMarketRegimeSnapshotService:
    def _make_svc(self):
        from core.application.services.market_regime_snapshot_service import MarketRegimeSnapshotService
        sf = AsyncMock()
        db_ctx = AsyncMock()
        db_ctx.__aenter__ = AsyncMock(return_value=db_ctx)
        db_ctx.__aexit__  = AsyncMock(return_value=False)
        db_ctx.execute    = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=1)))
        db_ctx.commit     = AsyncMock()
        sf.return_value   = db_ctx
        return MarketRegimeSnapshotService(session_factory=sf)

    @pytest.mark.asyncio
    async def test_event_driven_priority(self):
        svc = self._make_svc()
        snap = await svc.classify_and_store(
            vix=25.0, nifty_regime="NORMAL",
            breadth_score=10.0, advance_decline_ratio=1.2,
            nifty_close=None, event_active=True,
        )
        assert snap["regime"] == "EVENT_DRIVEN"

    @pytest.mark.asyncio
    async def test_high_vix_extreme(self):
        svc = self._make_svc()
        snap = await svc.classify_and_store(
            vix=32.0, nifty_regime="NORMAL",
            breadth_score=5.0, advance_decline_ratio=0.5,
            nifty_close=None, event_active=False,
        )
        assert snap["regime"] == "HIGH_VOLATILITY"
        assert snap.get("sub_regime") == "EXTREME"

    @pytest.mark.asyncio
    async def test_strong_trending(self):
        svc = self._make_svc()
        snap = await svc.classify_and_store(
            vix=14.0, nifty_regime="TRENDING_BULLISH",
            breadth_score=55.0, advance_decline_ratio=2.5,
            nifty_close=None, event_active=False,
        )
        assert snap["regime"] == "STRONG_TRENDING"

    @pytest.mark.asyncio
    async def test_range_bound_default(self):
        svc = self._make_svc()
        snap = await svc.classify_and_store(
            vix=14.0, nifty_regime="NORMAL",
            breadth_score=5.0, advance_decline_ratio=1.0,
            nifty_close=None, event_active=False,
        )
        assert snap["regime"] == "RANGE_BOUND"


# ── §8 ExecutionReadinessService ─────────────────────────────────────────────

class TestExecutionReadinessService:
    def _make_svc(self):
        from core.application.services.execution_readiness_service import ExecutionReadinessService
        redis = AsyncMock()
        redis.ping = AsyncMock(return_value=True)
        return ExecutionReadinessService(redis_client=redis)

    @pytest.mark.asyncio
    async def test_score_has_8_checks(self):
        svc = self._make_svc()
        result = await svc.evaluate(
            "NIFTY",
            broker_connected=True,
            oc_snapshot_ts=datetime.now(UTC),
            quote_ts=datetime.now(UTC),
            option_play_oi=5000,
            risk_engine_healthy=True,
        )
        assert result["total"] == 8
        assert 0 <= result["score"] <= 100

    @pytest.mark.asyncio
    async def test_score_drops_for_missing_oc(self):
        svc = self._make_svc()
        with_oc = await svc.evaluate(
            "NIFTY",
            broker_connected=True,
            oc_snapshot_ts=datetime.now(UTC),
            quote_ts=datetime.now(UTC),
            option_play_oi=5000,
        )
        without_oc = await svc.evaluate(
            "NIFTY",
            broker_connected=True,
            oc_snapshot_ts=None,
            quote_ts=datetime.now(UTC),
            option_play_oi=5000,
        )
        assert with_oc["score"] > without_oc["score"]


# ── §12 ScannerReplayService._extract_top_scores ─────────────────────────────

class TestScannerReplayExtractTopScores:
    def test_top_10_by_score(self):
        from core.application.services.scanner_replay_service import _extract_top_scores
        results = [
            {"symbol": f"SYM{i}", "adjusted_score": float(i), "confidence": 0.5,
             "outcome": "rejected", "direction": "LONG"}
            for i in range(20)
        ]
        top = _extract_top_scores(results)
        assert len(top) == 10
        assert top[0]["adjusted_score"] == 19.0
        assert top[-1]["adjusted_score"] == 10.0

    def test_empty_results(self):
        from core.application.services.scanner_replay_service import _extract_top_scores
        assert _extract_top_scores([]) == []

    def test_none_scores_excluded(self):
        from core.application.services.scanner_replay_service import _extract_top_scores
        results = [
            {"symbol": "A", "adjusted_score": 80.0, "confidence": 0.9, "outcome": "accepted", "direction": "LONG"},
            {"symbol": "B", "adjusted_score": None, "confidence": 0.5, "outcome": "rejected", "direction": None},
        ]
        top = _extract_top_scores(results)
        assert len(top) == 1
        assert top[0]["symbol"] == "A"


# ── §13 ResourceMonitorService ───────────────────────────────────────────────

class TestResourceMonitorService:
    def test_collect_cpu_psutil_optional(self):
        from core.application.services.resource_monitor_service import _collect_cpu
        result = _collect_cpu()
        assert isinstance(result, dict)
        # Should either have percent or note about missing psutil
        assert "percent" in result or "available" in result or "error" in result

    def test_collect_memory_psutil_optional(self):
        from core.application.services.resource_monitor_service import _collect_memory
        result = _collect_memory()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_collect_redis_unavailable(self):
        from core.application.services.resource_monitor_service import ResourceMonitorService
        svc = ResourceMonitorService(redis_client=None, db_engine=None)
        result = await svc._collect_redis()
        assert result == {"available": False}

    def test_collect_db_unavailable(self):
        from core.application.services.resource_monitor_service import ResourceMonitorService
        svc = ResourceMonitorService(redis_client=None, db_engine=None)
        result = svc._collect_db()
        assert result == {"available": False}

    def test_record_request(self):
        from core.application.services.resource_monitor_service import ResourceMonitorService
        svc = ResourceMonitorService()
        svc.record_request()
        svc.record_request(error=True)
        assert svc._request_count == 2
        assert svc._request_errors == 1
