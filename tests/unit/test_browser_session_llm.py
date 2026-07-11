"""Browser-session LLM: BrowserReply, helpers canônicos e verdade de execução (spec 2026-07-05)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from juris.llm.browser_session import (
    BrowserReply,
    BrowserSessionLLM,
    browser_model_label,
    label_to_browser_provider,
    normalize_browser_provider,
    provider_divergence,
)


class TestHelpers:
    def test_browser_model_label(self) -> None:
        assert browser_model_label("chatgpt") == "chatgpt (browser session)"
        assert browser_model_label("claude") == "claude.ai (browser session)"
        assert browser_model_label(None) == "claude.ai (browser session)"

    def test_normalize_browser_provider(self) -> None:
        assert normalize_browser_provider("claude") == "claude"
        assert normalize_browser_provider("claude.ai") == "claude"
        assert normalize_browser_provider("chatgpt") == "chatgpt"
        assert normalize_browser_provider("chatgpt.com") == "chatgpt"
        assert normalize_browser_provider("chat.openai.com") == "chatgpt"
        # inesperado / rótulo legado de UI / vazio → None, nunca adivinha
        assert normalize_browser_provider("gemini") is None
        assert normalize_browser_provider("claude.ai (browser session)") is None
        assert normalize_browser_provider(None) is None
        assert normalize_browser_provider("") is None

    def test_label_to_browser_provider_inverts_only_our_labels(self) -> None:
        assert label_to_browser_provider("chatgpt (browser session)") == "chatgpt"
        assert label_to_browser_provider("claude.ai (browser session)") == "claude"
        assert label_to_browser_provider("qwen3:latest") is None
        assert label_to_browser_provider(None) is None

    def test_provider_divergence(self) -> None:
        assert provider_divergence("chatgpt", "chatgpt") is None
        assert provider_divergence(None, "claude") is None      # nada declarado
        assert provider_divergence("chatgpt", None) is None     # real desconhecido/local
        msg = provider_divergence("chatgpt", "claude")
        assert msg is not None
        assert "ChatGPT" in msg and "Claude.ai" in msg


@pytest.mark.asyncio
async def test_complete_uses_reported_provider_as_model_truth() -> None:
    transport = AsyncMock()
    transport.send = AsyncMock(return_value=BrowserReply(content="Resposta", provider="chatgpt"))
    llm = BrowserSessionLLM(transport=transport, model="claude.ai (browser session)")

    resp = await llm.complete("Qual a tese?", system="Você é estrategista")

    assert resp.content == "Resposta"
    assert resp.model == "chatgpt (browser session)"  # real vence o pedido
    kwargs = transport.send.await_args.kwargs
    assert kwargs["prompt"] == "Qual a tese?"
    assert kwargs["system"] == "Você é estrategista"


@pytest.mark.asyncio
async def test_complete_falls_back_to_requested_label_without_provider() -> None:
    transport = AsyncMock()
    transport.send = AsyncMock(return_value=BrowserReply(content="Resposta", provider=None))
    llm = BrowserSessionLLM(transport=transport, model="chatgpt (browser session)")

    resp = await llm.complete("Qual a tese?")

    assert resp.model == "chatgpt (browser session)"  # extensão antiga → label pedido


@pytest.mark.asyncio
async def test_unexpected_provider_value_does_not_break_completion() -> None:
    transport = AsyncMock()
    transport.send = AsyncMock(return_value=BrowserReply(content="Resposta", provider="algo-novo"))
    llm = BrowserSessionLLM(transport=transport, model="claude.ai (browser session)")

    resp = await llm.complete("Qual a tese?")

    assert resp.content == "Resposta"                       # nunca falha por observabilidade
    assert resp.model == "claude.ai (browser session)"      # não-canônico → label pedido


def test_model_name() -> None:
    llm = BrowserSessionLLM(transport=AsyncMock(), model="chatgpt (browser session)")
    assert llm.model_name == "chatgpt (browser session)"
