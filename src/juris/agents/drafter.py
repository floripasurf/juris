"""Drafter agent — produces grounded, citation-verified petition drafts."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from juris.agents.citation_verifier import (
    CitationCheck,
    MarkerCitationVerifier,
    VerificationResult,
)
from juris.agents.estrategia import EstrategiaAgent, EstrategiaResult
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
from juris.review.models import ReviewReport

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DraftRequest:
    """Request for a petition draft."""

    numero_cnj: str
    tribunal: str
    tipo_peticao: TipoPeticao
    thesis: str | None = None
    custom_instructions: str = ""
    use_cloud_llm: bool = False
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
    ) -> None:
        self._llm = llm
        self._repertory = repertory
        self._researcher = researcher
        self._verifier = verifier
        self._reviewer = reviewer
        self._audit = audit
        self._defesa_analyzer = defesa_analyzer
        self._estrategia = estrategia

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
        if self._defesa_analyzer and request.tipo_peticao in (
            TipoPeticao.CONTESTACAO,
            TipoPeticao.CONTRARRAZOES,
        ):
            try:
                defesa_report = await self._defesa_analyzer.analyze(context)
                defesa_text = f"## ANALISE DE DEFESAS\n{defesa_report.summary}\n\n"
            except Exception:
                logger.warning(
                    "defesa_analysis_failed", numero_cnj=request.numero_cnj
                )

        # Step 3: Determine thesis
        thesis = request.thesis or await self._infer_thesis(request, context)
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
                    },
                    result,
                )
            except Exception:
                logger.warning("estrategia_failed", numero_cnj=request.numero_cnj)

        # Step 5: Style retrieval (from petition templates if available)
        style_text = ""
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
        except Exception:
            logger.debug("style_retrieval_skipped")

        # Step 5b: Template scaffold from corpus (MODELO_PETICAO)
        if not style_text:
            try:
                template_result = self._repertory.find_template(
                    tipo_peticao=request.tipo_peticao.value,
                    area_direito=context.ramo_justica,
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
            except Exception:
                logger.debug("template_scaffold_skipped")

        # Step 6+7: Generate and verify (with revision loop)
        allowed_ids = {r.source_id for r in research.supporting + research.opposing}
        draft_text = ""
        verification: VerificationResult | None = None
        revision_feedback = ""

        for revision in range(request.max_revision_rounds + 1):
            # Generate
            draft_text = await self._generate(
                request=request,
                case_context=case_ctx,
                thesis=thesis,
                research=research,
                defesa_text=defesa_text,
                style_text=style_text,
                revision_feedback=revision_feedback,
            )

            # Verify citations
            verification = self._verifier.verify(
                draft_text, allowed_source_ids=allowed_ids
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
                    ids = [c.source_id for c in verification.failed]
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

        # Step 8: Pre-show review (optional)
        if self._reviewer and verification and verification.all_passed:
            try:
                from juris.review.models import ReviewRequest

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

                # Re-prompt on critical issues (if revisions remain)
                if (
                    report.critical_count > 0
                    and result.revisions < request.max_revision_rounds
                ):
                    result.revisions += 1
                    critical_issues = [
                        i
                        for i in report.issues
                        if i.severity.value == "critical"
                    ]
                    feedback_parts = [
                        f"- {issue.title}: {issue.description}"
                        for issue in critical_issues[:3]
                    ]
                    revision_feedback = (
                        "## PROBLEMAS CRITICOS DO REVISOR\n"
                        + "\n".join(feedback_parts)
                        + "\n\n"
                    )
                    draft_text = await self._generate(
                        request=request,
                        case_context=case_ctx,
                        thesis=thesis,
                        research=research,
                        defesa_text=defesa_text,
                        style_text=style_text,
                        revision_feedback=revision_feedback,
                    )
            except Exception:
                logger.warning(
                    "review_after_draft_failed", numero_cnj=request.numero_cnj
                )

        # Step 9: Compose result
        result.draft_markdown = self._resolve_cite_markers(draft_text, research)
        result.contraponto_section = self._build_contraponto(research)
        result.citations_used = verification.checks if verification else []
        result.total_duration_seconds = time.monotonic() - start

        self._log_audit(
            "draft.completed",
            request.numero_cnj,
            {
                "revisions": result.revisions,
                "citations_count": len(result.citations_used),
                "duration_seconds": result.total_duration_seconds,
                "prompt_version": PROMPT_VERSION,
            },
            result,
        )

        return result

    async def _generate(
        self,
        request: DraftRequest,
        case_context: dict[str, Any],
        thesis: str,
        research: ResearchResult,
        defesa_text: str,
        style_text: str,
        revision_feedback: str,
    ) -> str:
        """Generate a draft via LLM call."""
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
            tipo_peticao=request.tipo_peticao.value,
        )

        response = await self._llm.complete(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.15,
        )
        return response.content

    async def _infer_thesis(
        self,
        request: DraftRequest,
        context: ProcessoContext,
    ) -> str:
        """Infer thesis via small LLM call when not explicitly provided."""
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
            )
            return response.content.strip()
        except Exception:
            logger.warning("thesis_inference_failed")
            return f"Defesa em {request.tipo_peticao.value}"

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
