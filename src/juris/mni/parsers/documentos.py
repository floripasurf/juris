"""Document processing — decode, store, and extract text from MNI documents."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from juris.core.observability import get_logger
from juris.core.storage import StorageBackend, StoredObject

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    """Result of processing a single MNI document."""

    id_documento: str
    storage_key: str
    sha256: str
    size_bytes: int
    mime_type: str
    texto_extraido: str | None = None


async def store_document(
    storage: StorageBackend,
    processo_cnj: str,
    id_documento: str,
    conteudo_base64: str,
    mime_type: str = "application/pdf",
) -> ProcessedDocument:
    """Decode a base64 document from MNI and store it.

    Args:
        storage: Storage backend (local or S3).
        processo_cnj: CNJ number for path construction.
        id_documento: Document ID from the tribunal.
        conteudo_base64: Base64-encoded document content.
        mime_type: MIME type of the document.

    Returns:
        ProcessedDocument with storage metadata.
    """
    raw_bytes = base64.b64decode(conteudo_base64)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # Build storage key: documentos/<cnj_clean>/<id_documento>.<ext>
    cnj_clean = processo_cnj.replace("-", "").replace(".", "")
    ext = _mime_to_ext(mime_type)
    storage_key = f"documentos/{cnj_clean}/{id_documento}.{ext}"

    stored = await storage.put(storage_key, raw_bytes, content_type=mime_type)

    logger.info(
        "document_stored",
        id_documento=id_documento,
        storage_key=storage_key,
        size=len(raw_bytes),
    )

    # Extract text if PDF
    texto = None
    if mime_type == "application/pdf":
        texto = extract_text_from_pdf(raw_bytes)

    return ProcessedDocument(
        id_documento=id_documento,
        storage_key=storage_key,
        sha256=sha256,
        size_bytes=len(raw_bytes),
        mime_type=mime_type,
        texto_extraido=texto,
    )


def extract_text_from_pdf(pdf_bytes: bytes) -> str | None:
    """Extract text from a PDF using pymupdf, falling back to pdfplumber.

    Args:
        pdf_bytes: Raw PDF content.

    Returns:
        Extracted text, or None if extraction fails.
    """
    # Try pymupdf (fitz) first — faster
    try:
        import pymupdf

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        texts = []
        for page in doc:
            texts.append(page.get_text())
        doc.close()
        result = "\n".join(texts).strip()
        if result:
            return result
    except Exception:
        pass

    # Fallback to pdfplumber
    try:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            texts = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
            result = "\n".join(texts).strip()
            if result:
                return result
    except Exception:
        pass

    return None


def _mime_to_ext(mime_type: str) -> str:
    """Map MIME type to file extension."""
    mapping = {
        "application/pdf": "pdf",
        "application/msword": "doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "image/jpeg": "jpg",
        "image/png": "png",
        "text/html": "html",
        "text/plain": "txt",
    }
    return mapping.get(mime_type, "bin")
