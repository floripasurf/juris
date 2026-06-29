"""Text extraction and citation parsing from petition files."""
from __future__ import annotations

import re
from pathlib import Path

from juris.core.observability import get_logger

logger = get_logger(__name__)

# Citation patterns for Brazilian legal documents
_SUMULA_RE = re.compile(
    r"[Ss][uú]mula\s+(?:[Vv]inculante\s+)?(?:n[.ºo°]?\s*)?(\d+)\s+do\s+(STF|STJ|TST|TSE)",
    re.IGNORECASE,
)
_RE_RESP_RE = re.compile(
    r"(RE|REsp|RHC|HC|MS|RMS|AgRg|EDcl)\s*(?:n[.ºo°]?\s*)?[\d.,]+",
    re.IGNORECASE,
)
_ARTIGO_RE = re.compile(
    r"[Aa]rt(?:igo)?[.s]?\s*(\d+[\w°º]*(?:\s*,\s*(?:§\s*\d+[°º]?|\w+))?)\s+d[oae]\s+(CPC|CC|CF|CDC|CLT|CP|CPP|CTN|ECA|Lei|Decreto)",
    re.IGNORECASE,
)
_LEI_RE = re.compile(
    r"Lei\s+(?:n[.ºo°]?\s*)?[\d.,]+/\d{4}",
    re.IGNORECASE,
)
_TEMA_RE = re.compile(
    r"[Tt]ema\s+(?:n[.ºo°]?\s*)?(\d+)\s+do\s+(STJ|STF|TST)",
    re.IGNORECASE,
)

_PETITION_KEYWORDS: dict[str, list[str]] = {
    "contestacao": ["contestacao", "contestação", "contesta"],
    "apelacao": ["apelacao", "apelação", "apela"],
    "agravo": ["agravo de instrumento", "agravo"],
    "embargos": ["embargos de declaracao", "embargos declaração", "embargos"],
    "recurso_especial": ["recurso especial", "resp"],
    "recurso_extraordinario": ["recurso extraordinario", "recurso extraordinário"],
    "inicial": ["inicial", "exordial", "peticao inicial", "petição inicial"],
    "contrarrazoes": ["contrarrazoes", "contrarrazões"],
}


def extract_text_from_file(path: Path) -> str:
    """Extract text from PDF (pymupdf) or read .md/.txt directly."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix in (".md", ".txt", ".text"):
        return path.read_text(encoding="utf-8")
    msg = f"Unsupported file type: {suffix}"
    raise ValueError(msg)


def _extract_pdf(path: Path) -> str:
    """Extract text from PDF using pymupdf."""
    import pymupdf

    # pymupdf ships no type stubs; the runtime API is correct (Document is iterable).
    doc = pymupdf.open(str(path))  # type: ignore[no-untyped-call]
    parts = []
    for page in doc:  # type: ignore[attr-defined]
        parts.append(page.get_text())
    doc.close()  # type: ignore[no-untyped-call]
    return "\n".join(parts)


def extract_citations(text: str) -> list[str]:
    """Extract legal citations from petition text using regex patterns."""
    citations: list[str] = []
    seen: set[str] = set()

    for pattern in [_SUMULA_RE, _RE_RESP_RE, _ARTIGO_RE, _LEI_RE, _TEMA_RE]:
        for match in pattern.finditer(text):
            raw = match.group(0).strip()
            normalized_key = re.sub(r"\s+", " ", raw).lower()
            if normalized_key not in seen:
                seen.add(normalized_key)
                citations.append(raw)

    return citations


def detect_petition_type(text: str) -> str | None:
    """Heuristic: scan first 500 chars for petition type keywords."""
    header = text[:500].lower()
    for tipo, keywords in _PETITION_KEYWORDS.items():
        for kw in keywords:
            if kw in header:
                return tipo
    return None
