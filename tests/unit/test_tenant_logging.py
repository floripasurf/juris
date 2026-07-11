"""Tenant-scoped logging — every log in a request carries tenant_id (multi-tenant obs)."""

from __future__ import annotations

import structlog

from juris.core.observability import bind_tenant_log_context


def test_bind_tenant_puts_tenant_id_in_log_context() -> None:
    structlog.contextvars.clear_contextvars()
    try:
        bind_tenant_log_context("escritorio-a")
        assert structlog.contextvars.get_contextvars().get("tenant_id") == "escritorio-a"
    finally:
        structlog.contextvars.clear_contextvars()


def test_bound_tenant_appears_in_emitted_log() -> None:
    # setup_logging puts merge_contextvars in the pipeline, so a real log event picks
    # up the bound tenant_id. Test that processor directly (capture_logs bypasses it).
    structlog.contextvars.clear_contextvars()
    try:
        bind_tenant_log_context("escritorio-b")
        event = structlog.contextvars.merge_contextvars(None, "info", {"event": "x"})
        assert event["tenant_id"] == "escritorio-b"
    finally:
        structlog.contextvars.clear_contextvars()
