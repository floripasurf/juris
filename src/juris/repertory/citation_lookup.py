"""Shared citation lookup utilities for verifying citations against the repertory."""
from __future__ import annotations

import re
import unicodedata

from juris.core.observability import get_logger
from juris.repertory.ingestion.registry import REGISTRY
from juris.repertory.retrieval.service import RepertoryService, RetrievalResult

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

# Courts recognized by the ingested corpus, derived from the ingestion registry
# (never hardcoded separately) — used to confirm the órgão of a prose citation.
_KNOWN_ORGAOS: frozenset[str] = frozenset(entry.tribunal.lower() for entry in REGISTRY.values())
_ORGAO_PATTERN = re.compile(
    r"\b(?:" + "|".join(sorted(_KNOWN_ORGAOS, key=len, reverse=True)) + r")\b"
)

# Prose markers that introduce a citation's number: súmula, tema de repercussão
# geral/repetitivo, OJ, enunciado, REsp/RE/RR. Matched accent-insensitively
# (see `_strip_accents`) since `normalize_citation` lowercases but keeps diacritics.
_NUMERO_MARKER_PATTERN = re.compile(r"\b(?:sumula|tema|repetitivo|oj|enunciado|resp|re|rr)\b")
_DIGITS_PATTERN = re.compile(r"[\d.]+")


def _strip_accents(text: str) -> str:
    """Fold Portuguese diacritics away for accent-insensitive marker matching."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_citation(raw: str) -> str:
    """Normalize a citation string: strip whitespace, standardize abbreviations, lowercase."""
    text = raw.strip()
    text = re.sub(r"\s+", " ", text)
    lower = text.lower()
    for abbrev, full in _ABBREV_MAP.items():
        lower = lower.replace(abbrev, full)
    return lower


def _extract_citation_ref(normalized: str) -> tuple[str | None, str | None]:
    """Extract the (número, órgão) identity asserted by a normalized prose citation.

    Args:
        normalized: Citation text already run through ``normalize_citation``.

    Returns:
        ``(numero, orgao)`` — number with punctuation stripped, court lowercased
        — or ``(None, None)`` when either cannot be extracted. Vague prose with
        no identifiable number or court (e.g. "jurisprudência pacífica") never
        yields a partial result: identity is all-or-nothing.
    """
    folded = _strip_accents(normalized)

    numero: str | None = None
    marker_match = _NUMERO_MARKER_PATTERN.search(folded)
    if marker_match:
        digits_match = _DIGITS_PATTERN.search(folded, marker_match.end())
        if digits_match:
            numero = digits_match.group(0).replace(".", "")

    orgao_match = _ORGAO_PATTERN.search(folded)
    orgao = orgao_match.group(0) if orgao_match else None

    if numero is None or orgao is None:
        return None, None
    return numero, orgao


def _matches_identity(numero: str, orgao: str, result: RetrievalResult) -> bool:
    """Check whether a search result's own identity confirms número and órgão.

    A high similarity score is not identity: a different súmula from a
    different tribunal can score above threshold on a fuzzy search. This
    requires the número and órgão to actually appear in the candidate's
    source_id or in the start of its text.

    Args:
        numero: Citation number (punctuation stripped) to confirm.
        orgao: Citation court (lowercased) to confirm.
        result: A candidate search result.

    Returns:
        True when both número and órgão are corroborated by the candidate.
    """
    source_id_norm = result.source_id.lower().replace(".", "")
    texto_prefix_norm = result.texto[:200].lower().replace(".", "")
    numero_hit = numero in source_id_norm or numero in texto_prefix_norm
    orgao_hit = orgao in source_id_norm or orgao in texto_prefix_norm
    return numero_hit and orgao_hit


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
    """Normalize and fuzzy-search for prose citations like 'Súmula 297 do STJ'.

    A candidate only counts as verified when its número AND órgão are both
    confirmed against the candidate's own source_id/texto (see
    `_matches_identity`) — the top-scored result alone is not proof: a
    different súmula from a different tribunal can score above threshold on
    a fuzzy search. Prose with no extractable número/órgão (e.g. "jurisprudência
    pacífica") is rejected up front without even querying the repertory.

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
    numero, orgao = _extract_citation_ref(normalized)
    if numero is None or orgao is None:
        return False, None
    try:
        results = repertory.search_jurisprudencia(
            query=normalized, top_k=3, tenant_id=tenant_id
        )
        for r in results:
            if r.score >= threshold and _matches_identity(numero, orgao, r):
                return True, r.source_id
        return False, None
    except Exception:  # noqa: BLE001
        logger.warning("narrative_citation_lookup_error", citation=normalized)
        return False, None
