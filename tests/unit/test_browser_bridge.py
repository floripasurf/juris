"""Tests for the Native Messaging browser bridge transport (ADR-0018)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from juris.api.browser_bridge import NativeBridgeTransport, WebSocketBridgeChannel, validate_bridge_url


class _FakeConn:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.sent: str | None = None
        self.closed = False
        self._req_id: str | None = None

    async def send(self, data: str) -> None:
        self.sent = data
        try:
            self._req_id = json.loads(data).get("request_id")
        except (json.JSONDecodeError, AttributeError):
            self._req_id = None

    async def recv(self) -> str:
        # Echo the request_id into the reply, as the real host correlates it.
        try:
            obj = json.loads(self.reply)
        except json.JSONDecodeError:
            return self.reply
        if self._req_id is not None:
            obj["request_id"] = self._req_id
        return json.dumps(obj)

    async def close(self) -> None:
        self.closed = True


def _echo_channel(*, success: bool = True, content: str = "A resposta", error: str | None = None) -> AsyncMock:
    """A channel whose reply echoes the request_id (as the real host does)."""

    async def _request(message: dict) -> dict:
        return {"request_id": message["request_id"], "success": success, "content": content, "error": error}

    channel = AsyncMock()
    channel.request = AsyncMock(side_effect=_request)
    return channel


@pytest.mark.asyncio
async def test_send_relays_completion_request_and_returns_content() -> None:
    channel = _echo_channel(content="A resposta")
    transport = NativeBridgeTransport(channel)

    result = await transport.send(prompt="Tese?", system="Sys")

    assert result == "A resposta"
    sent = channel.request.await_args.args[0]
    assert sent["prompt"] == "Tese?"
    assert sent["system"] == "Sys"
    assert sent["request_id"]  # a correlation id is generated


@pytest.mark.asyncio
async def test_send_attests_deidentified_and_carries_bridge_token() -> None:
    channel = _echo_channel()
    transport = NativeBridgeTransport(channel, token="bridge-secret")  # noqa: S106 - test fixture

    await transport.send(prompt="Autor [NOME_1]", system=None)

    sent = channel.request.await_args.args[0]
    # The content script refuses to drive the session unless this attestation is present.
    assert sent["deidentified"] is True
    # Bridge auth travels with the request for the native host to validate.
    assert sent["token"] == "bridge-secret"  # noqa: S105 - test fixture


@pytest.mark.asyncio
async def test_send_bridge_token_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("JURIS_BROWSER_BRIDGE_TOKEN", "env-secret")  # noqa: S105 - test fixture
    channel = _echo_channel()
    transport = NativeBridgeTransport(channel)

    await transport.send(prompt="x", system=None)

    assert channel.request.await_args.args[0]["token"] == "env-secret"  # noqa: S105 - test fixture


@pytest.mark.asyncio
async def test_send_raises_on_failure() -> None:
    transport = NativeBridgeTransport(_echo_channel(success=False, error="sessão expirada"))

    with pytest.raises(RuntimeError, match="sessão expirada"):
        await transport.send(prompt="x", system=None)


@pytest.mark.asyncio
async def test_send_rejects_mismatched_request_id() -> None:
    channel = AsyncMock()
    channel.request = AsyncMock(
        return_value={"request_id": "OUTRO", "success": True, "content": "x"}
    )
    transport = NativeBridgeTransport(channel)

    with pytest.raises(RuntimeError, match="pedido errado"):
        await transport.send(prompt="Tese?", system=None)


def test_validate_bridge_url_accepts_loopback_without_secret_material() -> None:
    assert validate_bridge_url("ws://127.0.0.1:8787") == "ws://127.0.0.1:8787"
    assert validate_bridge_url("ws://[::1]:8787/") == "ws://[::1]:8787/"


def test_validate_bridge_url_rejects_remote_or_credentialed_urls() -> None:
    for url in (
        "ws://bridge.example.test:8787",
        "ws://127.0.0.1:8787?token=secret",
        "ws://user:secret@127.0.0.1:8787",
        "ws://127.0.0.1:8787/path",
    ):
        with pytest.raises(ValueError):
            validate_bridge_url(url)


def test_ws_channel_to_localhost_rejects_remote_bridge_url() -> None:
    with pytest.raises(ValueError, match="loopback"):
        WebSocketBridgeChannel.to_localhost("ws://bridge.example.test:8787")


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
async def test_ws_channel_times_out_while_connecting() -> None:
    async def slow_connect() -> _FakeConn:
        await asyncio.sleep(1)
        return _FakeConn("{}")

    channel = WebSocketBridgeChannel(connect=slow_connect, timeout=0.01)

    with pytest.raises(TimeoutError):
        await channel.request({"request_id": "x"})


@pytest.mark.asyncio
async def test_ws_channel_drives_transport_end_to_end() -> None:
    conn = _FakeConn('{"request_id": "x", "success": true, "content": "A tese"}')
    transport = NativeBridgeTransport(WebSocketBridgeChannel(connect=AsyncMock(return_value=conn)))

    assert await transport.send(prompt="Qual a tese?", system=None) == "A tese"
