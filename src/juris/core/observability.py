"""Structured logging and observability setup."""

from __future__ import annotations

import uuid

import structlog


def setup_logging(log_level: str = "DEBUG", json_output: bool = False) -> None:
    """Configure structlog for the application."""
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.get_level_from_name(log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def new_correlation_id() -> str:
    """Generate a correlation ID for request/job tracing."""
    return str(uuid.uuid4())[:12]


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a named logger instance."""
    return structlog.get_logger(name)  # type: ignore[return-value]
