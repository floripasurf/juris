"""Document chunking strategies for legal texts.

Splits legal documents into chunks suitable for embedding and retrieval.
Different strategies for ementas, acórdãos, and súmulas.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte

_MAX_CHUNK_TOKENS = 512
_OVERLAP_TOKENS = 64
_APPROX_CHARS_PER_TOKEN = 4


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """A chunk of a legal document ready for embedding.

    Args:
        chunk_id: Unique identifier for this chunk.
        source_id: ID of the parent FonteJurisprudencia.
        source_type: Type of the parent source.
        text: Chunk text content.
        metadata: Additional metadata.
        position: Position index within the parent document.
        uso: uso resolvido — fundamento/estilo; vazio = derivar do source_type.
    """

    chunk_id: str
    source_id: str
    source_type: TipoFonte
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    position: int = 0
    uso: str = ""


def _make_chunk_id(source_id: str, position: int) -> str:
    """Generate a deterministic chunk ID."""
    raw = f"{source_id}::{position}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _split_by_tokens(
    text: str,
    max_tokens: int = _MAX_CHUNK_TOKENS,
    overlap_tokens: int = _OVERLAP_TOKENS,
) -> list[str]:
    """Split text into overlapping chunks by approximate token count.

    Args:
        text: Text to split.
        max_tokens: Maximum tokens per chunk.
        overlap_tokens: Number of overlapping tokens between chunks.

    Returns:
        List of text chunks.
    """
    max_chars = max_tokens * _APPROX_CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * _APPROX_CHARS_PER_TOKEN

    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end < len(text):
            # Try to break at sentence boundary
            boundary = text.rfind(". ", start + max_chars // 2, end)
            if boundary > start:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap_chars
        if start >= len(text):
            break

    return chunks


def _build_metadata(fonte: FonteJurisprudencia) -> dict[str, Any]:
    """Build metadata dict from a FonteJurisprudencia."""
    from juris.repertory.corpus.status import is_active

    meta: dict[str, Any] = {
        "tribunal": fonte.tribunal,
        "tipo": fonte.tipo.value,
        "numero": fonte.numero,
        "hierarquia": fonte.hierarquia,
        "situacao": fonte.situacao,
        # Normalised vigência for the composite filter (ADR-0017): per-tipo
        # is_active semantics, so the ranker need not know each tipo's statuses.
        "vigente": is_active(fonte.tipo, fonte.situacao),
    }
    if fonte.temas:
        meta["temas"] = fonte.temas
    if fonte.base_legal:
        meta["base_legal"] = fonte.base_legal
    if fonte.relator:
        meta["relator"] = fonte.relator
    if fonte.data_julgamento:
        meta["data_julgamento"] = fonte.data_julgamento.isoformat()
    if fonte.source_url:
        meta["source_url"] = fonte.source_url
    return meta


def chunk_ementa(fonte: FonteJurisprudencia) -> list[DocumentChunk]:
    """Chunk an ementa — kept whole, no split.

    Args:
        fonte: The jurisprudence source.

    Returns:
        Single-element list with the full ementa as one chunk.
    """
    if not fonte.ementa:
        return []
    chunk_id = _make_chunk_id(fonte.id, 0)
    return [
        DocumentChunk(
            chunk_id=chunk_id,
            source_id=fonte.id,
            source_type=fonte.tipo,
            text=fonte.ementa,
            metadata=_build_metadata(fonte),
            position=0,
        )
    ]


def chunk_acordao(fonte: FonteJurisprudencia) -> list[DocumentChunk]:
    """Chunk an acórdão — split full text by section (512 tokens, 64 overlap).

    Args:
        fonte: The jurisprudence source.

    Returns:
        List of chunks from the full text, plus the ementa as chunk 0.
    """
    chunks = chunk_ementa(fonte)
    if not fonte.texto_integral:
        return chunks

    # Split by legal document sections first
    sections = re.split(
        r"\n(?=(?:EMENTA|ACÓRDÃO|VOTO|RELATÓRIO|DISPOSITIVO|CONCLUSÃO)\b)",
        fonte.texto_integral,
        flags=re.IGNORECASE,
    )

    position = len(chunks)
    meta = _build_metadata(fonte)

    for section in sections:
        text_chunks = _split_by_tokens(section.strip())
        for text in text_chunks:
            if not text:
                continue
            chunk_id = _make_chunk_id(fonte.id, position)
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    source_id=fonte.id,
                    source_type=fonte.tipo,
                    text=text,
                    metadata=meta,
                    position=position,
                )
            )
            position += 1

    return chunks


def chunk_sumula(fonte: FonteJurisprudencia) -> list[DocumentChunk]:
    """Chunk a súmula — whole text as a single chunk.

    Args:
        fonte: The jurisprudence source.

    Returns:
        Single-element list with the full súmula text.
    """
    text = fonte.texto_integral or fonte.ementa
    if not text:
        return []
    chunk_id = _make_chunk_id(fonte.id, 0)
    return [
        DocumentChunk(
            chunk_id=chunk_id,
            source_id=fonte.id,
            source_type=fonte.tipo,
            text=text,
            metadata=_build_metadata(fonte),
            position=0,
        )
    ]


_TEMPLATE_SECTION_RE = re.compile(
    r"^(?:"
    r"(?:I{1,4}V?|V?I{0,3}|[0-9]+)\s*[\.\)\-–—]\s*(?:D[OAE]S?\s+)?"
    r"|"
    r"(?:D[OAE]S?\s+)"
    r")"
    r"(?:FATOS?|DIREITO|PEDIDOS?|REQUERIMENTOS?|PRELIMINAR|M[ÉE]RITO|"
    r"FUNDAMENTA[ÇC][ÃA]O|CONCLUS[ÃA]O|PROVAS?|TUTELA|CAUSA DE PEDIR|"
    r"VALOR DA CAUSA|ENDERE[ÇC]AMENTO|QUALIFICA[ÇC][ÃA]O|COMPET[ÊE]NCIA)",
    re.IGNORECASE | re.MULTILINE,
)


def chunk_template(fonte: FonteJurisprudencia) -> list[DocumentChunk]:
    """Chunk a petition template by section headers.

    Args:
        fonte: The jurisprudence source (tipo=MODELO_PETICAO).

    Returns:
        List of chunks, one per section. Sub-splits if >512 tokens.
    """
    text = fonte.texto_integral or fonte.ementa
    if not text:
        return []

    meta = _build_metadata(fonte)
    chunks: list[DocumentChunk] = []

    # Split by section headers
    splits = _TEMPLATE_SECTION_RE.split(text)
    sections = [s.strip() for s in splits if s and s.strip()]

    if not sections:
        sections = [text]

    position = 0
    for section in sections:
        sub_chunks = _split_by_tokens(section)
        for sub in sub_chunks:
            if not sub:
                continue
            chunk_id = _make_chunk_id(fonte.id, position)
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    source_id=fonte.id,
                    source_type=fonte.tipo,
                    text=sub,
                    metadata=meta,
                    position=position,
                )
            )
            position += 1

    return chunks


def chunk_doutrina(fonte: FonteJurisprudencia) -> list[DocumentChunk]:
    """Chunk doutrina text by paragraphs, merging small ones.

    Args:
        fonte: The jurisprudence source (tipo=DOUTRINA_PD).

    Returns:
        List of chunks with 64-token overlap between consecutive chunks.
    """
    text = fonte.texto_integral or fonte.ementa
    if not text:
        return []

    meta = _build_metadata(fonte)

    # Split into paragraphs, merge small ones up to max tokens
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    merged: list[str] = []
    buffer = ""
    max_chars = _MAX_CHUNK_TOKENS * _APPROX_CHARS_PER_TOKEN

    for para in paragraphs:
        if buffer and len(buffer) + len(para) + 2 > max_chars:
            merged.append(buffer)
            # Overlap: keep last ~64 tokens
            overlap_chars = _OVERLAP_TOKENS * _APPROX_CHARS_PER_TOKEN
            buffer = buffer[-overlap_chars:] + "\n\n" + para if len(buffer) > overlap_chars else para
        else:
            buffer = buffer + "\n\n" + para if buffer else para

    if buffer:
        merged.append(buffer)

    chunks: list[DocumentChunk] = []
    for position, chunk_text in enumerate(merged):
        chunk_id = _make_chunk_id(fonte.id, position)
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                source_id=fonte.id,
                source_type=fonte.tipo,
                text=chunk_text,
                metadata=meta,
                position=position,
            )
        )

    return chunks


def chunk_noticia(fonte: FonteJurisprudencia) -> list[DocumentChunk]:
    """Chunk a news article — whole text, split only if >512 tokens.

    Args:
        fonte: The jurisprudence source (tipo=NOTICIA_TRIBUNAL).

    Returns:
        List of chunks (usually 1).
    """
    text = fonte.texto_integral or fonte.ementa
    if not text:
        return []

    meta = _build_metadata(fonte)
    text_chunks = _split_by_tokens(text)

    chunks: list[DocumentChunk] = []
    for position, chunk_text in enumerate(text_chunks):
        if not chunk_text:
            continue
        chunk_id = _make_chunk_id(fonte.id, position)
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                source_id=fonte.id,
                source_type=fonte.tipo,
                text=chunk_text,
                metadata=meta,
                position=position,
            )
        )

    return chunks


def chunk_fonte(fonte: FonteJurisprudencia) -> list[DocumentChunk]:
    """Dispatch to the appropriate chunking strategy based on source type.

    Args:
        fonte: The jurisprudence source to chunk.

    Returns:
        List of document chunks.
    """
    if fonte.tipo in (TipoFonte.SUMULA_VINCULANTE, TipoFonte.SUMULA):
        return chunk_sumula(fonte)
    if fonte.tipo in (TipoFonte.RE_STF, TipoFonte.RESP_REPETITIVO):
        return chunk_acordao(fonte)
    if fonte.tipo == TipoFonte.JURISPRUDENCIA_UNIFORME:
        return chunk_acordao(fonte)
    if fonte.tipo == TipoFonte.PRECEDENTE_LOCAL:
        return chunk_acordao(fonte)
    if fonte.tipo == TipoFonte.MODELO_PETICAO:
        return chunk_template(fonte)
    if fonte.tipo == TipoFonte.DOUTRINA_PD:
        return chunk_doutrina(fonte)
    if fonte.tipo == TipoFonte.NOTICIA_TRIBUNAL:
        return chunk_noticia(fonte)
    if fonte.tipo in (TipoFonte.ACORDAO_LANDMARK, TipoFonte.ACORDAO_PUBLICADO):
        return chunk_acordao(fonte)
    return chunk_ementa(fonte)
