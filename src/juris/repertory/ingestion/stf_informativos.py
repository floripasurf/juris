"""Ingester for STF Informativos (.pdf files).

Reads PDF files from the STF_Casos_Relevantes/Informativos/ directory,
splits each PDF into individual case digests by case number pattern,
and creates FonteJurisprudencia entries with tipo=NOTICIA_TRIBUNAL.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

import fitz  # type: ignore[import-untyped]  # pymupdf

from juris.core.sanitize import safe_error_text
from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)

_DEFAULT_SOURCE_DIR = (
    Path(__file__).resolve().parents[4] / "STF_Casos_Relevantes" / "Informativos"
)

# Matches case number patterns: RE 123456, ADI 9999, HC 12345, ADPF 635, etc.
# Anchored to start-of-line with optional whitespace preceding it.
_CASE_HEADER_RE = re.compile(
    r"(?:^|\n)"
    r"(?:"
    r"(?:ADI|ADC|ADPF|ADO|RE|ARE|RCL|HC|MS|MI|AP|Inq|Pet|ADIMC|ADCMC)"
    r"(?:\s+[\d.]+(?:[/-][A-Z]{2,3})?(?:\s+(?:MC|ED|AgR|Ref|Ref-Ref|RG)(?:-\w+)?)*)"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

# Extract all case number references in text (broader, for temas)
_CASE_REF_RE = re.compile(
    r"\b(?:ADI|ADC|ADPF|ADO|RE|ARE|RCL|HC|MS|MI|AP|Inq|Pet)\s+"
    r"[\d.]+(?:[/-][A-Z]{2,3})?(?:\s+(?:MC|ED|AgR|Ref|Ref-Ref|RG)(?:-\w+)?)*",
    re.IGNORECASE,
)


def _extract_pdf_text(filepath: Path) -> str:
    """Extract full text from a PDF file using pymupdf.

    Args:
        filepath: Path to the PDF file.

    Returns:
        Extracted text with pages joined by newlines.
    """
    doc = fitz.open(str(filepath))
    pages: list[str] = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _extract_case_refs(text: str) -> list[str]:
    """Extract all case number references from text.

    Args:
        text: Text to search for case numbers.

    Returns:
        Deduplicated list of normalised case reference strings.
    """
    matches = _CASE_REF_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        normalised = re.sub(r"\s+", " ", m.strip().upper())
        if normalised not in seen:
            seen.add(normalised)
            result.append(normalised)
    return result


def _split_into_digests(text: str) -> list[tuple[str, str]]:
    """Split informativo text into individual case digests.

    Splits on lines that look like a case number header (e.g. "ADI 5675/MG").
    Each digest is (case_header, digest_text).

    Args:
        text: Full text of the informativo PDF.

    Returns:
        List of (case_number, digest_text) tuples, or a single
        ("", full_text) if no split points are found.
    """
    # Find all match positions
    matches = list(_CASE_HEADER_RE.finditer(text))
    if not matches:
        return [("", text)]

    digests: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        header = match.group(0).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body and len(body) > 50:  # skip tiny fragments
            digests.append((header, body))

    return digests if digests else [("", text)]


class STFInformativosIngester(CorpusIngester):
    """Ingests STF Informativos from PDF files.

    Each PDF is split into individual case digests; each digest becomes
    one FonteJurisprudencia with tipo=NOTICIA_TRIBUNAL.

    Args:
        source_dir: Directory containing Informativo PDF files.
        limit: Maximum number of PDF files to process (None for all).
    """

    def __init__(
        self,
        source_dir: Path | None = None,
        limit: int | None = None,
    ) -> None:
        self._source_dir = source_dir or _DEFAULT_SOURCE_DIR
        self._limit = limit

    def fetch(self) -> list[FonteJurisprudencia]:
        """Read PDF files and split into individual case digests.

        Returns:
            List of FonteJurisprudencia, one per case digest.
        """
        if not self._source_dir.exists():
            logger.warning(
                "STF Informativos directory not found: %s", self._source_dir
            )
            return []

        pdf_files = sorted(self._source_dir.glob("*.pdf"))
        if self._limit is not None:
            pdf_files = pdf_files[: self._limit]

        fontes: list[FonteJurisprudencia] = []
        for filepath in pdf_files:
            try:
                text = _extract_pdf_text(filepath)
                if not text or len(text) < 50:
                    logger.debug("Skipping empty/tiny PDF: %s", filepath.name)
                    continue
                file_fontes = self._pdf_to_fontes(filepath, text)
                fontes.extend(file_fontes)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read PDF %s: %s", filepath.name, safe_error_text(exc))

        logger.info(
            "Loaded %d STF Informativo digests from %s",
            len(fontes),
            self._source_dir,
        )
        return fontes

    def parse(self, raw: Any) -> list[DocumentChunk]:
        """Parse a FonteJurisprudencia into document chunks.

        Args:
            raw: A FonteJurisprudencia instance.

        Returns:
            List of document chunks (dispatches to chunk_noticia).
        """
        if not isinstance(raw, FonteJurisprudencia):
            return []
        return chunk_fonte(raw)

    @staticmethod
    def _pdf_to_fontes(filepath: Path, text: str) -> list[FonteJurisprudencia]:
        """Convert a single PDF to a list of FonteJurisprudencia, one per digest.

        Args:
            filepath: Path to the PDF file.
            text: Full extracted text of the PDF.

        Returns:
            List of FonteJurisprudencia entries.
        """
        filename = filepath.name
        pdf_hash = hashlib.sha256(filename.encode()).hexdigest()[:8]

        digests = _split_into_digests(text)
        fontes: list[FonteJurisprudencia] = []

        for position, (case_header, digest_text) in enumerate(digests):
            source_id = f"noticia_tribunal_STF_info_{pdf_hash}_{position}"

            # Use the case header or first non-empty line as ementa
            first_line = digest_text.split("\n")[0].strip()[:250]
            ementa = first_line if first_line else filename

            # Extract all case references as temas
            temas = _extract_case_refs(digest_text)

            # Use the case header itself as the numero
            numero = case_header if case_header else filename

            fonte = FonteJurisprudencia(
                id=source_id,
                tribunal="STF",
                tipo=TipoFonte.NOTICIA_TRIBUNAL,
                numero=numero,
                ementa=ementa,
                texto_integral=digest_text,
                temas=temas,
                situacao="publicado",
                hierarquia=7,
                source_publisher="STF",
                legal_basis="government_publication",
            )
            fontes.append(fonte)

        return fontes
