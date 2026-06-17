"""Unit tests for BackgroundTaskRegistry."""

from __future__ import annotations

import asyncio

import pytest

from core.application.services.background_task_registry import BackgroundTaskRegistry


class TestBackgroundTaskRegistry:
    async def test_register_and_start_launches_task(self) -> None:
        registry = BackgroundTaskRegistry()
        ran = []

        async def factory() -> None:
            ran.append(True)

        registry.register("test", factory)
        await registry.start()
        await asyncio.sleep(0.05)
        await registry.shutdown()
        assert ran

    async def test_shutdown_cancels_running_tasks(self) -> None:
        registry = BackgroundTaskRegistry()
        cancelled = []

        async def long_running() -> None:
            try:
                await asyncio.sleep(9999)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        registry.register("worker", long_running)
        await registry.start()
        await asyncio.sleep(0.05)
        await registry.shutdown()
        assert cancelled

    async def test_restart_on_failure(self) -> None:
        registry = BackgroundTaskRegistry()
        call_count = []

        async def flaky() -> None:
            call_count.append(1)
            if len(call_count) < 2:
                raise RuntimeError("first run fails")
            await asyncio.sleep(9999)

        registry.register("flaky", flaky)
        await registry.start()
        await asyncio.sleep(2.5)  # allow restart with 1s initial backoff
        await registry.shutdown()
        assert len(call_count) >= 2

    async def test_empty_registry_start_and_shutdown(self) -> None:
        registry = BackgroundTaskRegistry()
        await registry.start()
        await registry.shutdown()

    async def test_multiple_tasks_all_launched(self) -> None:
        registry = BackgroundTaskRegistry()
        seen = set()

        async def make_factory(name: str):
            async def factory() -> None:
                seen.add(name)
                await asyncio.sleep(9999)
            return factory

        registry.register("a", await make_factory("a"))
        registry.register("b", await make_factory("b"))
        await registry.start()
        await asyncio.sleep(0.05)
        await registry.shutdown()
        assert "a" in seen
        assert "b" in seen

    async def test_cancelled_error_not_swallowed(self) -> None:
        registry = BackgroundTaskRegistry()

        async def blocking() -> None:
            await asyncio.sleep(9999)

        registry.register("blocker", blocking)
        await registry.start()
        await asyncio.sleep(0.05)
        await registry.shutdown()
        # If we reach here shutdown completed cleanly
