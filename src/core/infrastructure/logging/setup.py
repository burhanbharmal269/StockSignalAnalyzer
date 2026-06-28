"""Structured logging configuration using structlog.

Produces JSON in production and pretty console output in development.
Includes a secrets scrubber processor that redacts sensitive field values
before any log record reaches a handler.

Reference: docs/09_CLAUDE_EXECUTION_RULES.md (Logging Rules)
           docs/23_SECURITY_BASELINE.md (Section 7 — Secrets Scrubbing)
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

# ---------------------------------------------------------------------------
# Secrets scrubber
# ---------------------------------------------------------------------------

_SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "token",
        "api_key",
        "secret",
        "access_key",
        "private_key",
        "credential",
        "access_token",
        "refresh_token",
        "authorization",
    }
)

_SENSITIVE_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI keys
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]+"),  # Auth headers
    re.compile(r"\b[0-9a-f]{64}\b"),  # 64-char hex (key material)
)

_REDACTED = "[REDACTED]"


def _scrub_value(value: Any) -> Any:  # noqa: ANN401
    """Redact a single value if it matches a sensitive pattern."""
    if not isinstance(value, str):
        return value
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        if pattern.search(value):
            return _REDACTED
    return value


def secrets_scrubber(
    logger: WrappedLogger,  # noqa: ARG001
    method: str,  # noqa: ARG001
    event_dict: EventDict,
) -> EventDict:
    """structlog processor that redacts sensitive fields and values.

    Runs before any renderer so secrets never reach log files, stdout,
    or remote log aggregators.
    """
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_FIELD_NAMES:
            event_dict[key] = _REDACTED
        else:
            event_dict[key] = _scrub_value(event_dict[key])
    return event_dict


# ---------------------------------------------------------------------------
# Public configuration entry point
# ---------------------------------------------------------------------------


def configure_logging(
    log_level: str = "INFO",
    log_format: str = "console",
) -> None:
    """Configure structlog and the stdlib logging root handler.

    Call once at application startup before any log statements.

    Args:
        log_level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        log_format: 'console' for pretty dev output, 'json' for production.
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        secrets_scrubber,
        structlog.processors.StackInfoRenderer(),
        # ExceptionRenderer belongs in ProcessorFormatter.processors only (not here).
        # Placing it in shared_processors causes structlog to emit a UserWarning about
        # format_exc_info conflicts when both the pre-chain and the formatter render exc_info.
    ]

    if log_format == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.ExceptionRenderer(),
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    # httpx/httpcore log every TCP frame at DEBUG — suppress below WARNING
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # watchfiles logs every file-change scan at DEBUG
    logging.getLogger("watchfiles").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for the given module name.

    Usage:
        logger = get_logger(__name__)
        logger.info("event_name", key="value")
    """
    bound: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return bound
