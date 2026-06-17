"""Correlation ID management via ContextVar.

Each async request task gets an isolated correlation_id that travels through
every log line for that request. The ID is sourced from the incoming
X-Correlation-ID header (set by an upstream gateway) or freshly generated.

The structlog merge_contextvars processor (wired in logging/setup.py) picks
up the correlation_id automatically — no manual passing required.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

import structlog

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def generate_correlation_id() -> str:
    """Return a new random UUID4 string."""
    return str(uuid.uuid4())


def set_correlation_id(value: str) -> None:
    """Bind a correlation ID to the current async context."""
    _correlation_id.set(value)


def get_correlation_id() -> str:
    """Return the correlation ID for the current async context.

    Returns an empty string when called outside a request context so callers
    never need to guard against None.
    """
    return _correlation_id.get()


def bind_structlog_context() -> None:
    """Write the current correlation_id into structlog's contextvars.

    Must be called after set_correlation_id(). The merge_contextvars processor
    in the shared pipeline then includes correlation_id in every subsequent log
    call made within this async context.
    """
    structlog.contextvars.bind_contextvars(correlation_id=get_correlation_id())


def clear_structlog_context() -> None:
    """Remove all bound structlog contextvars for the current async context.

    Call at the end of every request (in a finally block) to prevent context
    leakage between requests that share an asyncio worker.
    """
    structlog.contextvars.clear_contextvars()
