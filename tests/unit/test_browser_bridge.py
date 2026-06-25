"""Tests for the Native Messaging browser bridge transport (ADR-0018)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from juris.api.browser_bridge import NativeBridgeTransport, WebSocketBridgeChannel


class _FakeConn:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.sent: str | None = None
        self.closed = False

    async def send(self, data: str) -> None:
        self.sent = data

    async def recv(self) -> str:
        return self.reply

    async def close(self) -> None:
        self.closed = True


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


@pytest.mark.asyncio
async def test_ws_channel_sends_json_returns_parsed_and_closes() -> None:
    conn = _FakeConn('{"request_id": "x", "success": true, "content": "oi"}')
    channel = WebSocketBridgeChannel(connect=AsyncMock(return_value=conn))

    out = await channel.request({"prompt": "tese", "request_id": "x"})

    assert out["content"] == "oi"
    assert json.loads(conn.sent)["prompt"] == "tese"  # message serialised and sent
    assert conn.closed is True  # connection released even on success


@pytest.mark.asyncio
async def test_ws_channel_closes_connection_on_error() -> None:
    conn = _FakeConn("not json")  # recv returns junk → json.loads raises
    channel = WebSocketBridgeChannel(connect=AsyncMock(return_value=conn))

    with pytest.raises(json.JSONDecodeError):
        await channel.request({"request_id": "x"})

    assert conn.closed is True


@pytest.mark.asyncio
async def test_ws_channel_drives_transport_end_to_end() -> None:
    conn = _FakeConn('{"request_id": "x", "success": true, "content": "A tese"}')
    transport = NativeBridgeTransport(WebSocketBridgeChannel(connect=AsyncMock(return_value=conn)))

    assert await transport.send(prompt="Qual a tese?", system=None) == "A tese"
