"""Reviewer agent — orchestrates 5-dimension petition analysis."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from juris.core.observability import get_logger
from juris.llm.base import AbstractLLM
from juris.persistence.audit import AuditLog
from juris.repertory.retrieval.service import RepertoryService, RetrievalResult
from juris.review.citation_verifier import RawCitationVerifier
from juris.review.extractor import extract_citations
from juris.review.models import (
    CitationRef,
    IssueSeverity,
    ReviewDimension,
    ReviewIssue,
    ReviewReport,
    ReviewRequest,
)
from juris.review.prompts import (
    DIMENSION_PROMPTS,
    PROMPT_VERSION,
    REVIEW_SCHEMA,
    SYSTEM_PROMPT,
)

logger = get_logger(__name__)

# Dimensions that need retrieval context (structure is purely stylistic)
_RETRIEVAL_DIMENSIONS = {
    ReviewDimension.COMPLETENESS,
    ReviewDimension.AUTHORITY,
    ReviewDimension.COUNTERARGUMENTS,
    ReviewDimension.COMPLIANCE,
}

# Retrieval query builders per dimension
_RETRIEVAL_QUERIES: dict[ReviewDimension, str] = {
    ReviewDimension.COMPLETENESS: "teses juridicas argumentos fundamentacao",
    ReviewDimension.AUTHORITY: "sumula vinculante precedente jurisprudencia",
    ReviewDimension.COUNTERARGUMENTS: "contra-argumento tese contraria improcedencia",
    ReviewDimension.COMPLIANCE: "litigancia ma-fe CPC artigo 78 79 80 81",
}

_PROOF_MARKERS = re.compile(
    r"\b(prova|documento|doc\.|anexo|contrato|comprovante|recibo|nota fiscal|id\.|evento\s+\d+)\b",
    re.IGNORECASE,
)
_LEGAL_BASIS_MARKERS = re.compile(
    r"(\bart\.|\b(?:artigo|cpc|cc|clt|lei|constitui|fundamento|nos termos|com base|"
    r"s[uú]mula|tema|resp|are?s?p?)\b)",
    re.IGNORECASE,
)
_EXCESSIVE_THESIS = re.compile(
    r"\b(êxito garantido|vit[oó]ria garantida|proced[eê]ncia certa|sem risco algum|risco zero|"
    r"inevit[aá]vel|indiscutivelmente|manifestamente procedente)\b",
    re.IGNORECASE,
)
_GENERIC_JURIS = re.compile(
    r"\b(jurisprud[eê]ncia pac[ií]fica|entendimento dominante|os tribunais entendem|"
    r"conforme a jurisprud[eê]ncia|precedentes s[aã]o un[aâ]nimes)\b",
    re.IGNORECASE,
)
_CLAIM_WITHOUT_PROOF = re.compile(
    r"\b(alega(?:-se)?|afirma(?:-se)?|sustenta(?:-se)?|houve|ocorreu|descumpriu|causou)\b",
    re.IGNORECASE,
)


class ReviewerAgent:
    """Orchestrates 5-dimension petition review with LLM + retrieval."""

    def __init__(
        self,
        llm: AbstractLLM,
        retriever: RepertoryService,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._verifier = RawCitationVerifier(retriever)
        self._audit = audit_log

    async def review(
        self,
        request: ReviewRequest,
        dimensions: list[ReviewDimension] | None = None,
    ) -> ReviewReport:
        """Run petition review across specified dimensions.

        Args:
            request: The petition text and metadata.
            dimensions: Dimensions to analyze. Defaults to all 5.

        Returns:
            ReviewReport with issues, citations, and audit metadata.
        """
        start = time.monotonic()
        dims = dimensions or list(ReviewDimension)

        report = ReviewReport(
            request=request,
            model_used=self._llm.model_name,
            prompt_version=PROMPT_VERSION,
        )

        # 1. Extract and verify citations
        raw_citations = extract_citations(request.petition_text)
        report.citations_found = self._verify_citations(raw_citations)
        report.retrieval_calls += 1
        report.issues.extend(deterministic_legal_issues(request, report.citations_found))

        # 2. Analyze each dimension
        for dim in dims:
            try:
                issues = await self._analyze_dimension(dim, request)
                report.issues.extend(issues)
                report.dimensions_analyzed.append(dim)
                report.llm_calls += 1
                if dim in _RETRIEVAL_DIMENSIONS:
                    report.retrieval_calls += 1
            except Exception:
                logger.exception("dimension_analysis_failed", dimension=dim.value)

        # 3. Sort issues: critical first, then important, then suggestion
        severity_order = {
            IssueSeverity.CRITICAL: 0,
            IssueSeverity.IMPORTANT: 1,
            IssueSeverity.SUGGESTION: 2,
        }
        report.issues.sort(key=lambda i: severity_order.get(i.severity, 9))

        report.duration_seconds = time.monotonic() - start

        # 4. Audit log
        self._log_audit(report)

        return report

    async def _analyze_dimension(
        self,
        dimension: ReviewDimension,
        request: ReviewRequest,
    ) -> list[ReviewIssue]:
        """Analyze a single dimension with retrieval + LLM."""
        # Retrieve context if needed
        context_text = ""
        if dimension in _RETRIEVAL_DIMENSIONS:
            query = _RETRIEVAL_QUERIES[dimension]
            # Augment query with petition content keywords
            petition_snippet = request.petition_text[:200]
            full_query = f"{query} {petition_snippet}"
            sources = self._retrieve_context(full_query)
            context_text = self._format_context(sources)

        # Build prompt
        prompt_template = DIMENSION_PROMPTS[dimension.value]
        if "{context}" in prompt_template:
            prompt = prompt_template.format(
                context=context_text or "Nenhum contexto disponivel.",
                petition_text=request.petition_text,
            )
        else:
            prompt = prompt_template.format(petition_text=request.petition_text)

        # Call LLM
        response = await self._llm.complete(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            schema=REVIEW_SCHEMA,
            max_tokens=2048,
            temperature=0.1,
        )

        # Parse response into ReviewIssue objects
        return self._parse_issues(response.content, dimension)

    def _verify_citations(self, raw_citations: list[str]) -> list[CitationRef]:
        """Verify extracted citations against repertory."""
        if not raw_citations:
            return []
        return self._verifier.verify_citations(raw_citations)

    def _retrieve_context(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        """Retrieve relevant jurisprudence from the repertory."""
        try:
            return self._retriever.search_jurisprudencia(query=query, top_k=top_k)
        except Exception:
            logger.warning("retrieval_failed", query=query[:50])
            return []

    @staticmethod
    def _format_context(sources: list[RetrievalResult]) -> str:
        """Format retrieval results as text context for the LLM prompt."""
        if not sources:
            return ""
        parts = []
        for i, src in enumerate(sources, 1):
            base = f" (Base: {', '.join(src.base_legal)})" if src.base_legal else ""
            parts.append(
                f"[{i}] {src.hierarchy_label} — {src.tribunal}\n"
                f"    {src.texto[:300]}{base}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _parse_issues(
        content: str,
        dimension: ReviewDimension,
    ) -> list[ReviewIssue]:
        """Parse LLM JSON response into ReviewIssue objects."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("llm_response_not_json", dimension=dimension.value)
            return []

        raw_issues: list[dict[str, Any]] = data.get("issues", [])
        issues: list[ReviewIssue] = []

        for raw in raw_issues:
            try:
                severity = IssueSeverity(raw["severity"])
            except (ValueError, KeyError):
                severity = IssueSeverity.SUGGESTION

            issues.append(ReviewIssue(
                dimension=dimension,
                severity=severity,
                title=raw.get("title", "Sem titulo"),
                description=raw.get("description", ""),
                line_anchor=raw.get("line_anchor"),
                suggestion=raw.get("suggestion"),
                citations=raw.get("citations", []),
            ))

        return issues

    def _log_audit(self, report: ReviewReport) -> None:
        """Log review to the audit trail."""
        if not self._audit:
            return
        self._audit.log(
            event_type="review",
            actor=f"llm:{report.model_used}",
            processo_cnj=report.request.numero_cnj,
            details={
                "dimensions": [d.value for d in report.dimensions_analyzed],
                "issues_count": len(report.issues),
                "critical_count": report.critical_count,
                "important_count": report.important_count,
                "citations_count": len(report.citations_found),
                "llm_calls": report.llm_calls,
                "retrieval_calls": report.retrieval_calls,
                "duration_seconds": report.duration_seconds,
                "prompt_version": report.prompt_version,
            },
        )


def deterministic_legal_issues(
    request: ReviewRequest,
    citations_found: list[CitationRef],
) -> list[ReviewIssue]:
    """High-precision legal guardrails independent from the LLM.

    These checks intentionally target patterns that are dangerous in drafts and
    cheap to verify deterministically. They do not replace the LLM review; they
    guarantee that obvious evidentiary and filing-quality risks are surfaced.
    """
    text = request.petition_text
    issues: list[ReviewIssue] = []

    proof_gap = _first_claim_without_proof(text)
    if proof_gap:
        issues.append(
            ReviewIssue(
                dimension=ReviewDimension.COMPLETENESS,
                severity=IssueSeverity.IMPORTANT,
                title="Alegação sem prova indicada",
                description=(
                    "Há alegação factual relevante sem referência próxima a documento, "
                    "evento, anexo ou outro lastro probatório."
                ),
                line_anchor=proof_gap,
                suggestion="Indique a prova correspondente ou marque a tese como lacuna antes de usar na minuta.",
            )
        )

    request_gap = _unfounded_request_anchor(text)
    if request_gap:
        issues.append(
            ReviewIssue(
                dimension=ReviewDimension.COMPLETENESS,
                severity=IssueSeverity.IMPORTANT,
                title="Pedido sem fundamento explícito",
                description=(
                    "A seção de pedidos contém requerimento sem base legal, contratual "
                    "ou jurisprudencial explícita no próprio bloco."
                ),
                line_anchor=request_gap,
                suggestion="Vincule o pedido ao fundamento normativo/probatório que o sustenta.",
            )
        )

    weak_juris_anchor = _weak_jurisprudence_anchor(text, citations_found)
    if weak_juris_anchor:
        issues.append(
            ReviewIssue(
                dimension=ReviewDimension.AUTHORITY,
                severity=IssueSeverity.IMPORTANT,
                title="Jurisprudência fraca ou genérica",
                description=(
                    "O texto usa autoridade jurisprudencial sem fonte verificável ou "
                    "com citação não localizada no repertório."
                ),
                line_anchor=weak_juris_anchor,
                suggestion="Substitua por precedente verificado, súmula, tema ou remova a afirmação genérica.",
            )
        )

    excess_anchor = _excessive_thesis_anchor(text)
    if excess_anchor:
        issues.append(
            ReviewIssue(
                dimension=ReviewDimension.COUNTERARGUMENTS,
                severity=IssueSeverity.IMPORTANT,
                title="Risco de tese excessiva",
                description=(
                    "A redação usa linguagem absoluta ou garante resultado, o que aumenta "
                    "risco de vulnerabilidade estratégica e desconformidade ética."
                ),
                line_anchor=excess_anchor,
                suggestion="Troque por tom proporcional à confiança: forte, cauteloso ou rascunho.",
            )
        )

    return issues


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _first_claim_without_proof(text: str) -> str | None:
    for paragraph in _paragraphs(text):
        if _CLAIM_WITHOUT_PROOF.search(paragraph) and not _PROOF_MARKERS.search(paragraph):
            return paragraph[:280]
    return None


def _unfounded_request_anchor(text: str) -> str | None:
    for paragraph in _paragraphs(text):
        lower = paragraph.lower()
        if "requer" not in lower:
            continue
        if _LEGAL_BASIS_MARKERS.search(paragraph):
            continue
        if _PROOF_MARKERS.search(paragraph):
            continue
        return paragraph[:280]
    return None


def _weak_jurisprudence_anchor(text: str, citations_found: list[CitationRef]) -> str | None:
    generic = _GENERIC_JURIS.search(text)
    unverified = next((c for c in citations_found if not c.found_in_repertory), None)
    if unverified is not None:
        return unverified.raw_text
    if generic:
        start = max(generic.start() - 80, 0)
        end = min(generic.end() + 120, len(text))
        return text[start:end].strip()
    return None


def _excessive_thesis_anchor(text: str) -> str | None:
    match = _EXCESSIVE_THESIS.search(text)
    if not match:
        return None
    start = max(match.start() - 80, 0)
    end = min(match.end() + 120, len(text))
    return text[start:end].strip()
