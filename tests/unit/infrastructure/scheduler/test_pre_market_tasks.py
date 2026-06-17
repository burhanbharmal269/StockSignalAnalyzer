"""Unit tests for PreMarketScheduler — job registration and lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


class TestPreMarketSchedulerInit:
    def test_registers_instrument_refresh_job(self) -> None:
        from core.infrastructure.scheduler.pre_market_tasks import PreMarketScheduler

        service = MagicMock()
        with patch("core.infrastructure.scheduler.pre_market_tasks.AsyncIOScheduler") as mock_sched:
            scheduler_instance = MagicMock()
            mock_sched.return_value = scheduler_instance
            PreMarketScheduler(service)
            scheduler_instance.add_job.assert_called_once()
            job_kwargs = scheduler_instance.add_job.call_args[1]
            assert job_kwargs["id"] == "instrument_master_refresh"
            assert job_kwargs["replace_existing"] is True

    def test_start_calls_scheduler_start(self) -> None:
        from core.infrastructure.scheduler.pre_market_tasks import PreMarketScheduler

        service = MagicMock()
        with patch("core.infrastructure.scheduler.pre_market_tasks.AsyncIOScheduler") as mock_sched:
            scheduler_instance = MagicMock()
            mock_sched.return_value = scheduler_instance
            ps = PreMarketScheduler(service)
            ps.start()
            scheduler_instance.start.assert_called_once()

    def test_stop_calls_scheduler_shutdown(self) -> None:
        from core.infrastructure.scheduler.pre_market_tasks import PreMarketScheduler

        service = MagicMock()
        with patch("core.infrastructure.scheduler.pre_market_tasks.AsyncIOScheduler") as mock_sched:
            scheduler_instance = MagicMock()
            mock_sched.return_value = scheduler_instance
            ps = PreMarketScheduler(service)
            ps.stop()
            scheduler_instance.shutdown.assert_called_once_with(wait=False)


class TestRunInstrumentRefresh:
    async def test_calls_service_refresh(self) -> None:
        from core.domain.value_objects.instrument_refresh_result import (
            InstrumentRefreshResult,
            RefreshStatus,
        )
        from core.infrastructure.scheduler.pre_market_tasks import PreMarketScheduler

        service = MagicMock()
        mock_result = InstrumentRefreshResult(
            status=RefreshStatus.SUCCESS,
            instruments_added=100,
            instruments_updated=50,
            instruments_deactivated=5,
            duration_ms=1200,
        )
        service.refresh = AsyncMock(return_value=mock_result)

        with patch("core.infrastructure.scheduler.pre_market_tasks.AsyncIOScheduler"):
            ps = PreMarketScheduler(service)
            await ps._run_instrument_refresh()

        service.refresh.assert_awaited_once()

    async def test_handles_refresh_exception_gracefully(self) -> None:
        from core.infrastructure.scheduler.pre_market_tasks import PreMarketScheduler

        service = MagicMock()
        service.refresh = AsyncMock(side_effect=RuntimeError("network error"))

        with patch("core.infrastructure.scheduler.pre_market_tasks.AsyncIOScheduler"):
            ps = PreMarketScheduler(service)
            # Should not raise
            await ps._run_instrument_refresh()
