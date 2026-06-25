"""Tests for the Native Messaging browser bridge transport (ADR-0018)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from juris.api.browser_bridge import NativeBridgeTransport


@pytest.mark.asyncio
async def test_send_relays_completion_request_and_returns_content() -> None:
    channel = AsyncMock()
    channel.request = AsyncMock(
        return_value={"request_id": "x", "success": True, "content": "A resposta"}
    )
    transport = NativeBridgeTransport(channel)

    result = await transport.send(prompt="Tese?", system="Sys")

    assert result == "A resposta"
    sent = channel.request.await_args.args[0]
    assert sent["prompt"] == "Tese?"
    assert sent["system"] == "Sys"
    assert sent["request_id"]  # a correlation id is generated


@pytest.mark.asyncio
async def test_send_raises_on_failure() -> None:
    channel = AsyncMock()
    channel.request = AsyncMock(
        return_value={"request_id": "x", "success": False, "error": "sessão expirada"}
    )
    transport = NativeBridgeTransport(channel)

    with pytest.raises(RuntimeError, match="sessão expirada"):
        await transport.send(prompt="x", system=None)
