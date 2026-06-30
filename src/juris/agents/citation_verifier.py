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
_RAW_CASE_PATTERNS = [
    # strong siglas, with an optional "AgInt/AgRg/AgR no/na" compound prefix
    re.compile(
        rf"\b(?:Ag(?:Int|Rg|R)\s+n[oa]\s+)?(?:{_STRONG_SIGLAS})\b\.?\s*{_NUM_TAIL}", re.IGNORECASE
    ),
    # ambiguous siglas: case-sensitive + a qualified number only (avoids "MS 365" etc.)
    re.compile(rf"\b(?:{_AMBIGUOUS_SIGLAS})\b\.?\s*{_QUALIFIED_NUM}"),
    re.compile(r"\bS[uú]mula(?:\s+Vinculante)?\s+(?:n[º°.]?\s*)?\d+", re.IGNORECASE),
    re.compile(r"\bTema(?:\s+Repetitivo)?\s+(?:n[º°.]?\s*)?\d+", re.IGNORECASE),
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
        """Find raw case references in prose not anchored to [CITE:] markers."""
        spurious: list[str] = []

        for pattern in _RAW_CASE_PATTERNS:
            for match in pattern.finditer(draft):
                # Check if this match is inside a [CITE:] marker
                start = match.start()
                # Look backward for "[CITE:" within 50 chars
                context_before = draft[max(0, start - 50) : start]
                if "[CITE:" not in context_before:
                    # Skip academic-style citations (from doutrina sources)
                    context_around = draft[max(0, start - 100) : start]
                    if re.search(r"[Cc]onforme (?:leciona|ensina|destaca)", context_around):
                        continue
                    raw_text = match.group(0).strip()
                    if raw_text not in spurious:
                        spurious.append(raw_text)

        return spurious
