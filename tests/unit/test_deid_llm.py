"""Tests for the de-identifying LLM wrapper (ADR-0016 — cloud-safe main path)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from juris.core.deid_llm import DeidentifyingLLM


@dataclass
class _Resp:
    content: str
    model: str = "claude"


class _Delegate:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.received_prompt: str | None = None
        self.received_system: str | None = None

    async def complete(self, prompt, system=None, schema=None, max_tokens=1024, temperature=0.0):
        self.received_prompt = prompt
        self.received_system = system
        return _Resp(content=self._reply)

    @property
    def model_name(self) -> str:
        return "claude-test"


@pytest.mark.asyncio
async def test_strips_pii_before_delegate_and_reidentifies_response() -> None:
    delegate = _Delegate("O réu [CPF_1] deve pagar")
    llm = DeidentifyingLLM(delegate, allow_partial=True)

    resp = await llm.complete("Caso do réu, CPF 123.456.789-09", system="Sistema sobre 123.456.789-09")

    assert "123.456.789-09" not in delegate.received_prompt  # PII never reaches the cloud
    assert "[CPF_1]" in delegate.received_prompt
    assert "123.456.789-09" not in (delegate.received_system or "")  # system de-identified too
    assert resp.content == "O réu 123.456.789-09 deve pagar"  # restored for the caller


@pytest.mark.asyncio
async def test_fails_closed_on_partial_deid_without_optin() -> None:
    llm = DeidentifyingLLM(_Delegate("x"), allow_partial=False)
    with pytest.raises(ValueError, match="parcial"):
        await llm.complete("CPF 123.456.789-09")


def test_model_name_passthrough() -> None:
    assert DeidentifyingLLM(_Delegate("x")).model_name == "claude-test"


@pytest.mark.asyncio
async def test_default_constructor_fails_closed_on_partial_deid() -> None:
    llm = DeidentifyingLLM(_Delegate("x"))
    with pytest.raises(ValueError, match="parcial"):
        await llm.complete("Pedido simples sem NER.")


def test_cloud_safe_llm_uses_ner_and_fails_closed_by_default() -> None:
    from juris.core.deid_llm import cloud_safe_llm

    llm = cloud_safe_llm(_Delegate("x"))
    assert llm._allow_partial is False  # names handled → gate closed
    assert llm._ner is not None


def test_cloud_safe_llm_structured_only_when_ner_disabled() -> None:
    from juris.core.deid_llm import cloud_safe_llm

    llm = cloud_safe_llm(_Delegate("x"), require_ner=False)
    assert llm._allow_partial is True  # structured-only fallback (names may remain)
    assert llm._ner is None
