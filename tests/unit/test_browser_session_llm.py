"""Tests for the browser-session LLM client (ADR-0018)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from juris.llm.browser_session import BrowserSessionLLM


@pytest.mark.asyncio
async def test_complete_relays_prompt_to_transport_and_wraps_reply() -> None:
    transport = AsyncMock()
    transport.send = AsyncMock(return_value="A resposta da sessão")
    llm = BrowserSessionLLM(transport=transport, model="claude.ai")

    resp = await llm.complete("Qual a tese?", system="Você é estrategista")

    assert resp.content == "A resposta da sessão"
    assert resp.model == "claude.ai"
    kwargs = transport.send.await_args.kwargs
    assert kwargs["prompt"] == "Qual a tese?"
    assert kwargs["system"] == "Você é estrategista"


def test_model_name() -> None:
    llm = BrowserSessionLLM(transport=AsyncMock(), model="chatgpt")
    assert llm.model_name == "chatgpt"
