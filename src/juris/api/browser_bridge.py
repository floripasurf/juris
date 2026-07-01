"""Native Messaging bridge to the browser LLM session (ADR-0018).

The juris-side transport: serialises a :class:`CompletionRequest`, sends it over
an injected channel (the Native Messaging chain extension ↔ host ↔ local agent),
and unwraps the :class:`CompletionResponse`. Channel-agnostic — the actual wire
(stdio native host, localhost WS to the local agent) implements ``BridgeChannel``.

This satisfies the ``BrowserTransport`` protocol structurally, so a
``BrowserSessionLLM`` can drive the lawyer's Claude/ChatGPT session through it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import uuid
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import urlparse, urlunparse

from juris.api.ws_schemas import CompletionRequest, CompletionResponse
from juris.core.observability import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger(__name__)


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    cleaned = host.strip().strip("[]").lower()
    if cleaned == "localhost":
        return True
    try:
        return ipaddress.ip_address(cleaned).is_loopback
    except ValueError:
        return False


def validate_bridge_host(host: str) -> str:
    """Ensure the browser bridge binds/dials only loopback interfaces."""
    if not _is_loopback_host(host):
        msg = "browser bridge deve usar apenas loopback (127.0.0.1, ::1 ou localhost)."
        raise ValueError(msg)
    return host


def validate_bridge_url(url: str) -> str:
    """Validate the localhost WS URL used to reach the Native Messaging bridge."""
    parsed = urlparse(url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or parsed.port is None:
        msg = "JURIS_BROWSER_BRIDGE_URL deve ser ws://127.0.0.1:<porta>."
        raise ValueError(msg)
    if not _is_loopback_host(parsed.hostname):
        msg = "JURIS_BROWSER_BRIDGE_URL deve apontar para loopback, nunca host remoto."
        raise ValueError(msg)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        msg = "JURIS_BROWSER_BRIDGE_URL não deve conter credenciais, query ou fragmento."
        raise ValueError(msg)
    if parsed.path not in {"", "/"}:
        msg = "JURIS_BROWSER_BRIDGE_URL deve apontar para a raiz do bridge."
        raise ValueError(msg)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


@runtime_checkable
class BridgeChannel(Protocol):
    """Sends a JSON message over the bridge and awaits the reply."""

    async def request(self, message: dict[str, object]) -> dict[str, object]: ...


class _WSConnection(Protocol):
    async def send(self, data: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


class WebSocketBridgeChannel:
    """BridgeChannel over a localhost WS to the Native Messaging host.

    One request per connection (no correlation needed): open → send JSON →
    await one reply → close. The ``connect`` factory is injected so the
    websockets dependency stays at the edge and the channel is testable.
    """

    def __init__(
        self,
        connect: Callable[[], Awaitable[_WSConnection]],
        *,
        timeout: float = 60.0,
    ) -> None:
        self._connect = connect
        self._timeout = timeout

    @classmethod
    def to_localhost(cls, url: str, *, timeout: float = 60.0) -> WebSocketBridgeChannel:
        """Build a channel that dials ``url`` (e.g. ws://127.0.0.1:8765) via websockets."""
        bridge_url = validate_bridge_url(url)

        async def _connect() -> _WSConnection:
            import websockets

            return await websockets.connect(bridge_url)  # type: ignore[return-value]

        return cls(_connect, timeout=timeout)

    async def request(self, message: dict[str, object]) -> dict[str, object]:
        conn = await asyncio.wait_for(self._connect(), self._timeout)
        try:
            await asyncio.wait_for(conn.send(json.dumps(message)), self._timeout)
            raw = await asyncio.wait_for(conn.recv(), self._timeout)
        finally:
            await conn.close()
        parsed: dict[str, object] = json.loads(raw)
        return parsed


class NativeBridgeTransport:
    """BrowserTransport over the Native Messaging bridge."""

    def __init__(
        self,
        channel: BridgeChannel,
        model: str = "claude.ai (browser session)",
        *,
        token: str | None = None,
    ) -> None:
        self._channel = channel
        self._model = model
        # Bridge auth secret. Falls back to $JURIS_BROWSER_BRIDGE_TOKEN so the agent
        # and native host can be paired without threading it through every caller.
        self._token = token or os.environ.get("JURIS_BROWSER_BRIDGE_TOKEN") or None

    async def send(self, *, prompt: str, system: str | None) -> str:
        request = CompletionRequest(
            request_id=uuid.uuid4().hex,
            prompt=prompt,
            system=system,
            model=self._model,
            # This transport is only ever used behind DeidentifyingLLM
            # (build_ai_of_preference), so the payload here is already de-identified.
            deidentified=True,
            token=self._token,
        )
        raw = await self._channel.request(request.model_dump())
        response = CompletionResponse(**raw)
        if response.request_id != request.request_id:
            msg = (
                f"resposta correlaciona com pedido errado "
                f"(esperado {request.request_id}, veio {response.request_id})"
            )
            raise RuntimeError(msg)
        if not response.success:
            msg = response.error or "browser session completion failed"
            raise RuntimeError(msg)
        logger.info("browser_bridge_completion", request_id=request.request_id)
        return response.content or ""
