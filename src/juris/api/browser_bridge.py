"""Native Messaging bridge to the browser LLM session (ADR-0018).

The juris-side transport: serialises a :class:`CompletionRequest`, sends it over
an injected channel (the Native Messaging chain extension ↔ host ↔ local agent),
and unwraps the :class:`CompletionResponse`. Channel-agnostic — the actual wire
(stdio native host, localhost WS to the local agent) implements ``BridgeChannel``.

This satisfies the ``BrowserTransport`` protocol structurally, so a
``BrowserSessionLLM`` can drive the lawyer's Claude/ChatGPT session through it.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from juris.api.ws_schemas import CompletionRequest, CompletionResponse
from juris.core.observability import get_logger

logger = get_logger(__name__)


@runtime_checkable
class BridgeChannel(Protocol):
    """Sends a JSON message over the bridge and awaits the reply."""

    async def request(self, message: dict[str, object]) -> dict[str, object]: ...


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
        if not response.success:
            msg = response.error or "browser session completion failed"
            raise RuntimeError(msg)
        logger.info("browser_bridge_completion", request_id=request.request_id)
        return response.content or ""
