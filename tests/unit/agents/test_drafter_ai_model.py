"""C5 (spec 2026-07-05): ai_model = modelo da geração da minuta final; tese em campo próprio."""

from __future__ import annotations

from typing import Any, cast

import pytest

from juris.agents.citation_verifier import MarkerCitationVerifier
from juris.agents.drafter import DrafterAgent, DraftRequest
from juris.agents.researcher import Researcher, ResearchQuery, ResearchResult
from juris.defesas.context import ProcessoContext
from juris.llm.base import AbstractLLM, LLMResponse
from juris.repertory.peticoes.models import TipoPeticao
from juris.repertory.retrieval.service import RepertoryService, RetrievalResult


class FakeLLM(AbstractLLM):
    def __init__(self, content: str, model: str = "fake-llm") -> None:
        self._content = content
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0, **kwargs) -> LLMResponse:
        return LLMResponse(content=self._content, model=self._model)


class FakeResearcher:
    async def research(self, query: ResearchQuery) -> ResearchResult:
        return ResearchResult(
            thesis=query.thesis,
            supporting=[
                RetrievalResult(
                    source_id="src-1",
                    score=0.91,
                    hierarchy=2,
                    hierarchy_label="STJ precedente",
                    tribunal="STJ",
                    texto="Trecho verificado do precedente recuperado.",
                )
            ],
            opposing=[],
            coverage_note="Favoraveis: 1 STJ precedente. Contrarias: nenhuma encontrada.",
        )


def _agent(llm_content: str, *, model: str = "fake-llm") -> DrafterAgent:
    repertory = cast(RepertoryService, object())
    return DrafterAgent(
        llm=FakeLLM(llm_content, model=model),
        repertory=repertory,
        researcher=cast(Researcher, FakeResearcher()),
        verifier=MarkerCitationVerifier(repertory),
    )


def _request() -> DraftRequest:
    return DraftRequest(
        numero_cnj="0001234-56.2026.8.13.0001",
        tribunal="tjmg",
        tipo_peticao=TipoPeticao.CONTESTACAO,
        thesis="Inexistência de inadimplemento.",
        max_revision_rounds=0,
    )


def _context() -> ProcessoContext:
    return ProcessoContext(
        numero_cnj="0001234-56.2026.8.13.0001",
        tribunal="tjmg",
        classe="Ação de cobrança",
    )


@pytest.mark.asyncio
async def test_ai_model_records_final_generation_model() -> None:
    agent = _agent("Minuta com [CITE:src-1].", model="chatgpt (browser session)")
    result = await agent.draft(_request(), _context())
    assert result.ai_model == "chatgpt (browser session)"


@pytest.mark.asyncio
async def test_ai_model_thesis_only_when_thesis_is_inferred() -> None:
    # _request() passa thesis explícita → nenhuma chamada de tese → campo None
    agent = _agent("Minuta com [CITE:src-1].", model="fake-llm")
    result = await agent.draft(_request(), _context())
    assert result.ai_model_thesis is None
