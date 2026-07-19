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

# TST OJ subseções: the seed reuses numbering across SDC/SDI-1/SDI-2/TP-OE (each
# restarts at 1 — e.g. SDI1-104 and SDI2-104 both exist), so the subseção is
# part of identity, not decoration. These fold prose variants (roman numerals,
# spacing) to the literal token used in the corpus's source_id.
_OJ_MARKER_PATTERN = re.compile(r"\boj\b")
_SDI_ROMAN_II_PATTERN = re.compile(r"\bsdi[\s-]*ii\b")
_SDI_ROMAN_I_PATTERN = re.compile(r"\bsdi[\s-]*i\b")
_SDI_ARABIC_PATTERN = re.compile(r"\bsdi[\s-]+([12])\b")
_TPOE_PATTERN = re.compile(r"\btp[\s/-]*oe\b")
_OJ_SUBSECAO_PATTERN = re.compile(r"\b(?:sdc|sdi1|sdi2|tp/oe)\b")


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


def _canonicalize_oj_subsecao_tokens(folded: str) -> str:
    """Fold OJ subseção spelling variants to the literal source_id token.

    "sdi-1"/"sdi1"/"sdi-i" -> "sdi1"; "sdi-2"/"sdi2"/"sdi-ii" -> "sdi2";
    "tp-oe"/"tp oe"/"tp/oe" -> "tp/oe" (matching the seed's literal spelling,
    slash included). Roman numerals are folded before arabic collapsing so
    "sdi-ii" doesn't get mistaken for "sdi-i" + a stray "i".
    """
    text = _SDI_ROMAN_II_PATTERN.sub("sdi2", folded)
    text = _SDI_ROMAN_I_PATTERN.sub("sdi1", text)
    text = _SDI_ARABIC_PATTERN.sub(r"sdi\1", text)
    return _TPOE_PATTERN.sub("tp/oe", text)


def _extract_oj_subsecao(normalized: str) -> tuple[bool, str | None]:
    """Detect whether a citation is about a TST OJ and, if so, its subseção.

    Args:
        normalized: Citation text already run through ``normalize_citation``.

    Returns:
        ``(is_oj, subsecao)``. ``is_oj`` is True whenever the citation uses
        the "oj" marker. ``subsecao`` is the canonical token matching the
        corpus's source_id spelling (``sdc``, ``sdi1``, ``sdi2``, ``tp/oe``),
        or ``None`` when no subseção could be recognized — an OJ citation
        with no recognizable subseção is too ambiguous (numbers restart per
        subseção in the seed) and the caller must reject it.
    """
    folded = _strip_accents(normalized)
    if not _OJ_MARKER_PATTERN.search(folded):
        return False, None
    canonical = _canonicalize_oj_subsecao_tokens(folded)
    match = _OJ_SUBSECAO_PATTERN.search(canonical)
    return True, (match.group(0) if match else None)


def _digit_bounded_search(numero: str, target: str) -> bool:
    """Substring match for número with digit boundaries on both sides.

    Plain substring matching lets "18" match inside "218" — a real seed
    collision (súmula 18 vs súmula 218 both exist per tribunal). Requiring
    no adjacent digit on either side turns that into a real mismatch.
    """
    return re.search(rf"(?<!\d){re.escape(numero)}(?!\d)", target) is not None


def _matches_identity(
    numero: str, orgao: str, result: RetrievalResult, subsecao: str | None = None
) -> bool:
    """Check whether a search result's own identity confirms número and órgão.

    A high similarity score is not identity: a different súmula from a
    different tribunal can score above threshold on a fuzzy search. This
    requires the número and órgão to actually appear in the candidate's
    source_id or in the start of its text — número matched with digit
    boundaries (see `_digit_bounded_search`) so "18" never matches "218".

    Args:
        numero: Citation number (punctuation stripped) to confirm.
        orgao: Citation court (lowercased) to confirm.
        result: A candidate search result.
        subsecao: For TST OJ citations, the canonical subseção token (e.g.
            "sdi1") that must additionally appear in the candidate's
            source_id as ``_{subsecao}-`` — the seed reuses OJ numbers
            across subseções, so this alone disambiguates SDI-1 #104 from
            SDI-2 #104. None for non-OJ citations (no extra constraint).

    Returns:
        True when número and órgão (and subseção, when applicable) are all
        corroborated by the candidate.
    """
    source_id_norm = result.source_id.lower().replace(".", "")
    texto_prefix_norm = result.texto[:200].lower().replace(".", "")
    numero_target = source_id_norm
    if subsecao is not None:
        anchor = f"_{subsecao}-"
        if anchor not in source_id_norm:
            return False
        # Anchor número to the tail after the subseção: the subseção token
        # itself ("sdi1"/"sdi2") contains a digit, so a bare digit-bounded
        # search against the full source_id would let número "1"/"2" match
        # the token instead of the actual trailing number (e.g. "OJ 2 da
        # SDI-2" wrongly confirming against SDI2-4).
        numero_target = source_id_norm.split(anchor, 1)[-1]
    numero_hit = _digit_bounded_search(numero, numero_target) or _digit_bounded_search(
        numero, texto_prefix_norm
    )
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

    TST OJ citations get an extra check: the seed reuses OJ numbers across
    subseções (SDC/SDI-1/SDI-2/TP-OE), so an OJ citation without a
    recognizable subseção (e.g. "OJ 104 do TST" with no SDI-1/SDI-2/...) is
    rejected outright — a bare number there is ambiguous, not identity.

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
    is_oj, subsecao = _extract_oj_subsecao(normalized)
    if is_oj and subsecao is None:
        return False, None
    try:
        results = repertory.search_jurisprudencia(
            query=normalized, top_k=3, tenant_id=tenant_id
        )
        for r in results:
            if r.score >= threshold and _matches_identity(numero, orgao, r, subsecao):
                return True, r.source_id
        return False, None
    except Exception:  # noqa: BLE001
        logger.warning("narrative_citation_lookup_error", citation=normalized)
        return False, None
