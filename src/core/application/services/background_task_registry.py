"""BackgroundTaskRegistry — supervised async task manager.

Launches coroutine-based background tasks (PortfolioMonitorService,
DeadMansSwitchService) and restarts them on failure with exponential backoff.

Design (D-12):
  - Each registered task runs in its own asyncio.Task.
  - On task failure: log the exception, wait backoff_seconds (doubles each
    failure up to max_backoff_seconds), then restart.
  - Shutdown: cancel all tasks and wait for them to complete.
  - No task is silently swallowed — every exception is logged at ERROR level.

Usage:
    registry = BackgroundTaskRegistry()
    registry.register("portfolio_monitor", portfolio_monitor.run)
    registry.register("dead_mans_switch", dead_mans_switch.run)
    await registry.start()
    # ... application runs ...
    await registry.shutdown()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

_log = logging.getLogger(__name__)

_INITIAL_BACKOFF_SECONDS: float = 1.0
_MAX_BACKOFF_SECONDS: float = 60.0


class BackgroundTaskRegistry:
    """Supervised registry for long-running background coroutines."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._factories: dict[str, Callable[[], Coroutine[Any, Any, None]]] = {}
        self._running = False

    def register(
        self,
        name: str,
        factory: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Register a background task factory.

        The factory must be a zero-argument callable returning a coroutine.
        It is called every time the task starts or restarts.
        """
        self._factories[name] = factory

    async def start(self) -> None:
        """Launch all registered tasks under supervision."""
        self._running = True
        for name, factory in self._factories.items():
            self._tasks[name] = asyncio.create_task(
                self._supervised_run(name, factory),
                name=f"bg:{name}",
            )
        _log.info("background_task_registry started tasks=%s", list(self._tasks))

    async def shutdown(self) -> None:
        """Cancel all supervised tasks and wait for them to finish."""
        self._running = False
        for name, task in self._tasks.items():
            if not task.done():
                task.cancel()
                _log.info("background_task_registry cancelling task=%s", name)
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        _log.info("background_task_registry shutdown complete")

    async def _supervised_run(
        self,
        name: str,
        factory: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        backoff = _INITIAL_BACKOFF_SECONDS
        while self._running:
            try:
                await factory()
                # Factory returned normally — task ended cleanly
                _log.info("background_task name=%s exited normally", name)
                return
            except asyncio.CancelledError:
                _log.info("background_task name=%s cancelled", name)
                raise
            except Exception:
                _log.exception(
                    "background_task name=%s failed — restarting in %.1fs",
                    name,
                    backoff,
                )
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                _log.info("background_task name=%s cancelled during backoff", name)
                raise
            backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
