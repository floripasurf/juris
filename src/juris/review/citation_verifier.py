"""Verify petition citations against the jurisprudence repertory."""
from __future__ import annotations

from juris.core.observability import get_logger
from juris.repertory.citation_lookup import normalize_citation, resolve_narrative_citation
from juris.repertory.retrieval.service import RepertoryService
from juris.review.models import CitationRef

logger = get_logger(__name__)


class RawCitationVerifier:
    """Verify prose citations extracted from a petition against the repertory."""

    def __init__(self, service: RepertoryService, tenant_id: str | None = None) -> None:
        self._service = service
        self._tenant_id = tenant_id  # scope citation resolution to this firm (+ public seed)

    def verify_citations(self, citations: list[str]) -> list[CitationRef]:
        """For each citation, search repertory. Mark found/not-found."""
        results: list[CitationRef] = []
        for raw in citations:
            normalized = normalize_citation(raw)
            found, source_id = resolve_narrative_citation(
                raw, self._service, tenant_id=self._tenant_id
            )
            results.append(CitationRef(
                raw_text=raw,
                normalized=normalized,
                found_in_repertory=found,
                repertory_match=source_id,
            ))
        return results

    @staticmethod
    def _normalize_citation(raw: str) -> str:
        """Normalize: strip whitespace, standardize abbreviations, lowercase."""
        return normalize_citation(raw)


# Backwards compatibility alias
CitationVerifier = RawCitationVerifier
