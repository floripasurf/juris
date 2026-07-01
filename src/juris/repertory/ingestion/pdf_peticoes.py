"""PDF petition ingestion — scan, extract text, and analyze structure."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from juris.core.observability import get_logger
from juris.repertory.peticoes.extractor import extract_structure
from juris.repertory.peticoes.models import TemplatePeticao, TipoPeticao

logger = get_logger(__name__)


def scan_peticoes_dir(directory: Path | None = None) -> list[Path]:
    """Scan a directory for PDF petition files.

    Args:
        directory: Path to directory with model petitions.
            Defaults to storage/peticoes_modelo.

    Returns:
        Sorted list of PDF file paths found.
    """
    directory = directory or Path("storage/peticoes_modelo")
    if not directory.exists():
        return []
    return sorted(directory.glob("*.pdf"))


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF file using pymupdf.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Extracted text content from all pages.
    """
    import pymupdf

    doc = cast(Any, pymupdf.open(str(pdf_path)))  # type: ignore[no-untyped-call]
    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts)


async def ingest_peticoes(
    directory: Path | None = None,
    llm: Any | None = None,
    tipo_default: TipoPeticao = TipoPeticao.INICIAL,
) -> list[TemplatePeticao]:
    """Process all PDF petitions in a directory.

    Scans for PDFs, extracts text via pymupdf, then uses LLM
    to analyze the structure and build TemplatePeticao objects.

    Args:
        directory: Path to directory with model petitions.
        llm: LLM backend for structure extraction.
        tipo_default: Default petition type if not detected.

    Returns:
        List of extracted TemplatePeticao objects.
    """
    pdfs = scan_peticoes_dir(directory)
    if not pdfs:
        logger.info("ingest_peticoes_no_pdfs", directory=str(directory))
        return []

    if llm is None:
        logger.warning("ingest_peticoes_no_llm")
        return []

    templates: list[TemplatePeticao] = []

    for pdf_path in pdfs:
        petition_id = f"tpl_{pdf_path.stem}"
        logger.info("ingest_peticao_start", path=str(pdf_path), id=petition_id)

        try:
            text = extract_text_from_pdf(pdf_path)
        except Exception:
            logger.exception("ingest_peticao_pdf_error", path=str(pdf_path))
            continue

        if not text.strip():
            logger.warning("ingest_peticao_empty_text", path=str(pdf_path))
            continue

        tipo = _detect_tipo_from_filename(pdf_path.stem, tipo_default)

        try:
            template = await extract_structure(
                text=text,
                tipo_peticao=tipo,
                llm=llm,
                petition_id=petition_id,
            )
            templates.append(template)
            logger.info(
                "ingest_peticao_done",
                id=petition_id,
                sections=len(template.estrutura),
            )
        except Exception:
            logger.exception("ingest_peticao_extract_error", path=str(pdf_path))

    return templates


def _detect_tipo_from_filename(
    stem: str,
    default: TipoPeticao,
) -> TipoPeticao:
    """Attempt to detect petition type from filename.

    Args:
        stem: Filename without extension.
        default: Fallback type.

    Returns:
        Detected TipoPeticao or default.
    """
    stem_lower = stem.lower()
    mapping: dict[str, TipoPeticao] = {
        "inicial": TipoPeticao.INICIAL,
        "contestacao": TipoPeticao.CONTESTACAO,
        "apelacao": TipoPeticao.APELACAO,
        "agravo": TipoPeticao.AGRAVO_INSTRUMENTO,
        "embargos": TipoPeticao.EMBARGOS_DECLARACAO,
        "recurso_especial": TipoPeticao.RECURSO_ESPECIAL,
        "recurso_extraordinario": TipoPeticao.RECURSO_EXTRAORDINARIO,
        "contrarrazoes": TipoPeticao.CONTRARRAZOES,
        "cumprimento": TipoPeticao.CUMPRIMENTO_SENTENCA,
        "execucao": TipoPeticao.EXECUCAO,
    }
    for keyword, tipo in mapping.items():
        if keyword in stem_lower:
            return tipo
    return default
