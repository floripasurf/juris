"""Ingester for TJDFT petition templates (.docx files).

Reads .docx files from the Petiçoes/ directory, extracts text,
and creates FonteJurisprudencia entries with tipo=MODELO_PETICAO.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from docx import Document

from juris.core.sanitize import safe_error_text
from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)

_DEFAULT_SOURCE_DIR = Path(__file__).resolve().parents[4] / "Petiçoes"


def _extract_docx_text(filepath: Path) -> str:
    """Extract full text from a .docx file.

    Args:
        filepath: Path to the .docx file.

    Returns:
        Extracted text with paragraphs joined by newlines.
    """
    doc = Document(str(filepath))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _infer_tipo_peticao(filename: str) -> str:
    """Infer petition type from filename.

    Args:
        filename: The .docx filename (without path).

    Returns:
        Inferred petition type string.
    """
    name_lower = filename.lower()
    if "contestação" in name_lower or "contestacao" in name_lower:
        return "contestacao"
    if "inicial" in name_lower or "petição inicial" in name_lower:
        return "inicial"
    if "recurso" in name_lower:
        return "recurso"
    if "execução" in name_lower or "execucao" in name_lower:
        return "execucao"
    if "embargo" in name_lower:
        return "embargos"
    if "cobrança" in name_lower or "cobranca" in name_lower:
        return "cobranca"
    if "despejo" in name_lower:
        return "despejo"
    if "divórcio" in name_lower or "divorcio" in name_lower:
        return "divorcio"
    if "alimentos" in name_lower:
        return "alimentos"
    if "inventário" in name_lower or "inventario" in name_lower:
        return "inventario"
    if "habeas" in name_lower:
        return "habeas_corpus"
    if "mandado" in name_lower:
        return "mandado_seguranca"
    # Clean up number prefix for generic type
    cleaned = re.sub(r"^\d+[\.\d]*\s*", "", filename)
    cleaned = re.sub(r"\.docx$", "", cleaned, flags=re.IGNORECASE)
    return cleaned[:80]


class TJDFTModelosIngester(CorpusIngester):
    """Ingests TJDFT petition templates from .docx files.

    Args:
        source_dir: Directory containing .docx template files.
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
        """Read .docx files from the source directory.

        Returns:
            List of FonteJurisprudencia, one per template file.
        """
        if not self._source_dir.exists():
            logger.warning("TJDFT templates directory not found: %s", self._source_dir)
            return []

        docx_files = sorted(self._source_dir.glob("*.docx"))
        if self._limit is not None:
            docx_files = docx_files[: self._limit]

        fontes: list[FonteJurisprudencia] = []
        for filepath in docx_files:
            try:
                text = _extract_docx_text(filepath)
                if not text or len(text) < 20:
                    logger.debug("Skipping empty/tiny template: %s", filepath.name)
                    continue

                fonte = self._file_to_fonte(filepath, text)
                fontes.append(fonte)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read .docx %s: %s", filepath.name, safe_error_text(exc))

        logger.info("Loaded %d TJDFT templates from %s", len(fontes), self._source_dir)
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
        """Convert a .docx file to FonteJurisprudencia.

        Args:
            filepath: Path to the .docx file.
            text: Extracted text from the file.

        Returns:
            FonteJurisprudencia with tipo=MODELO_PETICAO.
        """
        filename = filepath.name
        file_hash = hashlib.sha256(filename.encode()).hexdigest()[:12]
        source_id = f"modelo_peticao_TJDFT_{file_hash}"
        tipo_peticao = _infer_tipo_peticao(filename)

        # Use first line or filename as ementa
        first_line = text.split("\n")[0].strip()[:200]
        ementa = first_line if first_line else filename

        return FonteJurisprudencia(
            id=source_id,
            tribunal="TJDFT",
            tipo=TipoFonte.MODELO_PETICAO,
            numero=filename,
            ementa=ementa,
            texto_integral=text,
            temas=[tipo_peticao],
            situacao="publicado",
            hierarquia=7,
            source_url="https://www.tjdft.jus.br/servicos/peticoes",
            source_publisher="DPDF/TJDFT",
            legal_basis="institutional_template",
        )
