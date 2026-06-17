"""Unit tests for correlation ID tracing (ContextVar-based)."""

from __future__ import annotations

import asyncio

from core.infrastructure.observability.tracing import (
    bind_structlog_context,
    clear_structlog_context,
    generate_correlation_id,
    get_correlation_id,
    set_correlation_id,
)


class TestGenerateCorrelationId:
    def test_returns_string(self) -> None:
        cid = generate_correlation_id()
        assert isinstance(cid, str)

    def test_looks_like_uuid4(self) -> None:
        import uuid

        cid = generate_correlation_id()
        parsed = uuid.UUID(cid)
        assert parsed.version == 4

    def test_unique_per_call(self) -> None:
        ids = {generate_correlation_id() for _ in range(50)}
        assert len(ids) == 50


class TestSetGetCorrelationId:
    def test_default_is_empty_string(self) -> None:
        # ContextVar default is "" — never None
        # Run in a fresh task to avoid bleed from other tests.
        result: list[str] = []

        async def _check() -> None:
            result.append(get_correlation_id())

        asyncio.run(_check())
        assert result[0] == ""

    def test_set_then_get_roundtrip(self) -> None:
        set_correlation_id("test-id-123")
        assert get_correlation_id() == "test-id-123"

    def test_overwrite(self) -> None:
        set_correlation_id("first")
        set_correlation_id("second")
        assert get_correlation_id() == "second"

    def test_isolated_between_async_tasks(self) -> None:
        """Two concurrent tasks must not share correlation IDs."""
        results: dict[str, str] = {}

        async def _task(name: str, cid: str) -> None:
            set_correlation_id(cid)
            await asyncio.sleep(0)  # yield so tasks interleave
            results[name] = get_correlation_id()

        async def _run() -> None:
            await asyncio.gather(
                _task("a", "id-for-a"),
                _task("b", "id-for-b"),
            )

        asyncio.run(_run())
        assert results["a"] == "id-for-a"
        assert results["b"] == "id-for-b"


class TestStructlogContextBinding:
    def test_bind_does_not_raise(self) -> None:
        set_correlation_id("bind-test")
        bind_structlog_context()  # should not raise

    def test_clear_does_not_raise(self) -> None:
        set_correlation_id("clear-test")
        bind_structlog_context()
        clear_structlog_context()  # should not raise

    def test_clear_then_get_still_returns_contextvar_value(self) -> None:
        set_correlation_id("persist-test")
        bind_structlog_context()
        clear_structlog_context()
        # ContextVar is separate from structlog contextvars — clearing structlog
        # does NOT clear the ContextVar, so get_correlation_id() still works.
        assert get_correlation_id() == "persist-test"

    def test_bind_includes_correlation_id_in_structlog(self) -> None:
        import structlog

        set_correlation_id("structlog-test")
        bind_structlog_context()
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("correlation_id") == "structlog-test"
        clear_structlog_context()
