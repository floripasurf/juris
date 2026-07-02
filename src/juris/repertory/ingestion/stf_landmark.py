"""Ingester for STF Landmark Cases PDF corpus.

Reads PDF files from the STF_Casos_Relevantes/ directory (excluding
Informativos/ subfolder), extracts text via pymupdf, and creates
FonteJurisprudencia entries with tipo=ACORDAO_LANDMARK.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, cast

from juris.core.sanitize import safe_error_text
from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)

_DEFAULT_SOURCE_DIR = Path(__file__).resolve().parents[4] / "STF_Casos_Relevantes"

# Section headers that delimit the end of the ementa block
_SECTION_HEADERS = re.compile(
    r"^\s*(ACÓRDÃO|ACORDÃO|ACÓRDAO|ACORDAO|RELATÓRIO|RELATORIO|VOTO|DISPOSITIVO"
    r"|EMENTA\s*:|DECISÃO|DECISAO|EXTRATO DE ATA|CERTIDÃO|CERTIDAO"
    r"|I\s*[-–]\s*|II\s*[-–]\s*|III\s*[-–]\s*)",
    re.MULTILINE | re.IGNORECASE,
)


def _parse_filename(stem: str) -> tuple[str, str]:
    """Parse case class and number from a PDF filename stem.

    Handles patterns like:
        ADC_12          -> ("ADC", "12")
        ADI_1856        -> ("ADI", "1856")
        ADPF_132_ADI_4277 -> ("ADPF", "132_ADI_4277")
        HC_82424        -> ("HC", "82424")

    Args:
        stem: Filename without extension (e.g. "ADC_12").

    Returns:
        Tuple of (classe, numero).
    """
    parts = stem.split("_", 1)
    if len(parts) == 2:
        return parts[0].upper(), parts[1]
    return stem.upper(), ""


def _extract_pdf_text(filepath: Path) -> str:
    """Extract full text from a PDF file using pymupdf.

    Args:
        filepath: Path to the PDF file.

    Returns:
        Concatenated text from all pages.
    """
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # type: ignore[import-untyped,no-redef]

    pages: list[str] = []
    doc = cast(Any, pymupdf.open(str(filepath)))  # type: ignore[no-untyped-call]
    try:
        for page in doc:
            pages.append(page.get_text())
    finally:
        doc.close()
    return "\n".join(pages)


def _extract_ementa(text: str) -> str:
    """Extract the ementa section from PDF text.

    Searches for an "EMENTA" or "EMENTA:" marker and captures text until
    the next section header or up to 500 characters.

    Args:
        text: Full extracted PDF text.

    Returns:
        Ementa text, stripped. Falls back to first 500 chars of text.
    """
    # Match "EMENTA" optionally followed by a colon and optional whitespace
    ementa_match = re.search(r"EMENTA\s*:?\s*", text, re.IGNORECASE)
    if not ementa_match:
        return text.strip()[:500]

    start = ementa_match.end()
    candidate = text[start:]

    # Find the next section header after the ementa
    next_section = _SECTION_HEADERS.search(candidate)
    body = candidate[:next_section.start()] if next_section and next_section.start() > 0 else candidate[:500]

    ementa = body.strip()
    # Collapse excessive whitespace while preserving paragraph structure
    ementa = re.sub(r"\n{3,}", "\n\n", ementa)
    return ementa[:500] if len(ementa) > 500 else ementa


class STFLandmarkIngester(CorpusIngester):
    """Ingests STF landmark case PDFs from the STF_Casos_Relevantes/ directory.

    Args:
        source_dir: Directory containing the case PDFs. Defaults to the
            STF_Casos_Relevantes/ folder at the project root.
        limit: Maximum number of files to ingest (None for all).
    """

    def __init__(
        self,
        source_dir: Path | None = None,
        limit: int | None = None,
    ) -> None:
        self._source_dir = source_dir or _DEFAULT_SOURCE_DIR
        self._limit = limit

    def fetch(self) -> list[FonteJurisprudencia]:
        """Walk source_dir for *.pdf files and parse each into FonteJurisprudencia.

        Excludes the Informativos/ subdirectory. Reads each PDF with pymupdf
        and infers the case class and number from the filename.

        Returns:
            List of FonteJurisprudencia, one per PDF file.
        """
        if not self._source_dir.exists():
            logger.warning("STF landmark cases directory not found: %s", self._source_dir)
            return []

        pdf_files = sorted(
            p
            for p in self._source_dir.rglob("*.pdf")
            if "Informativos" not in p.parts
        )

        if self._limit is not None:
            pdf_files = pdf_files[: self._limit]

        fontes: list[FonteJurisprudencia] = []
        for filepath in pdf_files:
            try:
                text = _extract_pdf_text(filepath)
                if not text or len(text.strip()) < 20:
                    logger.debug("Skipping empty/tiny PDF: %s", filepath.name)
                    continue
                fonte = self._file_to_fonte(filepath, text)
                fontes.append(fonte)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read PDF %s: %s", filepath.name, safe_error_text(exc))

        logger.info(
            "Loaded %d STF landmark cases from %s", len(fontes), self._source_dir
        )
        return fontes

    def parse(self, raw: Any) -> list[DocumentChunk]:
        """Parse a FonteJurisprudencia into document chunks.

        Args:
            raw: A FonteJurisprudencia instance.

        Returns:
            List of document chunks.
        """
        if not isinstance(raw, FonteJurisprudencia):
            return []
        return chunk_fonte(raw)

    @staticmethod
    def _file_to_fonte(filepath: Path, text: str) -> FonteJurisprudencia:
        """Convert a PDF file to FonteJurisprudencia.

        Args:
            filepath: Path to the PDF file.
            text: Extracted text from the PDF.

        Returns:
            FonteJurisprudencia with tipo=ACORDAO_LANDMARK.
        """
        stem = filepath.stem  # e.g. "ADC_12"
        classe, numero = _parse_filename(stem)
        source_id = f"acordao_landmark_STF_{classe}_{numero}"

        ementa = _extract_ementa(text)

        return FonteJurisprudencia(
            id=source_id,
            tribunal="STF",
            tipo=TipoFonte.ACORDAO_LANDMARK,
            numero=f"{classe}_{numero}",
            ementa=ementa,
            texto_integral=text,
            hierarquia=3,
            situacao="publicado",
            source_publisher="STF",
            legal_basis="government_publication",
        )
