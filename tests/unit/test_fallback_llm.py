"""Tests for the LLM fallback (browser session → cloud de-id / local)."""

from __future__ import annotations

import pytest

from juris.core.fallback_llm import FallbackLLM
from juris.llm.base import AbstractLLM, LLMResponse


class _StubLLM(AbstractLLM):
    def __init__(self, name, *, fail=False):
        self._name = name
        self._fail = fail

    async def complete(self, prompt, system=None, schema=None, max_tokens=1024, temperature=0.0):
        if self._fail:
            raise RuntimeError("sessão do browser indisponível")
        return LLMResponse(content=f"{self._name}:{prompt}", model=self._name)

    @property
    def model_name(self):
        return self._name


@pytest.mark.asyncio
async def test_uses_primary_when_it_works() -> None:
    llm = FallbackLLM(_StubLLM("browser"), _StubLLM("cloud"))
    resp = await llm.complete("oi")
    assert resp.content == "browser:oi"


@pytest.mark.asyncio
async def test_falls_back_when_primary_fails() -> None:
    events = []
    llm = FallbackLLM(
        _StubLLM("browser", fail=True), _StubLLM("cloud"), on_fallback=lambda e: events.append(str(e))
    )
    resp = await llm.complete("oi")
    assert resp.content == "cloud:oi"  # fell back
    assert events and "indisponível" in events[0]


@pytest.mark.asyncio
async def test_ai_of_preference_deidentifies_before_the_browser_and_falls_back() -> None:
    from juris.core.fallback_llm import build_ai_of_preference

    seen = {}

    class _CapturingBrowser(AbstractLLM):
        async def complete(self, prompt, system=None, schema=None, max_tokens=1024, temperature=0.0):
            seen["prompt"] = prompt
            return LLMResponse(content="ok", model="browser")

        @property
        def model_name(self):
            return "browser"

    llm = build_ai_of_preference(_CapturingBrowser(), _StubLLM("cloud"))
    await llm.complete("O CPF do autor é 529.982.247-25 e o nome é João da Silva.")
    # mandatory de-id: the raw CPF must NOT reach the browser session
    assert "529.982.247-25" not in seen["prompt"]


@pytest.mark.asyncio
async def test_ai_of_preference_falls_back_when_browser_session_dies() -> None:
    from juris.core.fallback_llm import build_ai_of_preference

    llm = build_ai_of_preference(_StubLLM("browser", fail=True), _StubLLM("cloud"))
    resp = await llm.complete("texto")
    assert resp.content == "cloud:texto"  # browser died → cloud fallback
