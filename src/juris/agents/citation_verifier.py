"""Marker-based citation verifier for draft petitions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from juris.core.observability import get_logger
from juris.repertory.citation_lookup import resolve_source_id
from juris.repertory.retrieval.service import RepertoryService

logger = get_logger(__name__)

# Pattern for [CITE:source_id] markers
_CITE_PATTERN = re.compile(r"\[CITE:([\w\-]+)\]")

# Academic citation pattern for DOUTRINA_PD sources
_ACADEMIC_CITE_PATTERN = re.compile(
    r"[Cc]onforme (?:leciona|ensina|destaca|observa|aponta)\s+[\w\s]+,\s+"
    r"[\w\s]+,\s+\d{4}"
)

# Patterns for raw case references in prose (not anchored to [CITE:])
# Raw jurisprudence references not anchored to a [CITE:] marker. Two tiers to catch
# real Brazilian formats WITHOUT false-positiving on plain prose / product names:
#
# * STRONG siglas (REsp/AREsp/AgInt/AgRg/RHC/RMS/EDcl/ADI/ADC/ADPF/IRDR/IAC/AIRR) are
#   distinctive, so a bare number is a safe signal (case-insensitive).
# * AMBIGUOUS short siglas (RE/ARE/HC/MS/RR/AI/ADO) collide with common text — "MS 365",
#   "HC 12", "are 123". They match ONLY uppercase (case-sensitive) AND with a *qualified*
#   number: dotted (1.234.567), "/UF", an "n./nº" lead-in, or >= 5 digits.
_STRONG_SIGLAS = r"E?A?REsp|AgInt|AgRg|EDcl|EDv|RHC|RMS|ADI|ADC|ADPF|IRDR|IAC|AIRR"
_NUM_TAIL = r"(?:n[º°.]?\s*)?\d[\d.]*(?:\s*/\s*[A-Z]{2})?"
_AMBIGUOUS_SIGLAS = r"ARE|RE|HC|MS|RR|AI|ADO"
_QUALIFIED_NUM = (
    r"(?:n[º°.]\s*\d[\d.]*"  # n. 123 / nº 1.234
    r"|\d{1,3}(?:\.\d{3})+"  # dotted: 1.234.567
    r"|\d+\s*/\s*[A-Z]{2}"  # 12345/SP
    r"|\d{5,})"  # long bare number
    r"(?:\s*/\s*[A-Z]{2})?"  # optional trailing /UF
)
# CNJ unified process number (7-2.4.1.2.4; the first group is 1–7 digits in labor).
# Distinctive enough to anchor a citation WHEN prefixed by a recurso/court indicator —
# a *bare* CNJ (the petition's own process number) is deliberately NOT matched.
_CNJ_NUM = r"\d{1,7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}"
# TST/labor siglas — RR/RO/AIRR collide with prose, so they anchor ONLY on a CNJ tail.
_LABOR_SIGLAS = r"RRAg|RR|ROT|RO|AIRO|AIRR|AIRE|ED-RR|Ag-AIRR|ARR"
# Court/recurso indicators that turn a following CNJ number into a precedent citation.
# Only *appellate* types are here — Mandado de Segurança / Reclamação / Habeas Corpus /
# Conflito are just as often the petition's OWN action (its caption), so matching them
# on a bare CNJ over-blocked valid drafts. Cited precedents of those types carry a
# [CITE:] marker and are handled by the anchoring logic instead.
_RECURSO_PREFIX = (
    r"Apela[çc][ãa]o(?:\s+C[íi]vel)?|Agravo(?:\s+de\s+Instrumento|\s+Interno|\s+Regimental)?"
    r"|Recurso\s+\w+|Embargos(?:\s+\w+)?"
)
_FULL_RECURSO_PREFIX = (
    r"Recurso\s+(?:Especial|Extraordin[áa]rio|Ordin[áa]rio|em\s+Habeas\s+Corpus"
    r"|em\s+Mandado\s+de\s+Seguran[çc]a)"
    r"|Agravo\s+em\s+Recurso\s+(?:Especial|Extraordin[áa]rio)"
    r"|Habeas\s+Corpus|Mandado\s+de\s+Seguran[çc]a"
)
_RAW_CASE_PATTERNS = [
    # strong siglas, with an optional "AgInt/AgRg/AgR no/na" compound prefix.
    # No \b after the sigla — the number may abut it ("REsp123456", an LLM typo).
    re.compile(
        rf"\b(?:Ag(?:Int|Rg|R)\s+n[oa]\s+)?(?:{_STRONG_SIGLAS})\.?\s*{_NUM_TAIL}", re.IGNORECASE
    ),
    # Acórdão / Ac. + number (a core way to cite BR case law)
    re.compile(r"\b(?:Ac[óo]rd[ãa]o|Ac\.)\s*(?:n[º°.]?\s*)?\d[\d.]*", re.IGNORECASE),
    # OJ (Orientação Jurisprudencial, labor) — uppercase abbrev + number
    re.compile(r"\bOJ\s+(?:SDI-?[I\d]+\s+)?(?:n[º°.]?\s*)?\d+"),
    # ambiguous siglas: case-sensitive + a qualified number only (avoids "MS 365" etc.)
    re.compile(rf"\b(?:{_AMBIGUOUS_SIGLAS})\b\.?\s*{_QUALIFIED_NUM}"),
    # TST/labor siglas anchored on a CNJ number (RR-1000-12.2020.5.03.0001)
    re.compile(rf"\b(?:{_LABOR_SIGLAS})\b\s*-?\s*{_CNJ_NUM}"),
    # a CNJ number introduced as a precedent by a recurso/court indicator
    re.compile(rf"\b(?:{_RECURSO_PREFIX})\s+(?:n[º°.]?\s*)?{_CNJ_NUM}", re.IGNORECASE),
    # full recurso names with ordinary precedent numbers (e.g. "Recurso Especial nº 1.234.567/SP")
    re.compile(rf"\b(?:{_FULL_RECURSO_PREFIX})\s+{_QUALIFIED_NUM}", re.IGNORECASE),
    re.compile(r"\bS[uú]mula(?:\s+Vinculante)?\s+(?:n[º°.]?\s*)?\d+", re.IGNORECASE),
    re.compile(r"\bTema(?:\s+Repetitivo)?\s+(?:n[º°.]?\s*)?\d+", re.IGNORECASE),
    re.compile(r"\b(?:Tese|Precedente|Enunciado)\s+(?:n[º°.]?\s*)?\d+", re.IGNORECASE),
    re.compile(r"\bOrienta[çc][ãa]o\s+Jurisprudencial\s+(?:n[º°.]?\s*)?\d+", re.IGNORECASE),
]


@dataclass(frozen=True, slots=True)
class CitationCheck:
    """Result of checking a single [CITE:] marker."""

    raw_marker: str
    source_id: str
    resolved: bool
    available_excerpt: str | None
    span_in_draft: tuple[int, int]


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Result of verifying all citations in a draft."""

    all_passed: bool
    checks: list[CitationCheck] = field(default_factory=list)
    failed: list[CitationCheck] = field(default_factory=list)
    spurious_citations: list[str] = field(default_factory=list)


class GroundingStatus(StrEnum):
    """Publication status for LLM text after deterministic citation checks."""

    VERIFIED = "verified"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class GroundingReport:
    """Deterministic grounding summary used by product surfaces."""

    status: GroundingStatus
    verified_citation_ids: list[str] = field(default_factory=list)
    failed_citation_ids: list[str] = field(default_factory=list)
    spurious_citations: list[str] = field(default_factory=list)
    reason: str | None = None

    @classmethod
    def verified(cls, checks: list[CitationCheck] | None = None) -> GroundingReport:
        return cls(
            status=GroundingStatus.VERIFIED,
            verified_citation_ids=[c.source_id for c in checks or [] if c.resolved],
        )

    @property
    def is_verified(self) -> bool:
        return self.status == GroundingStatus.VERIFIED


def build_grounding_report(
    verification: VerificationResult | None,
) -> GroundingReport:
    """Convert low-level citation checks into a product-level safety status."""

    if verification is None:
        return GroundingReport(
            status=GroundingStatus.BLOCKED,
            reason="verificacao_nao_executada",
        )

    if verification.all_passed:
        return GroundingReport.verified(verification.checks)

    reasons: list[str] = []
    if verification.failed:
        reasons.append("citacoes_invalidas")
    if verification.spurious_citations:
        reasons.append("citacoes_sem_marcador")

    return GroundingReport(
        status=GroundingStatus.BLOCKED,
        verified_citation_ids=[c.source_id for c in verification.checks if c.resolved],
        failed_citation_ids=[c.source_id for c in verification.failed],
        spurious_citations=list(verification.spurious_citations),
        reason="+".join(reasons) or "grounding_falhou",
    )


class MarkerCitationVerifier:
    """Verifies [CITE:source_id] markers in draft petitions.

    Deterministic, no LLM required. Sub-100ms for typical drafts.
    """

    def __init__(self, repertory: RepertoryService) -> None:
        self._repertory = repertory

    def verify(
        self,
        draft: str,
        allowed_source_ids: set[str] | None = None,
    ) -> VerificationResult:
        """Verify all [CITE:] markers and detect spurious prose citations.

        Args:
            draft: The draft petition text.
            allowed_source_ids: If provided, only these source_ids are valid.

        Returns:
            VerificationResult with all checks and spurious citations.
        """
        if not draft:
            return VerificationResult(all_passed=True)

        checks: list[CitationCheck] = []
        failed: list[CitationCheck] = []

        # 1. Find and verify all [CITE:] markers
        for match in _CITE_PATTERN.finditer(draft):
            source_id = match.group(1)
            raw_marker = match.group(0)
            span = match.span()

            if allowed_source_ids is not None:
                resolved = source_id in allowed_source_ids
                excerpt = None
            else:
                resolved, excerpt = resolve_source_id(source_id, self._repertory)

            check = CitationCheck(
                raw_marker=raw_marker,
                source_id=source_id,
                resolved=resolved,
                available_excerpt=excerpt,
                span_in_draft=span,
            )
            checks.append(check)
            if not resolved:
                failed.append(check)

        # 2. Detect spurious prose citations not anchored to [CITE:]
        spurious = self._find_spurious_citations(draft)

        all_passed = len(failed) == 0 and len(spurious) == 0

        return VerificationResult(
            all_passed=all_passed,
            checks=checks,
            failed=failed,
            spurious_citations=spurious,
        )

    def _find_spurious_citations(self, draft: str) -> list[str]:
        """Find raw case references in prose that are NOT inside a ``[CITE:]`` marker.

        A raw jurisprudence reference is anchored only when its span is *contained*
        within an actual ``[CITE:...]`` bracket pair — proximity to a marker is not
        enough (a fabricated ``REsp`` next to a real marker for a different source was
        the evasion). No doctrine lead-in ("conforme leciona") exempts a case
        reference — that exception is only for academic citations, handled elsewhere.
        """
        spurious: list[str] = []
        cite_spans = [(m.start(), m.end()) for m in _CITE_PATTERN.finditer(draft)]

        def _inside_marker(start: int, end: int) -> bool:
            return any(s <= start and end <= e for s, e in cite_spans)

        def _followed_by_marker(end: int) -> bool:
            # The readable name of a grounded source is cited THEN marked, e.g.
            # "Súmula 297 do STJ [CITE:src-1]". A [CITE:] marker within the same sentence
            # AFTER the reference anchors it. (The evasion is the opposite order — a fake
            # AFTER a marker — so a *preceding* marker never anchors here.)
            for s, _e in cite_spans:
                if s < end:
                    continue
                between = draft[end:s]
                if len(between) > 60:
                    break
                return re.search(r"[.!?;]\s", between) is None
            return False

        for pattern in _RAW_CASE_PATTERNS:
            for match in pattern.finditer(draft):
                if _inside_marker(match.start(), match.end()) or _followed_by_marker(match.end()):
                    continue
                raw_text = match.group(0).strip()
                if raw_text not in spurious:
                    spurious.append(raw_text)

        return spurious
