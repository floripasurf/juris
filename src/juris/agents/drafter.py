"""Drafter agent — produces grounded, citation-verified petition drafts."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from juris.agents.citation_verifier import (
    CitationCheck,
    GroundingReport,
    GroundingStatus,
    MarkerCitationVerifier,
    VerificationResult,
    build_grounding_report,
)
from juris.agents.estrategia import EstrategiaAgent, EstrategiaResult, tom_minuta
from juris.agents.researcher import Researcher, ResearchQuery, ResearchResult
from juris.core.observability import get_logger
from juris.defesas.context import ProcessoContext
from juris.llm.base import AbstractLLM
from juris.persistence.audit import AuditLog
from juris.prompts.drafter_v1 import (
    DRAFT_PROMPT,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    THESIS_INFERENCE_PROMPT,
    format_case_context,
    format_sources,
)
from juris.repertory.peticoes.models import TipoPeticao
from juris.repertory.retrieval.service import RepertoryService
from juris.review.models import IssueSeverity, ReviewIssue, ReviewReport, ReviewRequest

logger = get_logger(__name__)

# How firmly to write the minuta, keyed by the strategy's tom_minuta() output. The tone
# must never overstate: even "forte" argues with conviction, never guarantees an outcome
# (deontologia CED/EOAB). "não protocolar" produces a review-only draft.
_TONE_INSTRUCTIONS: dict[str, str] = {
    "forte": (
        "A tese é sólida: redija com firmeza e convicção, afirmando as conclusões "
        "com base nos precedentes verificados. Nunca prometa êxito garantido."
    ),
    "cauteloso": (
        "A tese tem solidez média: module o tom, prefira 'há elementos que indicam' "
        "a afirmações categóricas, e sinalize onde a fundamentação depende de prova."
    ),
    "rascunho": (
        "A tese é frágil: trate como rascunho preliminar, evite afirmações categóricas "
        "e aponte explicitamente as lacunas de fundamentação e prova a resolver."
    ),
    "não protocolar": (
        "NÃO PROTOCOLAR: esta minuta exige revisão humana obrigatória. Redija como "
        "rascunho de trabalho, marque de forma visível os pontos que precisam ser "
        "verificados por um advogado antes de qualquer uso, e não conclua com firmeza."
    ),
}


@dataclass(frozen=True, slots=True)
class DraftRequest:
    """Request for a petition draft."""

    numero_cnj: str
    tribunal: str
    tipo_peticao: TipoPeticao
    thesis: str | None = None
    custom_instructions: str = ""
    use_cloud_llm: bool = False
    contains_pii: bool = True
    max_revision_rounds: int = 1


@dataclass(slots=True)
class DraftResult:
    """Result of the drafting pipeline."""

    draft_markdown: str = ""
    contraponto_section: str = ""
    citations_used: list[CitationCheck] = field(default_factory=list)
    research_summary: str = ""
    reviewer_report: ReviewReport | None = None
    revisions: int = 0
    total_duration_seconds: float = 0.0
    audit_entry_ids: list[str] = field(default_factory=list)
    estrategia: EstrategiaResult | None = None
    grounding_report: GroundingReport = field(
        default_factory=GroundingReport.verified
    )
    blocked_reason: str | None = None
    # Modelo efetivo da geração da minuta FINAL (última geração vence) e da
    # inferência de tese — a resposta a "qual IA escreveu isto?" (spec 2026-07-05).
    ai_model: str | None = None
    ai_model_thesis: str | None = None

    @property
    def is_grounded(self) -> bool:
        """True when the draft text is safe to surface as LLM-authored prose."""
        return self.grounding_report.is_verified


class DrafterAgent:
    """Produces grounded, citation-verified petition drafts.

    Orchestrates a 9-step pipeline:
    1. Build case context
    2. Defense analysis (if contestacao/contrarrazoes)
    3. Determine thesis
    4. Research supporting/opposing jurisprudence
    5. Style retrieval (optional)
    6. First-pass generation
    7. Citation verification (+ re-prompt if needed)
    8. Pre-show review (+ re-prompt if critical)
    9. Compose final result
    """

    def __init__(
        self,
        llm: AbstractLLM,
        repertory: RepertoryService,
        researcher: Researcher,
        verifier: MarkerCitationVerifier,
        reviewer: Any | None = None,
        audit: AuditLog | None = None,
        defesa_analyzer: Any | None = None,
        estrategia: EstrategiaAgent | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self._llm = llm
        self._repertory = repertory
        self._researcher = researcher
        self._verifier = verifier
        self._reviewer = reviewer
        self._audit = audit
        self._defesa_analyzer = defesa_analyzer
        self._estrategia = estrategia
        self._tenant_id = tenant_id  # scope template lookup to this firm (+ public seed)

    async def draft(
        self,
        request: DraftRequest,
        context: ProcessoContext,
    ) -> DraftResult:
        """Execute the full drafting pipeline."""
        start = time.monotonic()
        result = DraftResult()

        # Step 1: Build case context
        case_ctx = self._build_case_context(context)
        self._log_audit(
            "draft.context_built",
            request.numero_cnj,
            {"context_keys": list(case_ctx.keys())},
            result,
        )

        # Step 2: Defense analysis (contestacao/contrarrazoes)
        defesa_text = ""
        analise_adversario: str | None = None
        if self._defesa_analyzer and request.tipo_peticao in (
            TipoPeticao.CONTESTACAO,
            TipoPeticao.CONTRARRAZOES,
        ):
            try:
                defesa_report = await self._defesa_analyzer.analyze(context)
                defesa_text = f"## ANALISE DE DEFESAS\n{defesa_report.summary}\n\n"
                analise_adversario = defesa_report.summary  # Módulo D — feed the strategy
            except Exception:  # noqa: BLE001
                logger.warning(
                    "defesa_analysis_failed", numero_cnj=request.numero_cnj
                )

        # Step 3: Determine thesis
        if request.thesis:
            thesis = request.thesis
        else:
            thesis, result.ai_model_thesis = await self._infer_thesis(request, context)
        self._log_audit(
            "draft.thesis_chosen",
            request.numero_cnj,
            {"thesis": thesis, "explicit": request.thesis is not None},
            result,
        )

        # Step 4: Research
        research = await self._researcher.research(
            ResearchQuery(thesis=thesis, case_context=case_ctx)
        )
        result.research_summary = research.coverage_note

        # Step 4.5: Strategy (ADR-0017 Stage 2) — pick the best-grounded
        # argumentative line from the retrieved precedents and let it drive the
        # draft. Only refines the thesis when one wasn't explicitly given.
        if self._estrategia and research.supporting:
            try:
                estrategia = await self._estrategia.propor(
                    contexto=f"{thesis}\n{case_ctx}",
                    precedentes=research.supporting,
                    analise_adversario=analise_adversario,
                )
                result.estrategia = estrategia
                if not request.thesis and estrategia.escolhida.tese:
                    thesis = estrategia.escolhida.tese
                self._log_audit(
                    "draft.estrategia_selected",
                    request.numero_cnj,
                    {
                        "tese": estrategia.escolhida.tese,
                        "score": estrategia.escolhida.score,
                        "ordem": estrategia.escolhida.ordem,
                        "confianca": estrategia.escolhida.confianca,
                        "alternativas": len(estrategia.alternativas),
                        "avisos_deontologicos": estrategia.avisos_deontologicos,
                        "revisao_humana_obrigatoria": estrategia.revisao_humana_obrigatoria,
                    },
                    result,
                )
                if estrategia.avisos_deontologicos:
                    logger.warning(
                        "estrategia_deontologia",
                        numero_cnj=request.numero_cnj,
                        avisos=estrategia.avisos_deontologicos,
                    )
            except Exception:  # noqa: BLE001
                logger.warning("estrategia_failed", numero_cnj=request.numero_cnj)

        # Step 5a-bis: exemplar de estilo do PRÓPRIO escritório (Biblioteca, L4).
        # Precede templates genéricos: a peça da própria firma ensina o estilo real.
        style_text = ""
        find_style_exemplar = getattr(self._repertory, "find_style_exemplar", None)
        if callable(find_style_exemplar):
            try:
                exemplar = find_style_exemplar(
                    tipo_peticao=request.tipo_peticao.value,
                    area_direito=context.ramo_justica,
                    tenant_id=self._tenant_id,
                )
            except Exception:  # noqa: BLE001 - estilo é enriquecimento, nunca derruba o draft
                logger.debug("style_exemplar_skipped")
                exemplar = None
            if exemplar is not None:
                style_text = (
                    "EXEMPLO DE ESTILO DO SEU ESCRITÓRIO (não citar como fonte):\n"
                    + exemplar.texto[:2500]
                )
                self._log_audit(
                    "draft.style_retrieved",
                    request.numero_cnj,
                    {
                        "origem": "escritorio",
                        "source_id": exemplar.source_id,
                        "tipo": exemplar.tipo,
                        "uso": exemplar.uso,
                    },
                    result,
                )

        # Step 5: Style retrieval (from petition templates if available)
        if not style_text:
            try:
                # Search for matching templates by tipo and ramo
                templates = getattr(self._repertory, '_templates', None)
                if templates and callable(getattr(templates, 'search', None)):
                    matched = templates.search(
                        tipo=request.tipo_peticao,
                        ramo_direito=context.ramo_justica,
                    )
                    if matched:
                        best = matched[0]
                        sections = [f"{s.ordem}. {s.titulo}: {s.proposito}" for s in best.estrutura]
                        style_text = (
                            f"Template: {best.titulo}\n"
                            f"Estrutura:\n" + "\n".join(sections)
                        )
                        self._log_audit("draft.style_retrieved", request.numero_cnj, {
                            "template_id": best.id,
                            "template_titulo": best.titulo,
                        }, result)
            except Exception:  # noqa: BLE001
                logger.debug("style_retrieval_skipped")

        # Step 5b: Template scaffold from corpus (MODELO_PETICAO)
        if not style_text:
            try:
                template_result = self._repertory.find_template(
                    tipo_peticao=request.tipo_peticao.value,
                    area_direito=context.ramo_justica,
                    tenant_id=self._tenant_id,
                )
                if template_result:
                    from juris.prompts.drafter_v1 import format_template_scaffold
                    # Extract section titles from template text
                    section_re = re.compile(
                        r"(?:D[OAE]S?\s+)?(?:FATOS?|DIREITO|PEDIDOS?|REQUERIMENTOS?|PRELIMINAR|MÉRITO|"
                        r"FUNDAMENTAÇÃO|CONCLUSÃO|PROVAS?|TUTELA|CAUSA DE PEDIR|"
                        r"VALOR DA CAUSA|ENDEREÇAMENTO|QUALIFICAÇÃO|COMPETÊNCIA)",
                        re.IGNORECASE,
                    )
                    sections = section_re.findall(template_result.texto)
                    if sections:
                        publisher = "TJDFT"  # default; could extract from source_id
                        style_text = format_template_scaffold(
                            source_publisher=publisher,
                            tipo_peticao=request.tipo_peticao.value,
                            section_titles=list(dict.fromkeys(sections)),  # dedupe preserving order
                        )
                        self._log_audit("draft.template_scaffold", request.numero_cnj, {
                            "template_source_id": template_result.source_id,
                        }, result)
            except Exception:  # noqa: BLE001
                logger.debug("template_scaffold_skipped")

        # Step 6+7: Generate and verify (with revision loop)
        allowed_ids = {r.source_id for r in research.supporting + research.opposing}
        allowed_source_texts = self._allowed_source_texts(research)
        draft_text = ""
        verification: VerificationResult | None = None
        revision_feedback = ""
        # Firmness the minuta should adopt, from the chosen strategy line — so the
        # drafted text matches the tone the console announces (forte/cauteloso/
        # rascunho/não protocolar), instead of the tone being a label-only afterthought.
        tone = (
            tom_minuta(
                result.estrategia.escolhida.confianca,
                revisao_obrigatoria=result.estrategia.revisao_humana_obrigatoria,
            )
            if result.estrategia
            else ""
        )

        for revision in range(request.max_revision_rounds + 1):
            # Generate
            draft_text, generation_model = await self._generate(
                request=request,
                case_context=case_ctx,
                thesis=thesis,
                research=research,
                defesa_text=defesa_text,
                style_text=style_text,
                revision_feedback=revision_feedback,
                tone=tone,
            )
            result.ai_model = generation_model

            # Verify citations
            verification = self._verifier.verify(
                draft_text,
                allowed_source_ids=allowed_ids,
                allowed_source_texts=allowed_source_texts,
            )
            self._log_audit(
                "draft.citations_verified",
                request.numero_cnj,
                {
                    "all_passed": verification.all_passed,
                    "total_checks": len(verification.checks),
                    "failed_count": len(verification.failed),
                    "spurious_count": len(verification.spurious_citations),
                    "revision": revision,
                },
                result,
            )

            if verification.all_passed:
                break

            # Build feedback for re-prompt
            if revision < request.max_revision_rounds:
                result.revisions += 1
                feedback_parts: list[str] = []
                if verification.failed:
                    ids = [f"{c.source_id} ({c.failure_reason or 'invalid'})" for c in verification.failed]
                    feedback_parts.append(
                        f"CITACOES INVALIDAS (remova ou substitua): {', '.join(ids)}"
                    )
                if verification.spurious_citations:
                    feedback_parts.append(
                        f"CITACOES SEM MARCADOR [CITE:] (adicione marcador ou remova): "
                        f"{', '.join(verification.spurious_citations)}"
                    )
                revision_feedback = (
                    "## CORRECOES NECESSARIAS\n"
                    + "\n".join(feedback_parts)
                    + "\n\n"
                )

        grounding_report = build_grounding_report(verification)
        result.grounding_report = grounding_report
        result.citations_used = verification.checks if verification else []

        if not grounding_report.is_verified:
            return self._block_ungrounded_result(
                result=result,
                request=request,
                research=research,
                report=grounding_report,
                start=start,
            )

        # Step 8: Pre-show review (optional)
        if self._reviewer and draft_text:
            try:
                review_req = ReviewRequest(
                    petition_text=draft_text,
                    petition_type=request.tipo_peticao.value,
                    numero_cnj=request.numero_cnj,
                    tribunal=request.tribunal,
                )
                report = await self._reviewer.review(review_req)
                result.reviewer_report = report
                self._log_audit(
                    "draft.reviewed",
                    request.numero_cnj,
                    {
                        "critical_count": report.critical_count,
                        "important_count": report.important_count,
                    },
                    result,
                )

                critical_issues = self._critical_reviewer_issues(report)
                if critical_issues and result.revisions < request.max_revision_rounds:
                    result.revisions += 1
                    feedback_parts = self._review_feedback_lines(critical_issues)
                    revision_feedback = (
                        "## PROBLEMAS CRITICOS DO REVISOR\n"
                        + "\n".join(feedback_parts)
                        + "\n\n"
                    )
                    draft_text, generation_model = await self._generate(
                        request=request,
                        case_context=case_ctx,
                        thesis=thesis,
                        research=research,
                        defesa_text=defesa_text,
                        style_text=style_text,
                        revision_feedback=revision_feedback,
                        tone=tone,
                    )
                    result.ai_model = generation_model
                    verification = self._verifier.verify(
                        draft_text,
                        allowed_source_ids=allowed_ids,
                        allowed_source_texts=allowed_source_texts,
                    )
                    result.grounding_report = build_grounding_report(verification)
                    result.citations_used = verification.checks
                    self._log_audit(
                        "draft.citations_verified",
                        request.numero_cnj,
                        {
                            "all_passed": verification.all_passed,
                            "total_checks": len(verification.checks),
                            "failed_count": len(verification.failed),
                            "spurious_count": len(verification.spurious_citations),
                            "revision": result.revisions,
                            "after_reviewer": True,
                        },
                        result,
                    )
                    if verification.all_passed:
                        review_req = ReviewRequest(
                            petition_text=draft_text,
                            petition_type=request.tipo_peticao.value,
                            numero_cnj=request.numero_cnj,
                            tribunal=request.tribunal,
                        )
                        report = await self._reviewer.review(review_req)
                        result.reviewer_report = report
                        self._log_audit(
                            "draft.reviewed",
                            request.numero_cnj,
                            {
                                "critical_count": report.critical_count,
                                "important_count": report.important_count,
                                "after_reviewer_revision": True,
                            },
                            result,
                        )
                        critical_issues = self._critical_reviewer_issues(report)
                if critical_issues:
                    return self._block_reviewer_result(
                        result=result,
                        request=request,
                        research=research,
                        issues=critical_issues,
                        start=start,
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "review_after_draft_failed", numero_cnj=request.numero_cnj
                )

        grounding_report = build_grounding_report(verification)
        result.grounding_report = grounding_report
        result.citations_used = verification.checks if verification else []
        if not grounding_report.is_verified:
            return self._block_ungrounded_result(
                result=result,
                request=request,
                research=research,
                report=grounding_report,
                start=start,
                after_reviewer=True,
            )

        # Step 9: Compose result
        result.draft_markdown = self._resolve_cite_markers(draft_text, research)
        result.contraponto_section = self._build_contraponto(research)
        result.total_duration_seconds = time.monotonic() - start

        self._log_audit(
            "draft.completed",
            request.numero_cnj,
            {
                "revisions": result.revisions,
                "citations_count": len(result.citations_used),
                "grounding_status": result.grounding_report.status.value,
                "duration_seconds": result.total_duration_seconds,
                "prompt_version": PROMPT_VERSION,
            },
            result,
        )

        return result

    @staticmethod
    def _allowed_source_texts(research: ResearchResult) -> dict[str, str]:
        return {r.source_id: r.texto for r in research.supporting + research.opposing if r.texto}

    @staticmethod
    def _critical_reviewer_issues(report: ReviewReport) -> list[ReviewIssue]:
        return [issue for issue in report.issues if issue.severity == IssueSeverity.CRITICAL]

    @staticmethod
    def _review_feedback_lines(issues: list[ReviewIssue]) -> list[str]:
        return [f"- {issue.title}: {issue.description}" for issue in issues[:5]]

    def _block_ungrounded_result(
        self,
        *,
        result: DraftResult,
        request: DraftRequest,
        research: ResearchResult,
        report: GroundingReport,
        start: float,
        after_reviewer: bool = False,
    ) -> DraftResult:
        result.draft_markdown = self._blocked_grounding_notice(report)
        result.contraponto_section = self._build_contraponto(research)
        result.blocked_reason = report.reason
        result.total_duration_seconds = time.monotonic() - start
        details: dict[str, Any] = {
            "reason": report.reason,
            "failed_citation_ids": report.failed_citation_ids,
            "spurious_citations": report.spurious_citations,
            "duration_seconds": result.total_duration_seconds,
            "prompt_version": PROMPT_VERSION,
        }
        if after_reviewer:
            details["after_reviewer"] = True
        self._log_audit(
            "draft.blocked_ungrounded",
            request.numero_cnj,
            details,
            result,
        )
        return result

    def _block_reviewer_result(
        self,
        *,
        result: DraftResult,
        request: DraftRequest,
        research: ResearchResult,
        issues: list[ReviewIssue],
        start: float,
    ) -> DraftResult:
        result.grounding_report = GroundingReport(
            status=GroundingStatus.BLOCKED,
            reason="reviewer_critical_issues",
        )
        result.draft_markdown = self._blocked_reviewer_notice(issues)
        result.contraponto_section = self._build_contraponto(research)
        result.blocked_reason = "reviewer_critical_issues"
        result.total_duration_seconds = time.monotonic() - start
        self._log_audit(
            "draft.blocked",
            request.numero_cnj,
            {
                "reason": "reviewer_critical_issues",
                "critical_count": len(issues),
                "critical_titles": [issue.title for issue in issues[:5]],
                "duration_seconds": result.total_duration_seconds,
                "prompt_version": PROMPT_VERSION,
            },
            result,
        )
        return result

    @staticmethod
    def _blocked_grounding_notice(report: GroundingReport) -> str:
        """Return a deterministic replacement when generated prose is unsafe."""

        lines = [
            "# Minuta bloqueada por falta de lastro verificável",
            "",
            "A saída da IA não foi liberada como minuta porque citou fonte ou "
            "jurisprudência sem verificação no corpus autorizado.",
            "",
            "## Pendências de verificação",
        ]
        if report.failed_citation_ids:
            lines.append("")
            lines.append("**Marcadores [CITE:] inválidos:**")
            lines.extend(f"- `{source_id}`" for source_id in report.failed_citation_ids)
        if report.spurious_citations:
            lines.append("")
            lines.append("**Referências jurisprudenciais sem marcador verificável:**")
            lines.extend(f"- {citation}" for citation in report.spurious_citations)
        if not report.failed_citation_ids and not report.spurious_citations:
            lines.append("")
            lines.append("- Verificação determinística não concluída.")
        lines.extend(
            [
                "",
                "## Próxima ação",
                "",
                "Refaça a pesquisa, substitua as referências por fontes presentes no "
                "corpus ou remova a citação antes de liberar a peça.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _blocked_reviewer_notice(issues: list[ReviewIssue]) -> str:
        lines = [
            "# Minuta bloqueada pelo revisor",
            "",
            "A minuta contém problema jurídico crítico identificado antes da liberação.",
            "Corrija os itens abaixo e gere uma nova versão antes de usar a peça.",
            "",
            "## Problemas críticos",
        ]
        for issue in issues[:5]:
            lines.append(f"- {issue.title}: {issue.description}")
        return "\n".join(lines)

    async def _generate(
        self,
        request: DraftRequest,
        case_context: dict[str, Any],
        thesis: str,
        research: ResearchResult,
        defesa_text: str,
        style_text: str,
        revision_feedback: str,
        tone: str = "",
    ) -> tuple[str, str]:
        """Generate a draft via LLM call; returns (markdown, effective model label)."""
        instruction = _TONE_INSTRUCTIONS.get(tone)
        tone_section = f"## TOM DA MINUTA ({tone})\n{instruction}\n\n" if instruction else ""
        prompt = DRAFT_PROMPT.format(
            case_context=format_case_context(case_context),
            defesa_section=defesa_text,
            thesis=thesis,
            supporting_sources=format_sources(research.supporting),
            opposing_sources=format_sources(research.opposing),
            style_section=f"## ESTILO\n{style_text}\n\n" if style_text else "",
            custom_instructions=(
                f"## INSTRUCOES ADICIONAIS\n{request.custom_instructions}\n\n"
                if request.custom_instructions
                else ""
            ),
            revision_feedback=revision_feedback,
            tone_section=tone_section,
            tipo_peticao=request.tipo_peticao.value,
        )

        response = await self._llm.complete(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.15,
            contains_pii=request.contains_pii,
        )
        return response.content, response.model

    async def _infer_thesis(
        self,
        request: DraftRequest,
        context: ProcessoContext,
    ) -> tuple[str, str | None]:
        """Infer thesis via small LLM call; returns (thesis, effective model or None)."""
        prompt = THESIS_INFERENCE_PROMPT.format(
            classe=context.classe,
            assuntos=", ".join(context.assuntos),
            tribunal=request.tribunal,
            tipo_peticao=request.tipo_peticao.value,
        )
        try:
            response = await self._llm.complete(
                prompt=prompt,
                temperature=0.1,
                max_tokens=256,
                contains_pii=request.contains_pii,
            )
            return response.content.strip(), response.model
        except Exception:  # noqa: BLE001
            logger.warning("thesis_inference_failed")
            return f"Defesa em {request.tipo_peticao.value}", None

    @staticmethod
    def _build_case_context(context: ProcessoContext) -> dict[str, Any]:
        """Convert ProcessoContext to a plain dict for prompt formatting."""
        return {
            "numero_cnj": context.numero_cnj,
            "tribunal": context.tribunal,
            "classe": context.classe,
            "ramo_justica": context.ramo_justica,
            "assuntos": context.assuntos,
            "valor_causa": context.valor_causa,
            "fase_atual": context.fase_atual,
        }

    @staticmethod
    def _resolve_cite_markers(
        draft: str,
        research: ResearchResult,
    ) -> str:
        """Replace [CITE:source_id] markers with readable labels."""
        source_map: dict[str, str] = {}
        for r in research.supporting + research.opposing:
            label = f"{r.hierarchy_label} — {r.tribunal} ({r.source_id})"
            source_map[r.source_id] = label

        def replacer(match: re.Match) -> str:  # type: ignore[type-arg]
            source_id = match.group(1)
            label = source_map.get(source_id, source_id)
            return f"[{label}]"

        return re.sub(r"\[CITE:([\w\-]+)\]", replacer, draft)

    @staticmethod
    def _build_contraponto(research: ResearchResult) -> str:
        """Build the CONTRAPONTO PREVISTO section from research results."""
        if not research.opposing:
            return ""

        lines: list[str] = ["## CONTRAPONTO PREVISTO"]
        lines.append("")
        lines.append("*Nota estrategica interna — NAO incluir na peticao.*")
        lines.append("")

        for r in research.opposing:
            strategic_note = (
                "**Acao recomendada:** antecipar e rebater no corpo da peticao"
                if r.hierarchy <= 4
                else "**Acao recomendada:** reservar para replica se levantado"
            )
            lines.append(
                f"- **{r.hierarchy_label} — {r.tribunal}** ({r.source_id})\n"
                f"  {r.texto[:120]}...\n"
                f"  {strategic_note}"
            )
            lines.append("")

        if research.has_strong_opposition:
            lines.append(
                "**ALERTA:** Oposicao forte encontrada (hierarquia <= 4). "
                "Considere antecipar os contrapontos acima no corpo da peticao."
            )

        return "\n".join(lines)

    def _log_audit(
        self,
        event_type: str,
        numero_cnj: str,
        details: dict[str, Any],
        result: DraftResult,
    ) -> None:
        """Log to audit trail and collect entry IDs."""
        if not self._audit:
            return
        entry = self._audit.log(
            event_type=event_type,
            actor=f"llm:{self._llm.model_name}",
            processo_cnj=numero_cnj,
            details=details,
        )
        result.audit_entry_ids.append(entry.entry_id)
