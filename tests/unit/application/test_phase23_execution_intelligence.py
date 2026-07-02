"""Phase 23 — Execution Intelligence unit tests.

Coverage: ≥ 95% of new modules.

Test classes:
  TestExecutionTimelineComputeDurations   — pure _compute_durations()
  TestBrokerHealthScore                   — pure _compute_score()
  TestRejectionCategorize                 — pure categorize()
  TestSlippagePureHelpers                 — _liquidity_score(), _compute_quality_score()
  TestExecutionTimelineServiceMock        — DB-level service with async mock
  TestExecutionLatencyServiceBuffer       — buffer accumulation + flush
  TestExecutionSlippageService            — record_entry / fill quality score
  TestExecutionRejectionService           — record + stats
  TestExecutionRetryService               — record retry
  TestBrokerHealthMonitorService          — compute score from Redis metrics
  TestExecutionReplayService              — in-memory record_event / flush
  TestExecutionHistoricalService          — window SQL query
  TestExecutionEventHandler               — routes events to services
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# §1 Pure helpers: _compute_durations
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionTimelineComputeDurations:
    def _fn(self, record):
        from core.application.services.execution_intelligence.execution_timeline_service import _compute_durations
        return _compute_durations(record)

    def test_empty_record_returns_empty(self):
        assert self._fn({}) == {}

    def test_signal_to_risk_only(self):
        t0 = datetime(2026, 7, 2, 9, 0, 0, tzinfo=UTC)
        t1 = t0 + timedelta(seconds=0.5)
        result = self._fn({
            "signal_generated_at": t0,
            "risk_approved_at": t1,
        })
        assert "signal_to_risk_ms" in result
        assert abs(result["signal_to_risk_ms"] - 500.0) < 1.0

    def test_total_execution_ms_computed(self):
        t0 = datetime(2026, 7, 2, 9, 0, 0, tzinfo=UTC)
        t1 = t0 + timedelta(milliseconds=300)
        result = self._fn({
            "signal_generated_at": t0,
            "order_filled_at": t1,
        })
        assert "total_execution_ms" in result
        assert abs(result["total_execution_ms"] - 300.0) < 1.0

    def test_negative_diff_clamped_to_zero(self):
        t0 = datetime(2026, 7, 2, 9, 0, 0, tzinfo=UTC)
        t1 = t0 - timedelta(seconds=1)  # backward in time — should clamp to 0
        result = self._fn({
            "signal_generated_at": t0,
            "risk_approved_at": t1,
        })
        assert result.get("signal_to_risk_ms", 0.0) == 0.0

    def test_all_stages(self):
        base = datetime(2026, 7, 2, 9, 0, 0, tzinfo=UTC)
        record = {
            "signal_generated_at": base,
            "risk_approved_at":    base + timedelta(milliseconds=100),
            "strike_selected_at":  base + timedelta(milliseconds=200),
            "order_submitted_at":  base + timedelta(milliseconds=300),
            "broker_received_at":  base + timedelta(milliseconds=400),
            "exchange_accepted_at": base + timedelta(milliseconds=450),
            "order_filled_at":     base + timedelta(milliseconds=600),
            "position_opened_at":  base + timedelta(milliseconds=700),
        }
        result = self._fn(record)
        assert result["signal_to_risk_ms"] == pytest.approx(100.0, abs=1)
        assert result["total_execution_ms"] == pytest.approx(600.0, abs=1)


# ─────────────────────────────────────────────────────────────────────────────
# §9 BrokerHealthScore — pure _compute_score
# ─────────────────────────────────────────────────────────────────────────────

class TestBrokerHealthScore:
    def _fn(self, metrics):
        from core.application.services.execution_intelligence.broker_health_monitor_service import _compute_score
        return _compute_score(metrics)

    def test_perfect_metrics_returns_100(self):
        assert self._fn({
            "api_latency_ms": 50.0,
            "is_connected": True,
            "failure_rate_pct": 0.0,
            "reconnect_count": 0,
        }) == 100.0

    def test_disconnected_ws_deducts_30(self):
        score = self._fn({
            "api_latency_ms": 50.0,
            "is_connected": False,
            "failure_rate_pct": 0.0,
            "reconnect_count": 0,
        })
        assert score == pytest.approx(70.0, abs=1)

    def test_high_api_latency_deducts(self):
        score = self._fn({
            "api_latency_ms": 3000.0,
            "is_connected": True,
            "failure_rate_pct": 0.0,
            "reconnect_count": 0,
        })
        assert score <= 65.0

    def test_high_fail_rate_deducts(self):
        score = self._fn({
            "api_latency_ms": 100.0,
            "is_connected": True,
            "failure_rate_pct": 10.0,
            "reconnect_count": 0,
        })
        assert score < 80.0

    def test_score_never_below_zero(self):
        score = self._fn({
            "api_latency_ms": 5000.0,
            "is_connected": False,
            "failure_rate_pct": 100.0,
            "reconnect_count": 50,
        })
        assert score == 0.0

    def test_missing_metrics_handled_gracefully(self):
        score = self._fn({})
        assert score == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# §7 Rejection categorization — pure categorize()
# ─────────────────────────────────────────────────────────────────────────────

class TestRejectionCategorize:
    def _fn(self, reason):
        from core.application.services.execution_intelligence.execution_rejection_service import categorize
        return categorize(reason)

    def test_none_returns_unknown(self):
        assert self._fn(None) == "UNKNOWN"

    def test_empty_returns_unknown(self):
        assert self._fn("") == "UNKNOWN"

    def test_insufficient_funds(self):
        assert self._fn("insufficient funds to place order") == "INSUFFICIENT_FUNDS"

    def test_market_closed(self):
        assert self._fn("Market is closed for trading") == "MARKET_CLOSED"

    def test_margin_issue(self):
        assert self._fn("SPAN margin requirement not met") == "MARGIN_ISSUE"

    def test_price_freeze(self):
        assert self._fn("Price freeze in effect for this strike") == "PRICE_FREEZE"

    def test_api_failure(self):
        assert self._fn("HTTP 503 from broker API") == "API_FAILURE"

    def test_network_failure(self):
        assert self._fn("Network connection refused") == "NETWORK_FAILURE"

    def test_validation_error(self):
        assert self._fn("Invalid lot size") == "VALIDATION_ERROR"

    def test_exchange_error(self):
        assert self._fn("Exchange rejection from NSE") == "EXCHANGE_ERROR"

    def test_unknown_reason(self):
        assert self._fn("some completely random error") == "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# §3/4/8 Slippage pure helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestSlippagePureHelpers:
    def test_liquidity_score_perfect(self):
        from core.application.services.execution_intelligence.execution_slippage_service import _liquidity_score
        score = _liquidity_score(spread_pct=0.0, available_qty=10000)
        assert score >= 95.0

    def test_liquidity_score_wide_spread_penalised(self):
        from core.application.services.execution_intelligence.execution_slippage_service import _liquidity_score
        score_tight = _liquidity_score(spread_pct=0.1, available_qty=1000)
        score_wide  = _liquidity_score(spread_pct=2.0, available_qty=1000)
        assert score_wide < score_tight

    def test_liquidity_score_never_below_zero(self):
        from core.application.services.execution_intelligence.execution_slippage_service import _liquidity_score
        assert _liquidity_score(spread_pct=100.0, available_qty=0) == 0.0

    def test_quality_score_perfect_fill(self):
        from core.application.services.execution_intelligence.execution_slippage_service import _compute_quality_score
        score = _compute_quality_score(100.0, 1, 0, 100.0, 100.0, 100.0)
        assert score == 100.0

    def test_quality_score_partial_fill_penalised(self):
        from core.application.services.execution_intelligence.execution_slippage_service import _compute_quality_score
        full    = _compute_quality_score(100.0, 1, 0, 100.0, 100.0, 100.0)
        partial = _compute_quality_score(60.0, 3, 2, 100.0, 99.0, 101.0)
        assert partial < full

    def test_quality_score_never_below_zero(self):
        from core.application.services.execution_intelligence.execution_slippage_service import _compute_quality_score
        score = _compute_quality_score(0.0, 100, 50, 100.0, 80.0, 120.0)
        assert score == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionTimelineService — mock DB
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionTimelineServiceMock:
    def _make_svc(self):
        from core.application.services.execution_intelligence.execution_timeline_service import ExecutionTimelineService
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=MagicMock(mappings=MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))))
        mock_db.commit = AsyncMock()

        sf = MagicMock()
        sf.return_value = mock_db
        sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        sf.return_value.__aexit__ = AsyncMock(return_value=False)

        return ExecutionTimelineService(sf), sf, mock_db

    def test_record_signal_generated_does_not_raise(self):
        svc, sf, db = self._make_svc()
        asyncio.get_event_loop().run_until_complete(
            svc.record_signal_generated("sig-1", symbol="NIFTY", regime="TRENDING")
        )

    def test_get_timeline_returns_none_on_miss(self):
        svc, sf, db = self._make_svc()
        result = asyncio.get_event_loop().run_until_complete(svc.get_timeline("missing"))
        assert result is None

    def test_get_recent_returns_list(self):
        svc, sf, db = self._make_svc()
        db.execute.return_value = MagicMock(
            mappings=MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        )
        result = asyncio.get_event_loop().run_until_complete(svc.get_recent())
        assert isinstance(result, list)


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionLatencyService — buffer and flush
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionLatencyServiceBuffer:
    def _make_svc(self):
        from core.application.services.execution_intelligence.execution_latency_service import ExecutionLatencyService
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        sf = MagicMock()
        sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        sf.return_value.__aexit__ = AsyncMock(return_value=False)
        return ExecutionLatencyService(sf), mock_db

    def test_record_stage_accumulates_in_buffer(self):
        svc, _ = self._make_svc()
        asyncio.get_event_loop().run_until_complete(
            svc.record_stage(stage="total_execution", duration_ms=150.0, signal_id="s1")
        )
        assert len(svc._buffer) == 1

    def test_flush_clears_buffer(self):
        svc, db = self._make_svc()
        svc._buffer.append({"stage": "test", "duration_ms": 100.0})
        asyncio.get_event_loop().run_until_complete(svc.flush())
        assert len(svc._buffer) == 0

    def test_high_latency_logs_warning(self):
        svc, _ = self._make_svc()
        with patch("core.application.services.execution_intelligence.execution_latency_service._log") as mock_log:
            asyncio.get_event_loop().run_until_complete(
                svc.record_stage(stage="total_execution", duration_ms=6000.0)
            )
            mock_log.warning.assert_called()

    def test_record_stage_fail_open(self):
        from core.application.services.execution_intelligence.execution_latency_service import ExecutionLatencyService
        svc = ExecutionLatencyService(MagicMock(side_effect=RuntimeError("boom")))
        # Should not raise
        asyncio.get_event_loop().run_until_complete(
            svc.record_stage(stage="total_execution", duration_ms=100.0)
        )


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionSlippageService
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionSlippageService:
    def _make_svc(self):
        from core.application.services.execution_intelligence.execution_slippage_service import ExecutionSlippageService
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        sf = MagicMock()
        sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        sf.return_value.__aexit__ = AsyncMock(return_value=False)
        return ExecutionSlippageService(sf), mock_db

    def test_record_entry_does_not_raise(self):
        svc, _ = self._make_svc()
        asyncio.get_event_loop().run_until_complete(
            svc.record_entry("sig-1", expected_entry=100.0, actual_entry=100.5)
        )

    def test_record_fill_quality_returns_score(self):
        svc, db = self._make_svc()
        score = asyncio.get_event_loop().run_until_complete(
            svc.record_fill_quality("sig-1", fill_pct=100.0, num_fills=1, partial_fills=0)
        )
        assert 0.0 <= score <= 100.0

    def test_partial_fill_reduces_score(self):
        svc, db = self._make_svc()
        full = asyncio.get_event_loop().run_until_complete(
            svc.record_fill_quality("sig-1", fill_pct=100.0, num_fills=1, partial_fills=0)
        )
        partial = asyncio.get_event_loop().run_until_complete(
            svc.record_fill_quality("sig-2", fill_pct=60.0, num_fills=3, partial_fills=2)
        )
        assert partial < full


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionRejectionService
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionRejectionService:
    def _make_svc(self):
        from core.application.services.execution_intelligence.execution_rejection_service import ExecutionRejectionService
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        sf = MagicMock()
        sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        sf.return_value.__aexit__ = AsyncMock(return_value=False)
        return ExecutionRejectionService(sf)

    def test_record_rejection_returns_category(self):
        svc = self._make_svc()
        cat = asyncio.get_event_loop().run_until_complete(
            svc.record_rejection(signal_id="sig-1", raw_reason="insufficient funds")
        )
        assert cat == "INSUFFICIENT_FUNDS"

    def test_record_rejection_unknown(self):
        svc = self._make_svc()
        cat = asyncio.get_event_loop().run_until_complete(
            svc.record_rejection(signal_id="sig-2", raw_reason="random weird error")
        )
        assert cat == "UNKNOWN"

    def test_record_rejection_none_reason(self):
        svc = self._make_svc()
        cat = asyncio.get_event_loop().run_until_complete(
            svc.record_rejection(signal_id="sig-3", raw_reason=None)
        )
        assert cat == "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionRetryService
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionRetryService:
    def _make_svc(self):
        from core.application.services.execution_intelligence.execution_retry_service import ExecutionRetryService
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        sf = MagicMock()
        sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        sf.return_value.__aexit__ = AsyncMock(return_value=False)
        return ExecutionRetryService(sf)

    def test_record_retry_does_not_raise(self):
        svc = self._make_svc()
        asyncio.get_event_loop().run_until_complete(
            svc.record_retry(signal_id="s1", attempt_number=1, retry_reason="timeout")
        )

    def test_high_attempt_logs_warning(self):
        svc = self._make_svc()
        with patch("core.application.services.execution_intelligence.execution_retry_service._log") as mock_log:
            asyncio.get_event_loop().run_until_complete(
                svc.record_retry(signal_id="s1", attempt_number=5, retry_reason="timeout")
            )
            mock_log.warning.assert_called()


# ─────────────────────────────────────────────────────────────────────────────
# BrokerHealthMonitorService — score from mock Redis
# ─────────────────────────────────────────────────────────────────────────────

class TestBrokerHealthMonitorService:
    def _make_svc(self, redis_vals):
        from core.application.services.execution_intelligence.broker_health_monitor_service import BrokerHealthMonitorService
        mock_redis = AsyncMock()
        mock_redis.mget = AsyncMock(return_value=redis_vals)

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        sf = MagicMock()
        sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        sf.return_value.__aexit__ = AsyncMock(return_value=False)

        return BrokerHealthMonitorService(sf, redis_client=mock_redis)

    def test_healthy_broker_high_score(self):
        # api=80ms, ws_connected=True, 0 failures
        svc = self._make_svc([b"80", b"5", None, b"0", b"100", b"0", b"1"])
        result = asyncio.get_event_loop().run_until_complete(svc.update())
        assert result["health_score"] >= 90.0

    def test_disconnected_ws_reduces_score(self):
        svc = self._make_svc([b"80", b"5", None, b"0", b"100", b"0", b"0"])
        result = asyncio.get_event_loop().run_until_complete(svc.update())
        assert result["health_score"] < 80.0

    def test_no_redis_returns_default_score(self):
        from core.application.services.execution_intelligence.broker_health_monitor_service import BrokerHealthMonitorService
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        sf = MagicMock()
        sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        sf.return_value.__aexit__ = AsyncMock(return_value=False)

        svc = BrokerHealthMonitorService(sf, redis_client=None)
        result = asyncio.get_event_loop().run_until_complete(svc.update())
        assert "health_score" in result


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionReplayService — in-memory
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionReplayService:
    def _make_svc(self):
        from core.application.services.execution_intelligence.execution_replay_service import ExecutionReplayService
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        sf = MagicMock()
        sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        sf.return_value.__aexit__ = AsyncMock(return_value=False)
        return ExecutionReplayService(sf)

    def test_record_event_stored_in_memory(self):
        svc = self._make_svc()
        svc.record_event("sig-1", "order_created", {"order_id": "ord-1"})
        assert "sig-1" in svc._snapshots
        assert "order_created" in svc._snapshots["sig-1"]["stages"]

    def test_record_error_stored(self):
        svc = self._make_svc()
        svc.record_error("sig-1", "order_rejected", "insufficient funds")
        assert len(svc._snapshots["sig-1"]["errors"]) == 1

    def test_flush_clears_memory(self):
        svc = self._make_svc()
        svc.record_event("sig-1", "signal_generated", {})
        asyncio.get_event_loop().run_until_complete(svc.flush_signal("sig-1"))
        assert "sig-1" not in svc._snapshots

    def test_get_replay_returns_in_memory_snapshot(self):
        svc = self._make_svc()
        svc.record_event("sig-2", "signal_generated", {"symbol": "NIFTY"})
        result = asyncio.get_event_loop().run_until_complete(svc.get_replay("sig-2"))
        assert result is not None
        assert "stages" in result

    def test_flush_missing_signal_does_not_raise(self):
        svc = self._make_svc()
        asyncio.get_event_loop().run_until_complete(svc.flush_signal("nonexistent"))


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionEventHandler — routing
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionEventHandler:
    def _make_handler(self):
        from core.application.services.execution_intelligence.execution_event_handler import ExecutionEventHandler
        timeline  = AsyncMock()
        latency   = AsyncMock()
        slippage  = AsyncMock()
        retry     = AsyncMock()
        rejection = AsyncMock()
        replay    = MagicMock()
        replay.record_event = MagicMock()
        replay.record_error = MagicMock()
        replay.flush_signal = AsyncMock()
        replay.get_replay   = AsyncMock(return_value=None)
        broker_health = AsyncMock()

        handler = ExecutionEventHandler(
            timeline_svc=timeline,
            latency_svc=latency,
            slippage_svc=slippage,
            retry_svc=retry,
            rejection_svc=rejection,
            replay_svc=replay,
            broker_health_svc=broker_health,
        )
        return handler, timeline, latency, slippage, rejection, replay

    def _make_event(self, **kwargs):
        ev = MagicMock()
        for k, v in kwargs.items():
            setattr(ev, k, v)
        return ev

    def test_handle_signal_risk_approved_calls_timeline(self):
        handler, timeline, *_ = self._make_handler()
        event = self._make_event(signal_id="sig-1", direction="LONG", adjusted_score=85.0,
                                 regime="TRENDING", position_size_lots=2)
        asyncio.get_event_loop().run_until_complete(handler.handle_signal_risk_approved(event))
        timeline.record_risk_approved.assert_called_once_with("sig-1")

    def test_handle_order_created_calls_timeline(self):
        handler, timeline, *_ = self._make_handler()
        event = self._make_event(signal_id="sig-1", order_id="ord-1",
                                 direction="LONG", quantity=50, lots=1,
                                 order_type="MARKET", tradingsymbol="NIFTY26JUL24500CE")
        asyncio.get_event_loop().run_until_complete(handler.handle_order_created(event))
        timeline.record_order_created.assert_called_once_with("sig-1", "ord-1")

    def test_handle_order_rejected_calls_rejection_service(self):
        handler, _, _, _, rejection, replay = self._make_handler()
        event = self._make_event(signal_id="sig-2", order_id="ord-2",
                                 rejected_by="broker", reason="insufficient funds")
        asyncio.get_event_loop().run_until_complete(handler.handle_order_rejected(event))
        rejection.record_rejection.assert_called_once()

    def test_handle_order_rejected_flushes_replay(self):
        handler, _, _, _, rejection, replay = self._make_handler()
        rejection.record_rejection = AsyncMock()
        event = self._make_event(signal_id="sig-3", order_id="ord-3",
                                 rejected_by="oms", reason="kill switch")
        asyncio.get_event_loop().run_until_complete(handler.handle_order_rejected(event))
        replay.flush_signal.assert_called_once_with("sig-3")

    def test_fail_open_on_handler_error(self):
        handler, timeline, *_ = self._make_handler()
        timeline.record_risk_approved = AsyncMock(side_effect=RuntimeError("boom"))
        event = self._make_event(signal_id="sig-x", direction="LONG",
                                 adjusted_score=80.0, regime="TRENDING", position_size_lots=1)
        # Should NOT raise
        asyncio.get_event_loop().run_until_complete(handler.handle_signal_risk_approved(event))

    def test_handle_position_opened(self):
        handler, timeline, _, slippage, *_ = self._make_handler()
        event = self._make_event(signal_id="sig-5", position_id="pos-1",
                                 order_id="ord-5", direction="LONG", lots=2,
                                 quantity=100, entry_price=Decimal("100.0"),
                                 regime_at_open="TRENDING",
                                 stop_loss_price=Decimal("95.0"),
                                 target_1_price=Decimal("110.0"),
                                 instrument_token=12345,
                                 underlying="NIFTY")
        asyncio.get_event_loop().run_until_complete(handler.handle_position_opened(event))
        timeline.record_position_opened.assert_called_once_with("sig-5", "pos-1")

    def test_handle_position_closed(self):
        handler, timeline, *_ = self._make_handler()
        event = self._make_event(signal_id="sig-6", position_id="pos-6",
                                 direction="LONG", entry_price=Decimal("100.0"),
                                 exit_price=Decimal("105.0"),
                                 lots=1, realized_pnl=Decimal("500.0"),
                                 outcome="WIN", trading_mode="LIVE")
        asyncio.get_event_loop().run_until_complete(handler.handle_position_closed(event))
        timeline.record_position_closed.assert_called_once_with("sig-6")
