"""Shared citation lookup utilities for verifying citations against the repertory."""
from __future__ import annotations

import re

from juris.core.observability import get_logger
from juris.repertory.retrieval.service import RepertoryService

logger = get_logger(__name__)

# Abbreviation normalization map (shared with RawCitationVerifier)
_ABBREV_MAP: dict[str, str] = {
    "art.": "artigo",
    "arts.": "artigos",
    "n.": "numero",
    "nº": "numero",
    "n°": "numero",
    "nro.": "numero",
}


def normalize_citation(raw: str) -> str:
    """Normalize a citation string: strip whitespace, standardize abbreviations, lowercase."""
    text = raw.strip()
    text = re.sub(r"\s+", " ", text)
    lower = text.lower()
    for abbrev, full in _ABBREV_MAP.items():
        lower = lower.replace(abbrev, full)
    return lower


def resolve_source_id(
    source_id: str,
    repertory: RepertoryService,
    tenant_id: str | None = None,
) -> tuple[bool, str | None]:
    """Check if a source_id exists in the repertory.

    Args:
        source_id: The source identifier to look up.
        repertory: The repertory service to search.
        tenant_id: Scope the lookup to the public seed plus this firm's own uploads,
            so a citation never verifies against (or leaks an excerpt from) another
            tenant's private corpus.

    Returns:
        (found, excerpt) tuple. excerpt is first 200 chars of text if found.
    """
    try:
        results = repertory.search_jurisprudencia(
            query=source_id,
            top_k=5,
            tenant_id=tenant_id,
        )
        for r in results:
            if r.source_id == source_id:
                return True, r.texto[:200] if r.texto else None
        return False, None
    except Exception:  # noqa: BLE001
        logger.warning("source_id_lookup_error", source_id=source_id)
        return False, None


def resolve_narrative_citation(
    raw: str,
    repertory: RepertoryService,
    threshold: float = 0.3,
    tenant_id: str | None = None,
) -> tuple[bool, str | None]:
    """Normalize and fuzzy-search for prose citations like 'Sumula 297 do STJ'.

    Args:
        raw: Raw citation text.
        repertory: The repertory service.
        threshold: Minimum score to consider found.
        tenant_id: Scope the lookup to the public seed plus this firm's own uploads,
            so a citation never resolves against another tenant's private corpus.

    Returns:
        (found, source_id) tuple.
    """
    normalized = normalize_citation(raw)
    try:
        results = repertory.search_jurisprudencia(
            query=normalized, top_k=3, tenant_id=tenant_id
        )
        if results and results[0].score >= threshold:
            return True, results[0].source_id
        return False, None
    except Exception:  # noqa: BLE001
        logger.warning("narrative_citation_lookup_error", citation=normalized)
        return False, None
