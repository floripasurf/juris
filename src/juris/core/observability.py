"""Structured logging and observability setup."""

from __future__ import annotations

import logging
import uuid
from typing import cast

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
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def new_correlation_id() -> str:
    """Generate a correlation ID for request/job tracing."""
    return str(uuid.uuid4())[:12]


def bind_tenant_log_context(tenant_id: str) -> None:
    """Bind ``tenant_id`` to the structlog context so every subsequent log in this
    request/task carries it — per-tenant observability (ADR-0015 Phase 2).

    Context vars are task-local, so binding per request never leaks across tenants.
    """
    structlog.contextvars.bind_contextvars(tenant_id=tenant_id)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a named logger instance."""
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))
