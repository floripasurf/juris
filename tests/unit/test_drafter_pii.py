"""PII propagation tests for the drafter LLM calls."""

from __future__ import annotations

from typing import Any

import pytest

from juris.agents.citation_verifier import VerificationResult
from juris.agents.drafter import DrafterAgent, DraftRequest
from juris.agents.researcher import ResearchResult
from juris.defesas.context import ProcessoContext
from juris.llm.base import AbstractLLM, LLMResponse
from juris.repertory.peticoes.models import TipoPeticao
from juris.review.models import ReviewReport, ReviewRequest


class RecordingLLM(AbstractLLM):
    """Records PII markers passed to completion calls."""

    def __init__(self) -> None:
        self.contains_pii_values: list[bool] = []

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
        self.contains_pii_values.append(contains_pii)
        return LLMResponse(content="texto gerado", model=self.model_name)

    @property
    def model_name(self) -> str:
        return "recording-llm"


class StaticResearcher:
    async def research(self, query: object) -> ResearchResult:
        return ResearchResult(thesis="tese ficticia")


class FailingVerifier:
    def verify(
        self,
        draft: str,
        allowed_source_ids: set[str] | None = None, **kwargs) -> VerificationResult:
        return VerificationResult(all_passed=False, spurious_citations=["REsp 123"])


class RecordingReviewer:
    def __init__(self) -> None:
        self.requests: list[ReviewRequest] = []

    async def review(self, request: ReviewRequest) -> ReviewReport:
        self.requests.append(request)
        return ReviewReport(request=request, model_used="reviewer", prompt_version="test")


@pytest.mark.asyncio
async def test_generate_marks_case_draft_prompt_as_pii() -> None:
    llm = RecordingLLM()
    agent = DrafterAgent(
        llm=llm,
        repertory=None,  # type: ignore[arg-type]
        researcher=None,  # type: ignore[arg-type]
        verifier=None,  # type: ignore[arg-type]
    )

    await agent._generate(
        request=DraftRequest(
            numero_cnj="0000001-02.2024.8.26.0100",
            tribunal="TJSP",
            tipo_peticao=TipoPeticao.CONTESTACAO,
        ),
        case_context={"numero_cnj": "0000001-02.2024.8.26.0100"},
        thesis="nulidade de citacao",
        research=ResearchResult(thesis="nulidade de citacao"),
        defesa_text="",
        style_text="",
        revision_feedback="",
    )

    assert llm.contains_pii_values == [True]


@pytest.mark.asyncio
async def test_generate_allows_explicit_non_pii_demo_prompt() -> None:
    llm = RecordingLLM()
    agent = DrafterAgent(
        llm=llm,
        repertory=None,  # type: ignore[arg-type]
        researcher=None,  # type: ignore[arg-type]
        verifier=None,  # type: ignore[arg-type]
    )

    await agent._generate(
        request=DraftRequest(
            numero_cnj="DEMO-0000000-00.0000.0.00.0000",
            tribunal="TJMG",
            tipo_peticao=TipoPeticao.CONTESTACAO,
            contains_pii=False,
        ),
        case_context={"numero_cnj": "DEMO-0000000-00.0000.0.00.0000"},
        thesis="tese ficticia",
        research=ResearchResult(thesis="tese ficticia"),
        defesa_text="",
        style_text="",
        revision_feedback="",
    )

    assert llm.contains_pii_values == [False]


@pytest.mark.asyncio
async def test_thesis_inference_marks_case_context_prompt_as_pii() -> None:
    llm = RecordingLLM()
    agent = DrafterAgent(
        llm=llm,
        repertory=None,  # type: ignore[arg-type]
        researcher=None,  # type: ignore[arg-type]
        verifier=None,  # type: ignore[arg-type]
    )

    await agent._infer_thesis(
        DraftRequest(
            numero_cnj="0000001-02.2024.8.26.0100",
            tribunal="TJSP",
            tipo_peticao=TipoPeticao.CONTESTACAO,
        ),
        ProcessoContext(
            numero_cnj="0000001-02.2024.8.26.0100",
            tribunal="TJSP",
            classe="Procedimento Comum Civel",
            assuntos=["Responsabilidade civil"],
        ),
    )

    assert llm.contains_pii_values == [True]


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="Reconciliacao sprint-15<->main: o pilot espera o reviewer rodando mesmo com "
    "citacao falha; o main (guardrails legais C1) gateia o reviewer atras do grounding e "
    "bloqueia draft nao-fundamentado. Decisao de produto pendente.",
    strict=False,
)
async def test_draft_runs_reviewer_even_when_citation_verification_fails() -> None:
    llm = RecordingLLM()
    reviewer = RecordingReviewer()
    agent = DrafterAgent(
        llm=llm,
        repertory=None,  # type: ignore[arg-type]
        researcher=StaticResearcher(),  # type: ignore[arg-type]
        verifier=FailingVerifier(),  # type: ignore[arg-type]
        reviewer=reviewer,
    )

    result = await agent.draft(
        DraftRequest(
            numero_cnj="DEMO-0000000-00.0000.0.00.0000",
            tribunal="TJMG",
            tipo_peticao=TipoPeticao.CONTESTACAO,
            thesis="tese ficticia",
            contains_pii=False,
            max_revision_rounds=0,
        ),
        ProcessoContext(
            numero_cnj="DEMO-0000000-00.0000.0.00.0000",
            tribunal="TJMG",
            classe="Procedimento Comum Civel",
        ),
    )

    assert result.reviewer_report is not None
    assert len(reviewer.requests) == 1
