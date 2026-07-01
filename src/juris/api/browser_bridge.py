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
import json
import uuid
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from juris.api.ws_schemas import CompletionRequest, CompletionResponse
from juris.core.observability import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger(__name__)


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

        async def _connect() -> _WSConnection:
            import websockets

            return await websockets.connect(url)  # type: ignore[return-value]

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
    ) -> None:
        self._channel = channel
        self._model = model

    async def send(self, *, prompt: str, system: str | None) -> str:
        request = CompletionRequest(
            request_id=uuid.uuid4().hex,
            prompt=prompt,
            system=system,
            model=self._model,
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
