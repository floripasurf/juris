"""Browser-session LLM backend — the lawyer's own Claude/ChatGPT subscription.

Per ADR-0018, frontier-quality PII work runs through the lawyer's existing
subscription, driven by a browser extension on their machine (the session never
leaves their perimeter — a local capability in the ADR-0015 split-trust model).

This client is provider/extension-agnostic: it relays the prompt over an injected
:class:`BrowserTransport` and wraps the reply. The transport is the seam — a
custom extension, an existing third-party extension, or a Playwright driver can
all implement it. Structured output is not enforced server-side; callers embed
the format in the prompt (as the strategy/draft agents already do).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from juris.core.observability import get_logger
from juris.llm.base import AbstractLLM, LLMResponse

logger = get_logger(__name__)


@runtime_checkable
class BrowserTransport(Protocol):
    """Relays a prompt to the lawyer's browser session and returns the reply."""

    async def send(self, *, prompt: str, system: str | None) -> str: ...


class BrowserSessionLLM(AbstractLLM):
    """Drives the lawyer's browser LLM session through a :class:`BrowserTransport`."""

    def __init__(
        self,
        transport: BrowserTransport,
        model: str = "claude.ai (browser session)",
    ) -> None:
        self._transport = transport
        self._model = model

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        # schema/max_tokens/temperature are part of the interface but not
        # controllable through a chat UI — the prompt carries the desired format.
        content = await self._transport.send(prompt=prompt, system=system)
        logger.info("browser_session_complete", model=self._model, chars=len(content))
        return LLMResponse(content=content, model=self._model)

    @property
    def model_name(self) -> str:
        return self._model
