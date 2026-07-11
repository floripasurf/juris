"""Estilo do escritório (L4): exemplar de peça do próprio tenant no style_text.

Harness espelha test_grounding.py (FakeLLM/FakeResearcher/_agent/_request/_context).
"""

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
    def __init__(self, content: str) -> None:
        self._content = content

    @property
    def model_name(self) -> str:
        return "fake-llm"

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0, **kwargs) -> LLMResponse:
        return LLMResponse(content=self._content, model=self.model_name)


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


class _FakeRepertoryStyle:
    """Repertory fake: sem templates genéricos; com exemplar do escritório."""

    def __init__(self, exemplar: RetrievalResult) -> None:
        self._exemplar = exemplar

    def find_style_exemplar(
        self,
        tipo_peticao: str,
        area_direito: str | None = None,
        tenant_id: str | None = None,
    ) -> RetrievalResult | None:
        return self._exemplar if tenant_id == "escritorio-a" else None

    def find_template(
        self,
        tipo_peticao: str,
        area_direito: str | None = None,
        tenant_id: str | None = None,
    ) -> RetrievalResult | None:
        return None


_EXEMPLAR = RetrievalResult(
    source_id="src-peca",
    score=1.0,
    hierarchy=7,
    hierarchy_label="Nivel 7",
    tribunal="",
    texto="EXCELENTÍSSIMO SENHOR... estrutura da peça do escritório " * 50,
    tipo="peca_escritorio",
    uso="estilo",
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
async def test_exemplar_do_escritorio_entra_no_style_text() -> None:
    captured: dict[str, Any] = {}

    class _SpyLLM(FakeLLM):
        async def complete(
            self,
            prompt: str,
            system: str | None = None,
            schema: dict[str, Any] | None = None,
            max_tokens: int = 1024,
            temperature: float = 0.0, **kwargs) -> LLMResponse:
            captured["prompt"] = prompt
            return await super().complete(prompt, system, schema, max_tokens, temperature)

    agent = DrafterAgent(
        llm=_SpyLLM("Minuta com [CITE:src-1]."),
        repertory=cast(RepertoryService, _FakeRepertoryStyle(_EXEMPLAR)),
        researcher=cast(Researcher, FakeResearcher()),
        verifier=MarkerCitationVerifier(cast(RepertoryService, object())),
        tenant_id="escritorio-a",
    )
    result = await agent.draft(_request(), _context())
    assert "EXEMPLO DE ESTILO DO SEU ESCRITÓRIO (não citar como fonte)" in captured["prompt"]
    assert result.is_grounded


@pytest.mark.asyncio
async def test_ACEITACAO_CENTRAL_peca_interna_citada_e_bloqueada() -> None:  # noqa: N802
    """O critério da Fase 1: LLM cita a peça interna (estilo) -> verifier bloqueia."""
    exemplar = _EXEMPLAR
    agent = DrafterAgent(
        llm=FakeLLM("Conforme [CITE:src-peca], procede."),  # cita o EXEMPLAR (estilo!)
        repertory=cast(RepertoryService, _FakeRepertoryStyle(exemplar)),
        researcher=cast(Researcher, FakeResearcher()),  # allowed_ids = {src-1}
        verifier=MarkerCitationVerifier(cast(RepertoryService, object())),
        tenant_id="escritorio-a",
    )
    result = await agent.draft(_request(), _context())
    assert result.is_grounded is False
    assert "src-peca" in result.grounding_report.failed_citation_ids
