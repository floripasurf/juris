"""Grounding safety tests for LLM-generated drafts."""

from __future__ import annotations

from typing import Any, cast

import pytest

from juris.agents.citation_verifier import MarkerCitationVerifier, build_grounding_report
from juris.agents.drafter import DrafterAgent, DraftRequest
from juris.agents.researcher import Researcher, ResearchQuery, ResearchResult
from juris.defesas.context import ProcessoContext
from juris.llm.base import AbstractLLM, LLMResponse
from juris.repertory.peticoes.models import TipoPeticao
from juris.repertory.retrieval.service import RepertoryService, RetrievalResult
from juris.review.models import IssueSeverity, ReviewDimension, ReviewIssue, ReviewReport, ReviewRequest


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


class SequenceLLM(AbstractLLM):
    def __init__(self, contents: list[str]) -> None:
        self._contents = contents
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-sequence-llm"

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.prompts.append(prompt)
        content = self._contents[min(len(self.prompts) - 1, len(self._contents) - 1)]
        return LLMResponse(content=content, model=self.model_name)


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


def _request_with_revisions(rounds: int) -> DraftRequest:
    return DraftRequest(
        numero_cnj="0001234-56.2026.8.13.0001",
        tribunal="tjmg",
        tipo_peticao=TipoPeticao.CONTESTACAO,
        thesis="Inexistência de inadimplemento.",
        max_revision_rounds=rounds,
    )


def _context() -> ProcessoContext:
    return ProcessoContext(
        numero_cnj="0001234-56.2026.8.13.0001",
        tribunal="tjmg",
        classe="Ação de cobrança",
    )


class _CriticalReviewer:
    async def review(self, request: ReviewRequest) -> ReviewReport:
        return ReviewReport(
            request=request,
            issues=[
                ReviewIssue(
                    dimension=ReviewDimension.COMPLIANCE,
                    severity=IssueSeverity.CRITICAL,
                    title="Risco de tese excessiva",
                    description="Afirma êxito garantido.",
                )
            ],
            model_used="deterministic",
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


def test_marker_verifier_blocks_lowercase_qualified_ambiguous_case_ref() -> None:
    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))

    result = verifier.verify("Conforme ms 987.654.321/sp, a tese procede.", {"src-1"})

    assert "ms 987.654.321/sp" in result.spurious_citations


def test_marker_verifier_blocks_claim_that_distorts_allowed_source_text() -> None:
    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))

    result = verifier.verify(
        "O STJ decidiu que a multa moratória é válida [CITE:src-1].",
        allowed_source_ids={"src-1"},
        allowed_source_texts={
            "src-1": "O acórdão trata de honorários sucumbenciais e prescrição intercorrente."
        },
    )

    assert result.all_passed is False
    assert result.failed[0].source_id == "src-1"
    assert result.failed[0].failure_reason == "citation_claim_mismatch"
    assert build_grounding_report(result).reason == "citacoes_distorcidas"


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
async def test_drafter_blocks_reviewer_critical_when_no_revision_remains() -> None:
    repertory = cast(RepertoryService, object())
    agent = DrafterAgent(
        llm=FakeLLM("Minuta com [CITE:src-1]."),
        repertory=repertory,
        researcher=cast(Researcher, FakeResearcher()),
        verifier=MarkerCitationVerifier(repertory),
        reviewer=_CriticalReviewer(),
    )

    result = await agent.draft(_request(), _context())

    assert result.is_grounded is False
    assert result.blocked_reason == "reviewer_critical_issues"
    assert "Minuta bloqueada pelo revisor" in result.draft_markdown


@pytest.mark.asyncio
async def test_drafter_reprompts_on_reviewer_critical_issue() -> None:
    llm = SequenceLLM([
        "A procedência é certa. Minuta com [CITE:src-1].",
        "Minuta corrigida com [CITE:src-1].",
    ])

    class _Reviewer:
        async def review(self, request: ReviewRequest) -> ReviewReport:
            issues = []
            if "procedência é certa" in request.petition_text:
                issues.append(
                    ReviewIssue(
                        dimension=ReviewDimension.COMPLIANCE,
                        severity=IssueSeverity.CRITICAL,
                        title="Risco de tese excessiva",
                        description="Afirma resultado certo.",
                    )
                )
            return ReviewReport(request=request, issues=issues, model_used="deterministic")

    repertory = cast(RepertoryService, object())
    agent = DrafterAgent(
        llm=llm,
        repertory=repertory,
        researcher=cast(Researcher, FakeResearcher()),
        verifier=MarkerCitationVerifier(repertory),
        reviewer=_Reviewer(),
    )

    result = await agent.draft(_request_with_revisions(1), _context())

    assert result.is_grounded is True
    assert result.revisions == 1
    assert "PROBLEMAS CRITICOS DO REVISOR" in llm.prompts[-1]
    assert "Minuta corrigida" in result.draft_markdown


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


def test_no_proximity_bypass_fake_case_next_to_real_marker() -> None:
    # a fabricated case number sitting within 50 chars of a real [CITE:] marker was
    # wrongly treated as "inside the marker" and skipped — it must still be flagged
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    result = verifier.verify("Conforme [CITE:src-1], o REsp 9.999.999 também confirma.", {"src-1"})
    assert "REsp 9.999.999" in result.spurious_citations


def test_no_doctrine_lead_in_bypass_for_case_ref() -> None:
    # "conforme lecina/ensina/destaca" must not shield a fabricated CASE reference
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    result = verifier.verify("Conforme leciona o Ministro, o REsp 9.999.999 firmou a tese.", {"src-1"})
    assert result.spurious_citations != []


@_pytest.mark.parametrize(
    "text",
    [
        "RR-1000-12.2020.5.03.0001",           # TST recurso de revista (CNJ-hyphen)
        "RO 0001234-56.2020.5.09.0001",        # recurso ordinário trabalhista
        "AIRR-100-45.2019.5.02.0011",          # agravo de instrumento em RR
        "Apelação Cível 1234567-89.2020.8.26.0100",  # CNJ cited as precedent
        "Agravo de Instrumento 2233445-66.2021.8.13.0024",
        "Recurso Especial nº 1.234.567/SP",
        "Recurso Extraordinário n. 987654",
        "Agravo em Recurso Especial nº 2.345.678/RJ",
        "Habeas Corpus nº 123.456/SP",
        "Mandado de Segurança nº 12.345/DF",
        "Tese 987",
        "Precedente 12",
        "Enunciado 5",
        "Orientação Jurisprudencial 415",
    ],
)
def test_spurious_catches_tst_labor_and_cnj_formats(text) -> None:
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    assert verifier.verify(f"A tese procede, conforme {text}.", {"src-1"}).spurious_citations, text


@_pytest.mark.parametrize(
    "text",
    [
        "Trata-se de ação distribuída sob o Processo nº 1234567-89.2020.8.26.0100.",  # own case CNJ
        "A parte interpôs recurso especial, mas o preparo não foi recolhido.",  # generic remedy, no precedent number
        "A parte requer a produção de provas.",
    ],
)
def test_spurious_no_false_positive_on_own_case_number(text) -> None:
    # the petition's OWN process number (no recurso/court precedent prefix) is not a citation
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    assert verifier.verify(text, {"src-1"}).spurious_citations == []


# --- adversarial: false negatives + grounded-name over-block ---


@_pytest.mark.parametrize("text", ["Acórdão 1234567", "REsp123456", "OJ 415", "Ac. 987654"])
def test_spurious_catches_previously_missed_formats(text) -> None:
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    assert verifier.verify(f"conforme {text}, a tese procede", {"src-1"}).spurious_citations, text


def test_grounded_name_followed_by_its_marker_is_not_blocked() -> None:
    # "A Súmula 297 do STJ [CITE:src-1]" — the readable name is backed by the FOLLOWING
    # marker; it must NOT be flagged (this over-block killed the natural grounded path).
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    result = verifier.verify("A Súmula 297 do STJ [CITE:src-1] aplica-se ao caso.", {"src-1"})
    assert result.spurious_citations == []


def test_own_case_reclamacao_or_ms_caption_not_blocked() -> None:
    # the petition's OWN action being a Reclamação/MS must not trip the gate
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    assert verifier.verify(
        "Trata-se de Reclamação nº 0001234-56.2024.5.03.0001 ajuizada pela parte.", {"src-1"}
    ).spurious_citations == []


def test_proximity_evasion_still_caught_marker_before_fake() -> None:
    # regression: a fake AFTER a marker (marker does NOT follow the fake) stays flagged
    from juris.repertory.retrieval.service import RepertoryService

    verifier = MarkerCitationVerifier(cast(RepertoryService, object()))
    assert "REsp 9.999.999" in verifier.verify(
        "Conforme [CITE:src-1], o REsp 9.999.999 também confirma.", {"src-1"}
    ).spurious_citations
