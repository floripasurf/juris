"""Grounding safety tests for LLM-generated drafts."""

from __future__ import annotations

from typing import Any, cast

import pytest

from juris.agents.citation_verifier import (
    MarkerCitationVerifier,
    build_grounding_report,
)
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
        temperature: float = 0.0,
    ) -> LLMResponse:
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


def _agent(llm_content: str) -> DrafterAgent:
    repertory = cast(RepertoryService, object())
    return DrafterAgent(
        llm=FakeLLM(llm_content),
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


def test_marker_verifier_blocks_unknown_source_id() -> None:
    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))

    result = verifier.verify("Argumento [CITE:inventado].", {"src-1"})
    report = build_grounding_report(result)

    assert result.all_passed is False
    assert report.is_verified is False
    assert report.failed_citation_ids == ["inventado"]
    assert report.reason == "citacoes_invalidas"


def test_marker_verifier_blocks_raw_jurisprudence_without_marker() -> None:
    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))

    result = verifier.verify("Conforme REsp 123456, a tese procede.", {"src-1"})
    report = build_grounding_report(result)

    assert result.all_passed is False
    assert report.is_verified is False
    assert report.spurious_citations == ["REsp 123456"]
    assert report.reason == "citacoes_sem_marcador"


@pytest.mark.asyncio
async def test_drafter_blocks_ungrounded_llm_prose() -> None:
    agent = _agent(
        "# Petição\n\nConforme REsp 123456, o pedido deve ser julgado improcedente."
    )

    result = await agent.draft(_request(), _context())

    assert result.is_grounded is False
    assert result.blocked_reason == "citacoes_sem_marcador"
    assert result.grounding_report.spurious_citations == ["REsp 123456"]
    assert "Minuta bloqueada" in result.draft_markdown
    assert "pedido deve ser julgado improcedente" not in result.draft_markdown


@pytest.mark.asyncio
async def test_drafter_allows_verified_marker_and_resolves_label() -> None:
    agent = _agent("# Petição\n\n## Direito\nArgumento verificado [CITE:src-1].")

    result = await agent.draft(_request(), _context())

    assert result.is_grounded is True
    assert result.blocked_reason is None
    assert result.grounding_report.verified_citation_ids == ["src-1"]
    assert "[STJ precedente — STJ (src-1)]" in result.draft_markdown


import pytest as _pytest  # noqa: E402


@_pytest.mark.parametrize(
    "text",
    [
        "REsp 123456",
        "REsp n. 1.234.567/SP",
        "REsp nº 1.234.567/SP",
        "REsp n° 1.234.567",
        "AREsp 1.234.567/SP",
        "AgInt no REsp 1.234.567/SP",
        "AgRg 1.234.567",
        "Tema Repetitivo 123",
        "Tema 123",
        "Súmula 7",
        "Súmula Vinculante 12",
        "IRDR 5",
        "IAC 3",
    ],
)
def test_spurious_detection_catches_real_jurisprudence_formats(text) -> None:
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    result = verifier.verify(f"A tese procede, conforme {text}.", {"src-1"})
    assert result.spurious_citations, f"não detectou jurisprudência crua: {text!r}"


@_pytest.mark.parametrize(
    "text",
    ["A responsabilidade civil é objetiva.", "O contrato é nulo.", "Houve dano moral."],
)
def test_spurious_detection_no_false_positive_on_plain_prose(text) -> None:
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    result = verifier.verify(text, {"src-1"})
    assert result.spurious_citations == []


@_pytest.mark.parametrize(
    "text",
    ["are 123", "MS 365", "HC 12", "O MS 365 da empresa", "AI 9 do plano"],
)
def test_spurious_no_false_positive_on_ambiguous_short_siglas(text) -> None:
    # short siglas (RE/HC/MS/AI) collide with plain words / product names — must not
    # block a valid draft unless the number is qualified (dotted, /UF, n., or long)
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    assert verifier.verify(text, {"src-1"}).spurious_citations == []


@_pytest.mark.parametrize(
    "text",
    ["RE 1.234.567/SP", "HC 123.456", "MS 12.345/DF", "RE 123456", "ARE 1.234.567"],
)
def test_spurious_still_catches_qualified_ambiguous_siglas(text) -> None:
    # the SAME siglas, with a real qualified number, must still be blocked
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    assert verifier.verify(f"conforme {text}", {"src-1"}).spurious_citations, text
