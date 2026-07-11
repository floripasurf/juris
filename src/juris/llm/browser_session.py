"""Browser-session LLM backend — the lawyer's own Claude/ChatGPT subscription.

Per ADR-0018, frontier-quality PII work runs through the lawyer's existing
subscription, driven by a browser extension on their machine (the session never
leaves their perimeter — a local capability in the ADR-0015 split-trust model).

This client is provider-agnostic: it relays the prompt over an injected
:class:`BrowserTransport` and wraps the reply. The extension reports back the
CANONICAL provider id it actually drove ("claude"/"chatgpt"); display labels are
always derived from the canonical id, never compared as UI text (spec 2026-07-05).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from juris.core.observability import get_logger
from juris.llm.base import AbstractLLM, LLMResponse

logger = get_logger(__name__)

BrowserProvider = Literal["claude", "chatgpt"]

_LABELS: dict[BrowserProvider, str] = {
    "claude": "claude.ai (browser session)",
    "chatgpt": "chatgpt (browser session)",
}
_CANONICAL: dict[str, BrowserProvider] = {
    "claude": "claude",
    "claude.ai": "claude",
    "chatgpt": "chatgpt",
    "chatgpt.com": "chatgpt",
    "chat.openai.com": "chatgpt",
}
_DISPLAY_NAMES: dict[BrowserProvider, str] = {"claude": "Claude.ai", "chatgpt": "ChatGPT"}


def browser_model_label(provider: BrowserProvider | None) -> str:
    """Rótulo de exibição derivado do id canônico (claude é o default histórico)."""
    return _LABELS[provider or "claude"]


def normalize_browser_provider(raw: str | None) -> BrowserProvider | None:
    """Normaliza o valor cru do wire para o id canônico; desconhecido → None.

    Leniente por design: um valor inesperado de uma extensão desatualizada nunca
    pode derrubar a completion — campo de observabilidade não falha resposta.
    """
    if not raw:
        return None
    return _CANONICAL.get(raw.strip().lower())


def label_to_browser_provider(label: str | None) -> BrowserProvider | None:
    """Inverte APENAS os nossos dois rótulos de exibição; qualquer outro → None."""
    for provider, known in _LABELS.items():
        if label == known:
            return provider
    return None


def provider_divergence(
    declared: BrowserProvider | None, actual: BrowserProvider | None
) -> str | None:
    """Mensagem de aviso quando o declarado e o realmente dirigido divergem.

    ``None`` quando: nada declarado, real desconhecido (extensão antiga ou
    fallback local — o ai_model local já evidencia isso), ou quando batem.
    """
    if declared is None or actual is None or declared == actual:
        return None
    return (
        f"Você declarou {_DISPLAY_NAMES[declared]} como IA de preferência, "
        f"mas a extensão dirigiu {_DISPLAY_NAMES[actual]}."
    )


@dataclass(frozen=True, slots=True)
class BrowserReply:
    """Resposta do transporte: conteúdo + id canônico cru reportado pela extensão."""

    content: str
    provider: str | None = None


@runtime_checkable
class BrowserTransport(Protocol):
    """Relays a prompt to the lawyer's browser session and returns the reply."""

    async def send(self, *, prompt: str, system: str | None) -> BrowserReply: ...


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
        *,
        contains_pii: bool = False,
    ) -> LLMResponse:
        # schema/max_tokens/temperature/contains_pii are part of the interface but not
        # controllable through a chat UI — the prompt carries the desired format.
        reply = await self._transport.send(prompt=prompt, system=system)
        actual = normalize_browser_provider(reply.provider)
        model = browser_model_label(actual) if actual else self._model
        logger.info("browser_session_complete", model=model, chars=len(reply.content))
        return LLMResponse(content=reply.content, model=model)

    @property
    def model_name(self) -> str:
        return self._model
